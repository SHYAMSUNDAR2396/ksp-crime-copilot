import sqlite3

import pytest

from functions.crime_query import rbac, validate
from functions.crime_query.rbac import Caller, RbacError
from tools import gen_data

CONSTABLE = Caller(employee_id=9, unit_id=3, district_id=1, rank_hierarchy=6)
INSPECTOR = Caller(employee_id=1, unit_id=1, district_id=1, rank_hierarchy=4)
SP = Caller(employee_id=97, unit_id=1, district_id=1, rank_hierarchy=3)
DGP = Caller(employee_id=100, unit_id=1, district_id=1, rank_hierarchy=1)


class FakeDB:
    def units_in_district(self, district_id):
        return {1: [1, 2, 3, 4], 2: [5, 6, 7, 8], 3: [9, 10, 11, 12]}[district_id]


class RowIdDB(FakeDB):
    def unit_rowids_for_business_ids(self, unit_ids):
        return [value + 1000 for value in unit_ids]


def scoped(sql, caller, db=None):
    ast = validate.validate(sql)
    units = rbac.allowed_units(caller, db or FakeDB())
    return rbac.apply(ast, caller, units)


@pytest.fixture(scope="module")
def crime_db(tmp_path_factory):
    """A real sqlite build of the schema, for end-to-end leak-closure checks.
    Uses gen_data.build() directly (same pattern as tests/test_gen_data.py)
    rather than shelling out, so it's hermetic under pytest and needs no
    pre-built build/crime.db on disk.
    """
    out = tmp_path_factory.mktemp("rbac_e2e")
    gen_data.build(str(out / "crime.db"), csv_dir=str(out / "csv"))
    conn = sqlite3.connect(str(out / "crime.db"))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


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


def test_scope_predicate_uses_catalyst_unit_rowids_when_backend_maps_them():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', CONSTABLE, RowIdDB())
    assert 'PoliceStationID IN (1003)' in sql


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
                'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
                'WHERE ComplainantDetails.CasteID = 2',
                caller,
            )


def test_sensitive_column_in_projection_is_redacted_for_constable():
    sql, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID',
        CONSTABLE,
    )
    assert redact == ["CasteID"]
    assert 'CasteID' in sql  # still selected; the value is masked after execution


def test_sp_aggregate_over_sensitive_column_is_not_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID',
        SP,
    )
    assert redact == []


def test_sp_row_level_sensitive_column_is_still_redacted():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID',
        SP,
    )
    assert redact == ["CasteID"]


def test_inspector_aggregate_over_sensitive_column_is_rejected():
    with pytest.raises(RbacError):
        scoped(
            'SELECT ComplainantDetails.ReligionID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
            'LEFT JOIN ComplainantDetails '
            'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
            'GROUP BY ComplainantDetails.ReligionID',
            INSPECTOR,
        )


def test_constable_aggregate_over_sensitive_column_is_rejected():
    with pytest.raises(RbacError):
        scoped(
            'SELECT ComplainantDetails.ReligionID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
            'LEFT JOIN ComplainantDetails '
            'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
            'GROUP BY ComplainantDetails.ReligionID',
            CONSTABLE,
        )


def test_dgp_aggregate_over_sensitive_column_is_not_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID',
        DGP,
    )
    assert redact == []


def test_constable_cannot_infer_caste_distribution_by_group_position():
    """Regression for the leak this fix closes: GROUP BY row-position lets a
    masked caste distribution be recovered by an unauthorised caller. The
    exception must be rejected outright, not redacted, for anyone below SP.
    """
    with pytest.raises(RbacError):
        scoped(
            'SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) AS n '
            'FROM CaseMaster '
            'LEFT JOIN ComplainantDetails '
            'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
            'GROUP BY ComplainantDetails.CasteID',
            CONSTABLE,
        )


def test_redact_key_follows_the_alias():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID AS caste FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID',
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


# --- Leak A: sensitive column wrapped in an aggregate function escapes redaction ---

@pytest.mark.parametrize("func", ["MIN", "MAX", "SUM", "AVG"])
def test_aggregate_over_sensitive_column_is_rejected_for_constable(func):
    with pytest.raises(RbacError):
        scoped(
            'SELECT {0}(ComplainantDetails.CasteID) FROM CaseMaster '
            'LEFT JOIN ComplainantDetails '
            'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID'.format(func),
            CONSTABLE,
        )


@pytest.mark.parametrize("func", ["MIN", "MAX", "SUM", "AVG"])
def test_aggregate_over_sensitive_column_is_rejected_for_dgp(func):
    """Proves the rejection is not rank-gated: even the DGP, who is exempt
    from redaction on a bare sensitive projection, cannot launder the value
    through a function wrapper."""
    with pytest.raises(RbacError):
        scoped(
            'SELECT {0}(ComplainantDetails.CasteID) FROM CaseMaster '
            'LEFT JOIN ComplainantDetails '
            'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID'.format(func),
            DGP,
        )


# --- Leak B: a token GROUP BY on a row-identifying key defeats "aggregates only" ---

def test_sp_group_by_crimeno_and_caste_is_redacted_not_exempted():
    """CrimeNo is case-scoped, so GROUP BY CrimeNo, CasteID makes every group
    a single complainant in disguise as an aggregate. The exemption must not
    be granted -- the query still runs, but the caste column is redacted."""
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID, '
        'COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY CaseMaster.CrimeNo, ComplainantDetails.CasteID',
        SP,
    )
    assert redact == ["CasteID"]


