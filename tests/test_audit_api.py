import datetime as dt

from functions.crime_query import audit_api, db as db_module
from tools import gen_data


def _db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    return db_module.SqliteDB(str(path))


def _audit(db, employee_id, question):
    db.append_audit(
        EmployeeID=employee_id,
        RankHierarchy=4,
        Question=question,
        GeneratedSQL="SELECT CaseMaster.CrimeNo FROM CaseMaster",
        ExecutedSQL="scoped query",
        CrimeNos="FIR/1",
        RowCount=1,
        LoggedAt="2026-07-22T00:00:00",
    )


def test_audit_view_is_rank_scoped_and_does_not_accept_client_scope(tmp_path):
    db = _db(tmp_path)
    _audit(db, 9, "own or district query")
    _audit(db, 1, "same district query")

    result = audit_api.handle_operation(
        {"employee_id": 9, "district_id": 999}, db, dt.date(2026, 7, 22)
    )

    assert result["refused"] is False
    assert result["data"]["visibility"] == "district"
    assert {row["EmployeeID"] for row in result["data"]["rows"]} >= {1, 9}
    assert result["citations"] == ["FIR/1"]
    db.close()


def test_audit_view_denies_constable_without_leaking_rows(tmp_path):
    db = _db(tmp_path)
    _audit(db, 9, "private query")

    result = audit_api.handle_operation({"employee_id": 4}, db, dt.date(2026, 7, 22))

    assert result["refused"] is True
    assert result["policy_code"] == "CAPABILITY_DENIED"
    assert result["data"]["rows"] == []
    db.close()
