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
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster EXCEPT SELECT Unit.UnitName FROM Unit',
         'not allowed'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster INTERSECT SELECT Unit.UnitName FROM Unit',
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


# --- Finding 1: LIMIT bypass regression tests -------------------------------
#
# sqlglot parses `LIMIT -1` as Neg(Literal(1)) and `LIMIT 10+10` as
# Add(Literal(10), Literal(10)); `.name` on either node returns just the
# inner literal text, so a naive `int(limit.expression.name)` reads a
# plausible in-range value and returns the AST untouched -- `LIMIT -1` means
# "no limit" in SQLite. Assert on the rendered SQL, not just "no crash",
# because the bug was exactly that: no crash, and an unclamped AST returned.
@pytest.mark.parametrize(
    "limit_clause",
    [
        "LIMIT -1",
        "LIMIT 10+10",
        "LIMIT '500'",
        "LIMIT (200)",
        "LIMIT NULL",
        "LIMIT 1e9",
    ],
)
def test_malformed_limit_is_rejected_or_clamped(limit_clause):
    sql = 'SELECT CaseMaster.CrimeNo FROM CaseMaster {0}'.format(limit_clause)
    try:
        ast = validate.validate(sql)
    except ValidationError:
        return
    rendered = ast.sql()
    assert 'LIMIT {0}'.format(validate.MAX_LIMIT) in rendered
    assert '-1' not in rendered
    assert '+' not in rendered


# --- Finding 1: the ORDER BY alias exception must not leak ------------------
#
# _check_columns lets a bare projection alias through only when it is under
# an exp.Order ancestor. The same bare name in WHERE, GROUP BY or HAVING is
# an invented/unqualified column and must still be rejected.
@pytest.mark.parametrize(
    "sql",
    [
        'SELECT CaseMaster.CaseCategoryID AS cat FROM CaseMaster WHERE cat = 1 LIMIT 5',
        'SELECT CaseMaster.CaseCategoryID AS cat, COUNT(*) FROM CaseMaster '
        'GROUP BY cat LIMIT 5',
        'SELECT CaseMaster.CaseCategoryID AS cat, COUNT(*) FROM CaseMaster '
        'GROUP BY CaseMaster.CaseCategoryID HAVING cat > 0 LIMIT 5',
    ],
)
def test_bare_alias_only_tolerated_in_order_by(sql):
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(sql)
    assert 'must be qualified' in str(excinfo.value).lower()


# --- Finding 2: INTERVAL is not an exp.Func, so it needs its own ban --------
def test_interval_date_arithmetic_is_rejected():
    sql = (
        'SELECT CaseMaster.CrimeNo FROM CaseMaster '
        "WHERE CaseMaster.CrimeRegisteredDate > CaseMaster.IncidentFromDate "
        "+ INTERVAL '30' DAY LIMIT 5"
    )
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(sql)
    assert 'date arithmetic' in str(excinfo.value).lower()


# --- Finding 3: identifying columns need CrimeNo even when aggregated ------
@pytest.mark.parametrize(
    "sql,identifying_fragment",
    [
        (
            'SELECT Accused.AccusedName, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
            'JOIN Accused ON Accused.CaseMasterID = CaseMaster.CaseMasterID '
            'GROUP BY Accused.AccusedName LIMIT 5',
            'AccusedName',
        ),
        (
            'SELECT CaseMaster.BriefFacts, COUNT(*) FROM CaseMaster '
            'GROUP BY CaseMaster.BriefFacts LIMIT 5',
            'BriefFacts',
        ),
        (
            'SELECT Victim.VictimName, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
            'JOIN Victim ON Victim.CaseMasterID = CaseMaster.CaseMasterID '
            'GROUP BY Victim.VictimName LIMIT 5',
            'VictimName',
        ),
    ],
)
def test_aggregate_over_identifying_column_still_needs_crimeno(sql, identifying_fragment):
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(sql)
    assert identifying_fragment in str(excinfo.value)


@pytest.mark.parametrize(
    "sql",
    [
        'SELECT COUNT(*) FROM CaseMaster',
        'SELECT District.DistrictName FROM District',
        'SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID '
        'GROUP BY Unit.UnitName LIMIT 5',
        'SELECT ComplainantDetails.ReligionID, COUNT(CaseMaster.CaseMasterID) AS n '
        'FROM CaseMaster LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
        'GROUP BY ComplainantDetails.ReligionID',
    ],
)
def test_non_identifying_aggregates_still_exempt(sql):
    assert validate.validate(sql) is not None


# --- Finding 4: cross joins and CaseMaster self-joins break the RBAC anchor -
def test_comma_join_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate('SELECT CaseMaster.CrimeNo FROM CaseMaster, Unit LIMIT 5')
    assert 'cross join' in str(excinfo.value).lower()


def test_cross_join_keyword_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(
            'SELECT CaseMaster.CrimeNo FROM CaseMaster CROSS JOIN Unit LIMIT 5'
        )
    assert 'cross join' in str(excinfo.value).lower()


def test_comma_self_join_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(
            'SELECT a.CrimeNo FROM CaseMaster a, CaseMaster b LIMIT 5'
        )
    # This shape trips the no-ON cross-join check before the dedicated
    # duplicate-table check ever runs; either message is an acceptable
    # rejection, but it must be rejected.
    message = str(excinfo.value).lower()
    assert 'cross join' in message or 'casemaster' in message


def test_explicit_self_join_is_rejected():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(
            'SELECT a.CrimeNo FROM CaseMaster a '
            'JOIN CaseMaster b ON a.CaseMasterID = b.CaseMasterID LIMIT 5'
        )
    assert 'casemaster' in str(excinfo.value).lower()
    assert 'once' in str(excinfo.value).lower()


def test_legitimate_multi_join_still_passes():
    sql = (
        'SELECT CaseMaster.CrimeNo FROM CaseMaster '
        'LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID '
        'LEFT JOIN District ON Unit.DistrictID = District.DistrictID LIMIT 5'
    )
    assert validate.validate(sql) is not None
