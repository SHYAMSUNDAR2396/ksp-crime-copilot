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

    def list_alerts(self, status=None):
        return [self.alert] if status is None or self.alert["Status"] == status else []

    def append_action(self, alert_id, action, note, employee_id, now):
        self.alert["Status"] = "Reviewing" if action == "review" else action
        return self.alert

    def recipients_for(self, alert_id):
        return [{"AlertID": alert_id, "EmployeeID": 9}]

    def actions_for(self, alert_id):
        return [{"AlertID": alert_id, "ActionType": "Seen"}]


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


def test_missing_authenticated_employee_fails_closed_without_calling_loader():
    called = []

    def caller_loader(employee_id):
        called.append(employee_id)
        return SimpleNamespace(employee_id=employee_id)

    service = SilentMatchAPI(
        caller_loader, lambda caller: context(), lambda case_id, candidates=False: None,
        Matcher(), Scanner(), Repo(),
    )
    status, response = service.handle("GET", "/alerts", {})

    assert status == 403
    assert response == {"error": "caller is not authorised"}
    assert called == []


def test_embedding_provider_failure_returns_bounded_service_error():
    class FailingMatcher:
        def similar_cases(self, *args, **kwargs):
            from functions.crime_query.mo_embeddings import EmbeddingError
            raise EmbeddingError("provider URL and response body must not escape")

    service = SilentMatchAPI(
        lambda employee_id: SimpleNamespace(employee_id=employee_id),
        lambda caller: context(),
        lambda case_id, candidates=False: [case(1)] if candidates else case(case_id),
        FailingMatcher(), Scanner(), Repo(),
    )
    status, response = service.handle(
        "POST", "/similar-cases", {"employee_id": 9, "case_master_id": 1}
    )

    assert status == 503
    assert response == {"error": "silent-match service is temporarily unavailable"}


def test_malformed_status_and_transition_values_return_client_errors():
    status, response = api().handle("GET", "/alerts", {
        "employee_id": 9, "status": [],
    })
    assert status == 400
    assert response["error"] == "unsupported alert status"

    status, response = api().handle("POST", "/alerts/1/transition", {
        "employee_id": 9, "to_status": [], "note": "x",
    })
    assert status == 400
    assert response["error"] == "unsupported alert transition"


def test_non_integer_employee_id_fails_before_loader():
    status, response = api().handle("GET", "/alerts", {"employee_id": []})
    assert status == 403
    assert response["error"] == "caller is not authorised"


def test_non_positive_employee_id_fails_before_loader():
    called = []

    def caller_loader(employee_id):
        called.append(employee_id)
        return SimpleNamespace(employee_id=employee_id)

    service = SilentMatchAPI(
        caller_loader, lambda caller: context(), lambda case_id, candidates=False: None,
        Matcher(), Scanner(), Repo(),
    )
    status, response = service.handle("GET", "/alerts", {"employee_id": 0})

    assert status == 403
    assert response == {"error": "caller is not authorised"}
    assert called == []


def test_similar_cases_uses_bounded_anchor_loader_when_available():
    class BoundedLoader:
        def __init__(self):
            self.called_with = None

        def load(self, **kwargs):
            self.called_with = kwargs
            return [case(1)], [case(2, 2)]

        def __call__(self, case_id):
            return case(case_id)

    loader = BoundedLoader()
    service = SilentMatchAPI(
        lambda employee_id: SimpleNamespace(employee_id=employee_id),
        lambda caller: context(), loader, Matcher(), Scanner(), Repo(),
    )
    status, response = service.handle(
        "POST", "/similar-cases", {"employee_id": 9, "case_master_id": 1}
    )

    assert status == 200
    assert loader.called_with == {"anchor_case_id": 1}
    assert response["matches"]


def test_linked_transition_requires_note():
    status, response = api().handle("POST", "/alerts/1/transition", {
        "employee_id": 9, "to_status": "Linked", "note": "",
    })
    assert status == 403
    assert "requires" in response["error"]


