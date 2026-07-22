from types import SimpleNamespace

from functions.crime_query.access import AccessContext
from functions.crime_query.silent_match_api import SilentMatchAPI
from functions.crime_query.mo_models import SemanticMatch
from functions.crime_query.silent_match_models import ScanResult
from functions.silent_match.main import handle_request


def context():
    return AccessContext(9, 4, "INSPECTOR", (1, 2), (10,), frozenset({
        "query_structured_cases", "retrieve_similar_cases", "view_cross_jurisdiction_alerts", "review_alerts", "dispose_alerts",
        "run_batch_scan", "run_live_scan",
    }), "rbac_masked", frozenset({"review", "Linked", "Dismissed"}), "district")


def case(case_id, station=1):
    return {"CaseMasterID": case_id, "CrimeNo": "FIR/{}".format(case_id),
            "PoliceStationID": station, "DistrictID": 10, "PolicePersonID": 9}


class Repo:
    def __init__(self):
        self.alert = {"AlertID": 1, "AlertType": "possible_linked_pattern",
                      "AnchorCaseID": 1, "MatchedCaseID": 2, "Status": "New"}

    def get_alert(self, alert_id):
        return self.alert if alert_id == 1 else None

    def append_action(self, alert_id, action, note, employee_id, now):
        self.alert["Status"] = action
        return self.alert


class Matcher:
    def similar_cases(self, source, candidates, context, limit=10):
        return [SemanticMatch(1, 2, "FIR/1", "FIR/2", .9, "High", (), "a", "b", "idx-v1")]


class Scanner:
    def scan(self, **kwargs):
        return ScanResult("run-1", kwargs["trigger_source"], 1, 1, (), 0, 0)


def api():
    cases = {1: case(1), 2: case(2, 2)}
    return SilentMatchAPI(lambda employee_id: SimpleNamespace(employee_id=employee_id),
                          lambda caller: context(),
                          lambda case_id, candidates=False: list(cases.values()) if candidates else cases.get(case_id),
                          Matcher(), Scanner(), Repo())


def test_similar_cases_response_is_cited_and_versioned():
    status, response = api().handle("POST", "/similar-cases", {"employee_id": 9, "case_master_id": 1})
    assert status == 200
    assert response["matches"][0]["source_crime_no"] == "FIR/1"
    assert response["matches"][0]["index_version"] == "idx-v1"


def test_linked_transition_requires_note():
    status, response = api().handle("POST", "/alerts/1/transition", {
        "employee_id": 9, "to_status": "Linked", "note": "",
    })
    assert status == 403
    assert "requires" in response["error"]


def test_scan_uses_live_capability():
    status, response = api().handle("POST", "/scan", {
        "employee_id": 9, "anchor_case_id": 1, "trigger_source": "live",
    })
    assert status == 200
    assert response["run_id"] == "run-1"


def test_catalyst_request_adapter_delegates_method_path_and_json():
    class Request:
        method = "POST"
        path = "/scan"

        def get_json(self, silent=True):
            return {"employee_id": 9, "anchor_case_id": 1, "trigger_source": "live"}

    body, status = handle_request(Request(), api())
    assert status == 200
    assert body["run_id"] == "run-1"
