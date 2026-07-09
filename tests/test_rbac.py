import pytest

from functions.crime_query import rbac, validate
from functions.crime_query.rbac import Caller, RbacError

CONSTABLE = Caller(employee_id=9, unit_id=3, district_id=1, rank_hierarchy=6)
INSPECTOR = Caller(employee_id=1, unit_id=1, district_id=1, rank_hierarchy=4)
SP = Caller(employee_id=97, unit_id=1, district_id=1, rank_hierarchy=3)
DGP = Caller(employee_id=100, unit_id=1, district_id=1, rank_hierarchy=1)


class FakeDB:
    def units_in_district(self, district_id):
        return {1: [1, 2, 3, 4], 2: [5, 6, 7, 8], 3: [9, 10, 11, 12]}[district_id]


def scoped(sql, caller, db=None):
    ast = validate.validate(sql)
    units = rbac.allowed_units(caller, db or FakeDB())
    return rbac.apply(ast, caller, units)


def test_constable_is_scoped_to_own_unit():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', CONSTABLE)
    assert 'IN (3)' in sql.replace(' ', ' ')


def test_inspector_is_scoped_to_district_units():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', INSPECTOR)
    assert 'IN (1, 2, 3, 4)' in sql


def test_dgp_gets_no_unit_predicate():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', DGP)
    assert 'PoliceStationID' not in sql


def test_scope_uses_the_casemaster_alias():
    sql, _ = scoped(
        'SELECT cm.CrimeNo FROM CaseMaster cm', CONSTABLE
    )
    assert 'cm.PoliceStationID IN (3)' in sql


def test_existing_or_condition_is_parenthesised_before_anding_scope():
    sql, _ = scoped(
        'SELECT CaseMaster.CrimeNo FROM CaseMaster '
        "WHERE CaseMaster.CaseStatusID = 1 OR CaseMaster.CaseStatusID = 2",
        CONSTABLE,
    )
    assert '(' in sql.split('WHERE', 1)[1].split('AND')[0]
    # The bypass this guards against: OR binding looser than AND.
    assert 'OR CaseMaster.CaseStatusID = 2 AND' not in sql


def test_lookup_only_query_is_not_scoped():
    sql, _ = scoped('SELECT District.DistrictName FROM District', CONSTABLE)
    assert 'PoliceStationID' not in sql


def test_sensitive_column_in_where_is_rejected_for_everyone():
    for caller in (CONSTABLE, INSPECTOR, SP, DGP):
        with pytest.raises(RbacError):
            scoped(
                'SELECT CaseMaster.CrimeNo FROM CaseMaster '
                'LEFT JOIN ComplainantDetails '
                'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
                'WHERE ComplainantDetails.CasteID = 2',
                caller,
            )


def test_sensitive_column_in_projection_is_redacted_for_constable():
    sql, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        CONSTABLE,
    )
    assert redact == ["CasteID"]
    assert 'CasteID' in sql  # still selected; the value is masked after execution


def test_sp_aggregate_over_sensitive_column_is_not_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
        'GROUP BY ComplainantDetails.CasteID',
        SP,
    )
    assert redact == []


def test_sp_row_level_sensitive_column_is_still_redacted():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        SP,
    )
    assert redact == ["CasteID"]


def test_inspector_aggregate_over_sensitive_column_is_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.ReligionID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
        'GROUP BY ComplainantDetails.ReligionID',
        INSPECTOR,
    )
    assert redact == ["ReligionID"]


def test_redact_key_follows_the_alias():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID AS caste FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        CONSTABLE,
    )
    assert redact == ["caste"]


def test_redact_rows_replaces_only_named_keys():
    rows = [{"CrimeNo": "1" * 18, "CasteID": 2}]
    out = rbac.redact_rows(rows, ["CasteID"])
    assert out == [{"CrimeNo": "1" * 18, "CasteID": rbac.MASK}]
    assert rows[0]["CasteID"] == 2  # input not mutated


def test_allowed_units_tiers():
    db = FakeDB()
    assert rbac.allowed_units(DGP, db) is None
    assert rbac.allowed_units(SP, db) == [1, 2, 3, 4]
    assert rbac.allowed_units(INSPECTOR, db) == [1, 2, 3, 4]
    assert rbac.allowed_units(CONSTABLE, db) == [3]