def test_reviewing_transition_uses_canonical_review_action():
    status, response = api().handle("POST", "/alerts/1/transition", {
        "employee_id": 9, "to_status": "Reviewing", "note": "",
    })
    assert status == 200
    assert response["alert"]["Status"] == "Reviewing"
    assert response["action"]["action"] == "review"


def test_terminal_alert_cannot_be_reopened():
    service = api()
    service.repository.alert["Status"] = "Linked"
    status, response = service.handle("POST", "/alerts/1/transition", {
        "employee_id": 9, "to_status": "Reviewing", "note": "",
    })
    assert status == 403
    assert response["error"] == "alert transition is not allowed"


def test_alert_inbox_returns_only_scope_checked_alerts():
    status, response = api().handle("GET", "/alerts", {"employee_id": 9})
    assert status == 200
    assert response["alerts"][0]["AlertID"] == 1


def test_alert_detail_returns_persisted_recipients_and_actions():
    status, response = api().handle("GET", "/alerts/1", {"employee_id": 9})
    assert status == 200
    assert response["recipients"] == [{"AlertID": 1, "EmployeeID": 9}]
    assert response["actions"] == [{"AlertID": 1, "ActionType": "Seen"}]


def test_scan_uses_live_capability():
    status, response = api().handle("POST", "/scan", {
        "employee_id": 9, "anchor_case_id": 1, "trigger_source": "live",
    })
    assert status == 200
    assert response["run_id"] == "run-1"


def test_index_route_requires_valid_version_and_runs_idempotent_job():
    class Job:
        def __init__(self):
            self.versions = []

        def run(self, version):
            self.versions.append(version)
            return ScanResult("index-1", "index", 0, 0, (), 0, 0)

    job = Job()
    service = api()
    service.index_job_factory = lambda payload: job
    status, response = service.handle("POST", "/index", {
        "employee_id": 9, "index_version": "mo-index-v2",
    })

    assert status == 200
    assert response["run_id"] == "index-1"
    assert job.versions == ["mo-index-v2"]


def test_index_route_rejects_malformed_version():
    service = api()
    service.index_job_factory = lambda payload: None
    status, response = service.handle("POST", "/index", {
        "employee_id": 9, "index_version": "bad version!",
    })
    assert status == 400
    assert "index version" in response["error"]


def test_graph_projection_route_requires_batch_capability_and_runs_job():
    class Job:
        def __init__(self):
            self.versions = []

        def run(self):
            self.versions.append("graph-v2")
            return {"projection_version": "graph-v2", "nodes_written": 1}

    job = Job()
    service = api()
    service.graph_projection_job_factory = lambda payload: job
    status, response = service.handle("POST", "/graph-projection", {
        "employee_id": 9, "projection_version": "graph-v2",
    })

    assert status == 200
    assert response["projection_version"] == "graph-v2"
    assert job.versions == ["graph-v2"]


def test_graph_projection_route_rejects_unsafe_version():
    service = api()
    service.graph_projection_job_factory = lambda payload: None
    status, response = service.handle("POST", "/graph-projection", {
        "employee_id": 9, "projection_version": "graph v2",
    })
    assert status == 400
    assert "projection version" in response["error"]


def test_catalyst_request_adapter_delegates_method_path_and_json():
    class Request:
        method = "POST"
        path = "/scan"

        def get_json(self, silent=True):
            return {"employee_id": 9, "anchor_case_id": 1, "trigger_source": "live"}

    body, status = handle_request(Request(), api())
    assert status == 200
    assert body["run_id"] == "run-1"


def test_scan_uses_request_access_context_factory():
    class ContextScanner(Scanner):
        pass
    seen = []
    service = api()
    service.scanner_factory = lambda context: seen.append(context) or ContextScanner()
    status, _ = service.handle("POST", "/scan", {
        "employee_id": 9, "anchor_case_id": 1, "trigger_source": "live",
    })
    assert status == 200
    assert seen
