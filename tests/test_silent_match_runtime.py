from functions.silent_match.runtime import CatalystCaseLoader


class DB:
    def execute_raw(self, sql):
        rows = [{
            "CaseMasterID": "1", "CrimeNo": "FIR/1",
            "CrimeRegisteredDate": "2026-06-01", "PoliceStationID": "1",
            "DistrictID": "10", "BriefFacts": "facts",
            "latitude": "12.9", "longitude": "77.6",
            "AccusedName": "Ravi Kumar", "AgeYear": "30", "GenderID": "1",
        }]
        if "WHERE" in sql:
            return rows if " = 1" in sql else []
        return rows


def test_catalyst_loader_uses_fixed_case_projection_and_merges_rows():
    loader = CatalystCaseLoader(DB())
    case = loader(1)
    assert case["CaseMasterID"] == 1
    assert case["AccusedName"] == "Ravi Kumar"
    assert "ReligionID" not in repr(case)
