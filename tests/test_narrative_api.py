import datetime as dt

from functions.crime_query import db as db_module, narrative_api
from tools import gen_data


def test_narrative_api_rejects_unknown_caller_without_retrieval():
    class DB:
        def caller_for(self, employee_id):
            return None

    result = narrative_api.handle_operation(
        {"employee_id": 999, "question": "what happened?"}, DB(),
    )
    assert result["refused"] is True
    assert result["data"]["matches"] == []


def test_narrative_api_returns_scoped_original_excerpts(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    db = db_module.SqliteDB(str(path))
    result = narrative_api.handle_operation(
        {"employee_id": 97, "question": "broken lock gold cash", "limit": 3},
        db, today=dt.date(2026, 7, 22),
    )

    assert result["refused"] is False
    assert result["data"]["partial"] is True
    assert result["data"]["matches"]
    assert result["citations"]
    assert result["evidence"]["status"] == "ok"
    db.close()


def test_narrative_limit_array_returns_safe_refusal(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    db = db_module.SqliteDB(str(path))
    result = narrative_api.handle_operation(
        {"employee_id": 97, "question": "broken lock", "limit": []}, db,
    )
    assert result["refused"] is True
    assert result["data"]["matches"] == []
    db.close()


def test_narrative_data_store_failure_is_bounded():
    class BrokenDB:
        def caller_for(self, employee_id):
            from functions.crime_query.db import DBError
            raise DBError("internal connection detail")

    result = narrative_api.handle_operation({"employee_id": 97, "question": "facts"}, BrokenDB())
    assert result["refused"] is True
    assert result["policy_code"] == "SERVICE_UNAVAILABLE"
    assert "internal connection detail" not in result["answer"]