def test_sp_group_by_lookup_table_and_caste_keeps_exemption():
    """CrimeSubHead is a lookup/dimension table (not in CASE_SCOPED_TABLES),
    so grouping by it alongside CasteID is a genuine demographic aggregate
    and the exemption still applies."""
    _, redact = scoped(
        'SELECT CrimeSubHead.CrimeHeadName, ComplainantDetails.CasteID, '
        'COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'LEFT JOIN CrimeSubHead '
        'ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.ROWID '
        'GROUP BY CrimeSubHead.CrimeHeadName, ComplainantDetails.CasteID',
        SP,
    )
    assert redact == []


# --- End-to-end leak closures against the real generated database ---

def test_aggregate_wrap_leak_is_closed_end_to_end(crime_db):
    """Exploit A end to end: MIN(CasteID) must never execute -- rejected for
    every rank, so no cleartext caste value can reach the caller."""
    sql = (
        'SELECT MIN(ComplainantDetails.CasteID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID'
    )
    ast = validate.validate(sql)
    for caller in (CONSTABLE, INSPECTOR, SP, DGP):
        units = rbac.allowed_units(caller, FakeDB())
        with pytest.raises(RbacError):
            rbac.apply(ast, caller, units)


# --- Leak C: a query-global "authorised" exemption clears the whole ---
# --- projection even when only ONE sensitive column is a GROUP BY key ---

def test_sensitive_column_outside_group_by_is_redacted_even_when_caste_is_grouped():
    """The leak: SP groups by CasteID (a safe aggregate dimension) but also
    projects ReligionID, which is neither grouped nor aggregated. ReligionID
    must be redacted; CasteID, the actual grouping key, stays clear."""
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID, ComplainantDetails.ReligionID '
        'FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID',
        SP,
    )
    assert "ReligionID" in redact
    assert "CasteID" not in redact


def test_sensitive_column_outside_group_by_is_redacted_for_dgp_too():
    """Same query as above for DGP -- proves the redaction isn't rank-gated
    away; DGP is exempt from redaction only on the column actually grouped."""
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID, ComplainantDetails.ReligionID '
        'FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID',
        DGP,
    )
    assert "ReligionID" in redact
    assert "CasteID" not in redact


def test_sp_group_by_both_sensitive_columns_keeps_both_clear():
    """When both sensitive columns are themselves GROUP BY keys, both are
    legitimate aggregate dimensions and both stay clear."""
    _, redact = scoped(
        'SELECT ComplainantDetails.CasteID, ComplainantDetails.ReligionID, '
        'COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID, ComplainantDetails.ReligionID',
        SP,
    )
    assert redact == []


def test_leak_c_closed_end_to_end(crime_db):
    """Exploit C end to end against the real database: SP and DGP get
    ReligionID masked in every row while CasteID (the actual GROUP BY key)
    comes through as real integers. Constable/Inspector are still rejected
    outright because CasteID in GROUP BY is never structurally accepted for
    junior ranks."""
    sql = (
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID, ComplainantDetails.ReligionID '
        'FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY ComplainantDetails.CasteID'
    )
    ast = validate.validate(sql)

    for caller in (CONSTABLE, INSPECTOR):
        units = rbac.allowed_units(caller, FakeDB())
        with pytest.raises(RbacError):
            rbac.apply(ast, caller, units)

    for caller in (SP, DGP):
        units = rbac.allowed_units(caller, FakeDB())
        rewritten_sql, redact = rbac.apply(ast, caller, units)
        assert "ReligionID" in redact
        assert "CasteID" not in redact
        rows = [dict(row) for row in crime_db.execute(rewritten_sql).fetchall()]
        assert rows, "expected at least one row for caller {0}".format(caller)
        masked = rbac.redact_rows(rows, redact)
        for row in masked:
            assert row["ReligionID"] == rbac.MASK
            assert isinstance(row["CasteID"], int)


def test_token_group_by_leak_is_closed_end_to_end(crime_db):
    """Exploit B end to end, across all four ranks. SP/DGP were the leaky
    case (rank <= SENSITIVE_MAX_HIERARCHY made `authorised` true from the
    mere presence of a GROUP BY, regardless of which columns it grouped):
    the query now runs for them but every CasteID cell is masked, never
    clear. CONSTABLE/INSPECTOR were never leaky here -- a bare sensitive
    column in GROUP BY was already rejected outright for junior ranks before
    this fix, and still is (see test_constable_aggregate_over_sensitive_column_is_rejected);
    that's a stricter outcome than redaction, so no cleartext caste value
    reaches any of the four ranks either way."""
    sql = (
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID, '
        'COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID '
        'GROUP BY CaseMaster.CrimeNo, ComplainantDetails.CasteID'
    )
    ast = validate.validate(sql)

    for caller in (CONSTABLE, INSPECTOR):
        units = rbac.allowed_units(caller, FakeDB())
        with pytest.raises(RbacError):
            rbac.apply(ast, caller, units)

    for caller in (SP, DGP):
        units = rbac.allowed_units(caller, FakeDB())
        rewritten_sql, redact = rbac.apply(ast, caller, units)
        assert redact == ["CasteID"], "exemption must not be granted for {0}".format(caller)
        rows = [dict(row) for row in crime_db.execute(rewritten_sql).fetchall()]
        assert rows, "expected at least one row for caller {0}".format(caller)
        masked = rbac.redact_rows(rows, redact)
        for row in masked:
            assert row["CasteID"] == rbac.MASK
