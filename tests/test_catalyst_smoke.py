from dataclasses import replace

from tools.catalyst_smoke import SmokeConfig, config_from_env, run_smoke


class Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class BinaryResponse:
    status_code = 200
    headers = {"Content-Type": "application/pdf"}
    content = b"%PDF-1.7 smoke"


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def config():
    return SmokeConfig(
        crime_query_url="https://crime.example/function",
        silent_match_url="https://silent.example/function",
        token="secret-token",
        case_id=1,
    )


def test_smoke_checks_query_similar_cases_and_alert_contracts():
    client = Client([
        Response(200, {"refused": False, "answer": "ok", "citations": [], "evidence": {}}),
        Response(200, {"case_master_id": 1, "matches": [], "partial": True}),
        Response(200, {"alerts": [], "partial": False}),
    ])

    report = run_smoke(client, config())

    assert report["ok"] is True
    assert [step["name"] for step in report["steps"]] == [
        "crime_query", "similar_cases", "alerts",
    ]
    assert all(step["status"] == 200 for step in report["steps"])
    assert client.calls[0][2]["headers"]["Authorization"] == "Zoho-oauthtoken secret-token"
    assert "employee_id" not in client.calls[0][2]["json"]


def test_smoke_rejects_contract_failure_without_echoing_response_body():
    client = Client([Response(500, {"CrimeNo": "111111111111111111", "secret": "token"})])

    report = run_smoke(client, config())

    assert report["ok"] is False
    assert report["steps"][0]["status"] == 500
    serialized = repr(report)
    assert "111111111111111111" not in serialized
    assert "secret" not in serialized
    assert "token" not in serialized


def test_smoke_scan_is_explicit_and_uses_batch_contract():
    client = Client([
        Response(200, {"refused": False, "answer": "ok", "citations": [], "evidence": {}}),
        Response(200, {"case_master_id": 1, "matches": [], "partial": True}),
        Response(200, {"alerts": [], "partial": False}),
        Response(200, {"run_id": "run-1", "alerts": [], "failures": []}),
    ])

    report = run_smoke(
        client,
        replace(config(), include_scan=True, scan_date_window=("2026-06-01", "2026-06-30")),
    )

    assert report["ok"] is True
    assert report["steps"][-1]["name"] == "batch_scan"
    assert client.calls[-1][0:2] == ("POST", "https://silent.example/function/scan")
    assert client.calls[-1][2]["json"] == {
        "date_window": ["2026-06-01", "2026-06-30"],
        "trigger_source": "batch",
    }


def test_config_from_env_reports_missing_names_without_values():
    config, missing = config_from_env({"CATALYST_TOKEN": "do-not-print"})

    assert config is None
    assert "KSP_CRIME_QUERY_URL" in missing
    assert "CATALYST_TOKEN" not in repr(missing)


def test_smoke_graph_projection_is_explicit_and_versioned():
    client = Client([
        Response(200, {"refused": False, "answer": "ok", "citations": [], "evidence": {}}),
        Response(200, {"case_master_id": 1, "matches": [], "partial": True}),
        Response(200, {"alerts": [], "partial": False}),
        Response(200, {
            "projection_version": "graph-smoke-v1", "nodes_written": 1,
            "members_written": 1, "edges_written": 1,
        }),
    ])

    report = run_smoke(client, replace(config(), include_projection=True))

    assert report["ok"] is True
    assert report["steps"][-1]["name"] == "graph_projection"
    assert client.calls[-1][2]["json"] == {
        "projection_version": "graph-smoke-v1",
    }


def test_smoke_views_cover_voice_narrative_intelligence_and_audit_contracts():
    responses = [
        Response(200, {"refused": False, "answer": "ok", "citations": [], "evidence": {}}),
        Response(200, {"case_master_id": 1, "matches": [], "partial": True}),
        Response(200, {"alerts": [], "partial": False}),
    ]
    responses.extend(
        Response(200, {
            "turn_id": 1, "voice": {}, "citations": [], "refused": False,
            "data": {}, "evidence": {},
        })
        for _ in range(7)
    )
    client = Client(responses)

    report = run_smoke(client, replace(config(), include_views=True))

    assert report["ok"] is True
    assert [step["name"] for step in report["steps"]] == [
        "crime_query", "similar_cases", "alerts", "voice_query", "narrative",
        "network", "analytics", "profile", "demographics", "audit",
    ]


def test_smoke_export_requires_pdf_response():
    client = Client([
        Response(200, {"refused": False, "answer": "ok", "citations": [], "evidence": {}}),
        Response(200, {"case_master_id": 1, "matches": [], "partial": True}),
        Response(200, {"alerts": [], "partial": False}),
        BinaryResponse(),
    ])

    report = run_smoke(client, replace(config(), include_export=True))

    assert report["ok"] is True
    assert report["steps"][-1]["name"] == "conversation_export"
