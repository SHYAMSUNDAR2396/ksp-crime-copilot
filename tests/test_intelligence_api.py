import datetime as dt

from functions.crime_query import db as db_module
from functions.crime_query import intelligence_api
from functions.crime_query.intelligence_api import handle_operation
from tools import gen_data


def _db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    return db_module.SqliteDB(str(path))


def test_fixed_projections_translate_catalyst_rowids_to_business_ids():
    assert "Unit.UnitID AS PoliceStationID" in intelligence_api.CASE_PROJECTION
    assert "District.DistrictID AS DistrictID" in intelligence_api.CASE_PROJECTION
    assert "ArrestEmployee.EmployeeID AS ArrestIOID" in intelligence_api.CASE_PROJECTION


def test_network_operation_returns_cited_scope_safe_data(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 97,
        "operation": "network",
        "case_master_id": 1,
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is False
    assert result["data"]["nodes"]
    assert any(edge["edge_type"] == "charged_under" for edge in result["data"]["edges"])
    assert result["evidence"]["citations"] == result["citations"]
    db.close()


def test_case_detail_returns_exact_visible_case_and_brief_facts(tmp_path):
    db = _db(tmp_path)
    row = db.execute_raw(
        'SELECT CrimeNo, BriefFacts FROM "CaseMaster" '
        'WHERE CaseMasterID = 1'
    )[0]

    result = handle_operation({
        "employee_id": 9,
        "operation": "case_detail",
        "crime_no": row["CrimeNo"],
    }, db, dt.date(2026, 7, 22))

    assert result["refused"] is False
    assert result["citations"] == [row["CrimeNo"]]
    assert result["data"]["case"]["CrimeNo"] == row["CrimeNo"]
    assert result["data"]["case"]["BriefFacts"] == row["BriefFacts"]
    assert "AccusedName" not in result["data"]["case"]
    db.close()


def test_case_detail_refuses_case_outside_station_scope(tmp_path):
    db = _db(tmp_path)
    row = db.execute_raw(
        'SELECT CrimeNo FROM "CaseMaster" '
        'WHERE PoliceStationID = '
        '(SELECT rowid FROM "Unit" WHERE UnitID = 1) LIMIT 1'
    )[0]

    result = handle_operation({
        "employee_id": 12,
        "operation": "case_detail",
        "crime_no": row["CrimeNo"],
    }, db, dt.date(2026, 7, 22))

    assert result["refused"] is True
    assert result["policy_code"] == "SCOPE_DENIED"
    assert result["citations"] == []
    assert row["CrimeNo"] not in result["answer"]
    db.close()


def test_analytics_operation_is_capability_gated(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 9,
        "operation": "analytics",
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is False
    assert "trends" in result["data"]
    db.close()


def test_unknown_operation_fails_without_case_data(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 1,
        "operation": "not-a-feature",
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is True
    assert result["data"] == {}
    db.close()


def test_non_string_operation_and_dimension_fail_closed(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({"employee_id": 1, "operation": []}, db)
    assert result["refused"] is True
    result = handle_operation({
        "employee_id": 97, "operation": "demographics", "dimension": [],
    }, db)
    assert result["refused"] is True
    assert result["policy_code"] == "SCOPE_DENIED"
    result = handle_operation({"employee_id": [], "operation": "analytics"}, db)
    assert result["refused"] is True
    db.close()


def test_data_store_failure_returns_bounded_service_refusal():
    class BrokenDB:
        def caller_for(self, employee_id):
            raise db_module.DBError("internal connection detail")

    result = handle_operation({"employee_id": 97, "operation": "analytics"}, BrokenDB())
    assert result["refused"] is True
    assert result["policy_code"] == "SERVICE_UNAVAILABLE"
    assert "internal connection detail" not in result["answer"]


def test_malformed_network_case_is_a_safe_refusal(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 1,
        "operation": "network",
        "case_master_id": "not-an-id",
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is True
    assert result["policy_code"] == "SCOPE_DENIED"
    db.close()


def test_profile_requires_a_case_anchor(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 1,
        "operation": "profile",
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is True
    assert result["data"] == {}
    db.close()


def test_profile_expands_to_visible_cases_sharing_resolved_accused_identity(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 97,
        "operation": "profile",
        "case_master_id": 1,
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is False
    assert result["data"]["case_count"] == len(result["data"]["linked_case_ids"])
    assert result["data"]["case_count"] > 1
    assert result["data"]["citations"]
    db.close()


def test_sensitive_demographics_are_aggregate_only_and_rank_gated(tmp_path):
    db = _db(tmp_path)
    senior = handle_operation({
        "employee_id": 97,
        "operation": "demographics",
        "dimension": "ReligionID",
    }, db, dt.date(2026, 7, 22))
    junior = handle_operation({
        "employee_id": 9,
        "operation": "demographics",
        "dimension": "ReligionID",
    }, db, dt.date(2026, 7, 22))
    assert senior["refused"] is False
    assert senior["data"]["aggregate_only"] is True
    assert junior["refused"] is True
    assert junior["policy_code"] == "SENSITIVE_FIELD_DENIED"
    db.close()


def test_demographics_include_case_scoped_victims_and_accused(tmp_path):
    db = _db(tmp_path)
    result = handle_operation({
        "employee_id": 97,
        "operation": "demographics",
        "dimension": "GenderID",
    }, db, dt.date(2026, 7, 22))
    assert result["refused"] is False
    assert result["data"]["row_count"] > 5000
    assert result["data"]["aggregate_only"] is True
    db.close()
