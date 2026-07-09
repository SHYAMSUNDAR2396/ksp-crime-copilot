import pytest
import sqlglot

from functions.crime_query import validate
from functions.crime_query.validate import ValidationError

GOOD = (
    'SELECT CaseMaster.CrimeNo FROM CaseMaster '
    "WHERE CaseMaster.CrimeRegisteredDate >= '2026-01-01' LIMIT 50"
)


def test_valid_query_returns_a_select_ast():
    ast = validate.validate(GOOD)
    assert isinstance(ast, sqlglot.exp.Select)


def test_limit_is_added_when_missing():
    ast = validate.validate('SELECT CaseMaster.CrimeNo FROM CaseMaster')
    assert 'LIMIT {0}'.format(validate.MAX_LIMIT) in ast.sql()


def test_limit_above_cap_is_clamped():
    ast = validate.validate('SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 5000')
    assert 'LIMIT {0}'.format(validate.MAX_LIMIT) in ast.sql()


def test_aggregate_query_needs_no_crimeno():
    ast = validate.validate('SELECT COUNT(*) FROM CaseMaster')
    assert isinstance(ast, sqlglot.exp.Select)


def test_join_and_group_by_are_allowed():
    sql = (
        'SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID '
        'GROUP BY Unit.UnitName ORDER BY n DESC LIMIT 10'
    )
    assert validate.validate(sql) is not None


def test_lookup_only_query_needs_no_casemaster_anchor():
    assert validate.validate('SELECT District.DistrictName FROM District') is not None


def test_table_aliases_resolves_aliases_and_bare_names():
    ast = validate.validate(
        'SELECT cm.CrimeNo FROM CaseMaster cm '
        'LEFT JOIN Unit ON cm.PoliceStationID = Unit.UnitID LIMIT 5'
    )
    assert validate.table_aliases(ast) == {"cm": "CaseMaster", "Unit": "Unit"}


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ('DELETE FROM CaseMaster', 'SELECT'),
        ('UPDATE CaseMaster SET CrimeNo = 1', 'SELECT'),
        ('DROP TABLE CaseMaster', 'SELECT'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster; DROP TABLE Unit', 'one statement'),
        ('SELECT AuditLog.Question FROM AuditLog', 'unknown table'),
        ('SELECT CaseMaster.PhoneNumber FROM CaseMaster', 'unknown column'),
        ('SELECT Vehicle.PlateNo FROM Vehicle', 'unknown table'),
        ('SELECT CrimeNo FROM CaseMaster', 'must be qualified'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster WHERE CaseMasterID IN '
         '(SELECT Victim.CaseMasterID FROM Victim)', 'subquer'),
        ('WITH x AS (SELECT CaseMaster.CrimeNo FROM CaseMaster) SELECT x.CrimeNo FROM x',
         'not allowed'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster UNION SELECT Unit.UnitName FROM Unit',
         'not allowed'),
        ("SELECT UPPER(CaseMaster.CrimeNo) FROM CaseMaster", 'function'),
        ("SELECT DATE(CaseMaster.CrimeRegisteredDate) FROM CaseMaster", 'function'),
        ('SELECT Victim.VictimName FROM Victim LIMIT 5', 'CaseMaster'),
        ('SELECT CaseMaster.BriefFacts FROM CaseMaster LIMIT 5', 'CrimeNo'),
    ],
)
def test_rejections(sql, fragment):
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(sql)
    assert fragment.lower() in str(excinfo.value).lower()


def test_error_message_names_the_offending_identifier():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate('SELECT CaseMaster.PhoneNumber FROM CaseMaster')
    assert 'PhoneNumber' in str(excinfo.value)
