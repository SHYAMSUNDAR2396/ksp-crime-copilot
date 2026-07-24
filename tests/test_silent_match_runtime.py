from functions.silent_match.runtime import CatalystCaseLoader, recipient_employee_ids
from functions.crime_query.db import SqliteDB
from functions.crime_query.mo_embeddings import EmbeddingError
from tools import gen_data


def test_missing_embedding_endpoint_creates_bounded_unavailable_provider(monkeypatch):
    from functions.silent_match.runtime import build_embedding_provider

    monkeypatch.delenv("QUICKML_EMBEDDINGS_ENDPOINT", raising=False)
    provider = build_embedding_provider(object())

    try:
        provider.embed_documents(["narrative"])
    except EmbeddingError as error:
        assert str(error) == "multilingual embedding provider is unavailable"
    else:
        raise AssertionError("unconfigured embedding provider must fail closed")


class DB:
    def execute_raw(self, sql):
        rows = [{
            "CaseMasterID": "1", "CrimeNo": "FIR/1",
            "CrimeRegisteredDate": "2026-06-01", "PoliceStationID": "1",
            "DistrictID": "10", "BriefFacts": "facts",
            "latitude": "12.9", "longitude": "77.6",
            "PolicePersonID": "9", "CrimeMinorHeadID": "6", "SectionID": "379",
            "AccusedName": "Ravi Kumar", "AgeYear": "30", "GenderID": "1",
        }]
        if "WHERE" in sql:
            return rows if " = 1" in sql else []
        return rows


def test_catalyst_loader_uses_fixed_case_projection_and_merges_rows():
    loader = CatalystCaseLoader(DB())
    assert "Unit.UnitID AS PoliceStationID" in loader.CASE_SQL
    assert "District.DistrictID AS DistrictID" in loader.CASE_SQL
    assert "ArrestEmployee.EmployeeID AS ArrestIOID" in loader.CASE_SQL
    case = loader(1)
    assert case["CaseMasterID"] == 1
    assert case["AccusedName"] == "Ravi Kumar"
    assert case["SectionCodes"] == ("379",)
    assert case["CrimeMinorHeadID"] == "6"
    assert case["PolicePersonID"] == 9
    assert "ReligionID" not in repr(case)


def test_catalyst_loader_collects_all_arrest_ioids():
    class ArrestDB(DB):
        def execute_raw(self, sql):
            rows = super().execute_raw(sql)
            return rows + [dict(rows[0], ArrestIOID="11"),
                           dict(rows[0], ArrestIOID="12")]

    case = CatalystCaseLoader(ArrestDB())(1)
    assert case["ArrestIOIDs"] == (11, 12)


def test_recipient_ids_include_case_owners_arrest_ios_and_command_scope():
    class RecipientDB:
        def command_employee_ids(self, district_ids):
            assert district_ids == {10, 11}
            return [3, 20]

    anchor = {"PolicePersonID": "9", "ArrestIOIDs": ("11",), "DistrictID": "10"}
    candidate = {"PolicePersonID": 12, "ArrestIOIDs": (13, 11), "DistrictID": 11}
    assert recipient_employee_ids(RecipientDB(), anchor, candidate) == (3, 9, 11, 12, 13, 20)


def test_catalyst_loader_projection_executes_against_generated_rowid_schema(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    db = SqliteDB(str(path))
    try:
        case = CatalystCaseLoader(db)(1)
        assert case["CaseMasterID"] == 1
        assert isinstance(case["ArrestIOIDs"], tuple)
        assert case["PoliceStationID"] is not None
        assert case["DistrictID"] is not None
    finally:
        db.close()


def test_catalyst_loader_preserves_all_accused_profiles():
    class MultiDB(DB):
        def execute_raw(self, sql):
            rows = super().execute_raw(sql)
            rows.append(dict(rows[0], AccusedName="Ravi K", AgeYear="31", GenderID="1"))
            return rows

    case = CatalystCaseLoader(MultiDB())(1)
    assert {profile[0] for profile in case["AccusedProfiles"]} == {"Ravi Kumar", "Ravi K"}


def test_catalyst_loader_bounds_batch_candidates_to_historical_lookback():
    class WindowDB:
        def __init__(self):
            self.queries = []

        def execute_raw(self, sql):
            self.queries.append(sql)
            return [
                {"CaseMasterID": "1", "CrimeNo": "FIR/1",
                 "CrimeRegisteredDate": "2026-06-01", "PoliceStationID": "1",
                 "DistrictID": "10", "BriefFacts": "anchor", "SectionID": "379"},
                {"CaseMasterID": "2", "CrimeNo": "FIR/2",
                 "CrimeRegisteredDate": "2025-08-01", "PoliceStationID": "2",
                 "DistrictID": "10", "BriefFacts": "candidate", "SectionID": "379"},
                {"CaseMasterID": "3", "CrimeNo": "FIR/3",
                 "CrimeRegisteredDate": "2024-01-01", "PoliceStationID": "3",
                 "DistrictID": "10", "BriefFacts": "too old", "SectionID": "379"},
            ]

    db = WindowDB()
    loader = CatalystCaseLoader(db, candidate_lookback_days=365)
    anchors, candidates = loader.load(date_window=("2026-06-01", "2026-06-30"))

    assert [row["CaseMasterID"] for row in anchors] == [1]
    assert [row["CaseMasterID"] for row in candidates] == [2]
    assert any(
        "CrimeRegisteredDate >= '2025-06-01'" in query
        and "CrimeRegisteredDate <= '2026-06-30'" in query
        for query in db.queries
    )


def test_catalyst_loader_bounds_live_candidates_before_anchor_date():
    class WindowDB:
        def __init__(self):
            self.queries = []

        def execute_raw(self, sql):
            self.queries.append(sql)
            return [{
                "CaseMasterID": "1", "CrimeNo": "FIR/1",
                "CrimeRegisteredDate": "2026-06-01", "PoliceStationID": "1",
                "DistrictID": "10", "BriefFacts": "anchor", "SectionID": "379",
            }, {
                "CaseMasterID": "2", "CrimeNo": "FIR/2",
                "CrimeRegisteredDate": "2026-05-31", "PoliceStationID": "2",
                "DistrictID": "10", "BriefFacts": "candidate", "SectionID": "379",
            }, {
                "CaseMasterID": "3", "CrimeNo": "FIR/3",
                "CrimeRegisteredDate": "2026-06-02", "PoliceStationID": "3",
                "DistrictID": "10", "BriefFacts": "future", "SectionID": "379",
            }]

    db = WindowDB()
    anchors, candidates = CatalystCaseLoader(db, candidate_lookback_days=365).load(
        anchor_case_id=1
    )

    assert [row["CaseMasterID"] for row in anchors] == [1]
    assert [row["CaseMasterID"] for row in candidates] == [2]
    assert any(
        "CrimeRegisteredDate <= '2026-06-01'" in query for query in db.queries
    )
