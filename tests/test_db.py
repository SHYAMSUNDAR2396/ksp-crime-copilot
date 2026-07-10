import pytest

from functions.crime_query import db as db_module
from functions.crime_query.rbac import Caller
from tools import gen_data


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_execute_returns_list_of_dicts(db):
    rows = db.execute('SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 3')
    assert len(rows) == 3
    assert set(rows[0]) == {"CrimeNo"}


def test_execute_returns_empty_list_not_none(db):
    rows = db.execute(
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.CrimeRegisteredDate = '1900-01-01'"
    )
    assert rows == []


def test_units_in_district(db):
    assert db.units_in_district(1) == [1, 2, 3, 4]
    assert db.units_in_district(3) == [9, 10, 11, 12]


def test_lookup_returns_distinct_sorted_values(db):
    heads = db.lookup("CrimeSubHead", "CrimeHeadName")
    assert "Two-Wheeler Theft" in heads
    assert heads == sorted(set(heads))


def test_caller_for_reads_rank_hierarchy_from_schema(db):
    caller = db.caller_for(1)
    assert isinstance(caller, Caller)
    assert caller.employee_id == 1
    assert caller.unit_id == 1
    assert caller.district_id == 1
    assert caller.rank_hierarchy == 4  # Inspector, seeded first in every unit


def test_caller_for_unknown_employee_is_none(db):
    assert db.caller_for(999999) is None


def test_append_audit_writes_a_row(db):
    before = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    db.append_audit(
        EmployeeID=1,
        RankHierarchy=4,
        Question="how many burglaries",
        GeneratedSQL="SELECT COUNT(*) FROM CaseMaster",
        ExecutedSQL="SELECT COUNT(*) FROM CaseMaster",
        CrimeNos="",
        RowCount=1,
        Timestamp="2026-07-09T10:00:00",
    )
    after = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    assert after == before + 1


def test_audit_log_is_not_reachable_through_execute(db):
    # execute() is the path generated SQL takes; AuditLog is not in the catalog,
    # so validate() rejects it long before this. This asserts the second line of
    # defence: db.execute refuses the audit table by name.
    with pytest.raises(db_module.DBError):
        db.execute('SELECT AuditLog.Question FROM AuditLog')


def test_flatten_unwraps_table_nested_rows():
    nested = [{"CaseMaster": {"CrimeNo": "1"}, "Unit": {"UnitName": "Bengaluru East"}}]
    assert db_module.ZcqlDB._flatten(nested) == [
        {"CrimeNo": "1", "UnitName": "Bengaluru East"}
    ]


class _FailingTable(object):
    def insert_row(self, fields):
        raise RuntimeError("insert_row not available")


class _FailingDatastore(object):
    def table(self, name):
        return _FailingTable()


class _StubZcql(object):
    def execute_query(self, sql):
        return []


class _StubApp(object):
    def zcql(self):
        return _StubZcql()

    def datastore(self):
        return _FailingDatastore()


def test_zcql_append_audit_raises_dberror_on_failure():
    # ZcqlDB is not exercised against a live Catalyst backend in this task
    # (that's Task 12); this only proves append_audit never silently no-ops
    # when the underlying datastore call fails.
    zdb = db_module.ZcqlDB(_StubApp())
    with pytest.raises(db_module.DBError):
        zdb.append_audit(
            EmployeeID=1,
            RankHierarchy=4,
            Question="q",
            GeneratedSQL="SELECT 1",
            ExecutedSQL="SELECT 1",
            CrimeNos="",
            RowCount=0,
            Timestamp="2026-07-09T10:00:00",
        )
