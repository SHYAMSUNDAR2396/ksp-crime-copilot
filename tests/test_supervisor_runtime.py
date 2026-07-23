import datetime as dt
import time

from functions.crime_query.evidence import EvidenceBundle
from functions.crime_query.supervisor import build_task_context
from functions.crime_query.supervisor_runtime import execute_task_graph
from functions.crime_query.access import AccessContext


def _context(capabilities):
    return AccessContext(
        employee_id=9,
        rank_hierarchy=3,
        access_bucket="SP_COMMAND",
        unit_ids=(1,),
        district_ids=(1,),
        capabilities=frozenset(capabilities),
        sensitive_data_policy="rbac_masked",
        alert_actions=frozenset({"review"}),
        audit_visibility="district",
    )


def _bundle(name, crime_no, claim):
    return EvidenceBundle(
        agent_name=name,
        status="ok",
        claims=(claim,),
        rows_or_entities=({"CrimeNo": crime_no},),
        citations=(crime_no,),
        evidence_signals=(name.lower(),),
        confidence=1.0,
        limitations=(),
        index_or_model_version="test-v1",
        elapsed_ms=1,
    )


def test_task_graph_fans_out_specialists_and_composes_only_after_merge():
    task = build_task_context(
        "request-1", "mixed", _context(("query_structured_cases", "retrieve_narratives"))
    )
    events = []

    def structured(_task, _payload):
        events.append("structured")
        return _bundle("Structured Query Agent", "111111111111111111", "structured claim")

    def narrative(_task, _payload):
        events.append("narrative")
        return _bundle("Narrative Retrieval Agent", "222222222222222222", "narrative claim")

    def compose(merged, _payload):
        assert merged.status == "ok"
        assert merged.citations == ("111111111111111111", "222222222222222222")
        events.append("compose")
        return "verified answer"

    result = execute_task_graph(
        task,
        {
            "Structured Query Agent": structured,
            "Narrative Retrieval Agent": narrative,
        },
        payload={"question": "test"},
        composer=compose,
    )

    assert set(events[:2]) == {"structured", "narrative"}
    assert events[-1] == "compose"
    assert result.complete is True
    assert result.composition == "verified answer"
    assert result.merged_evidence.citations == (
        "111111111111111111", "222222222222222222"
    )


def test_task_graph_retries_transient_agent_failure_without_leaking_error():
    task = build_task_context("request-2", "structured_query", _context(("query_structured_cases",)))
    calls = []

    def flaky(_task, _payload):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider token must never be returned")
        return _bundle("Structured Query Agent", "111111111111111111", "ok")

    result = execute_task_graph(task, {"Structured Query Agent": flaky})

    assert len(calls) == 2
    assert result.complete is True
    assert result.failed_agents == ()
    assert [run.attempts for run in result.runs if run.agent_name == "Structured Query Agent"] == [2]


def test_task_graph_marks_required_timeout_as_partial_and_redacts_failure():
    task = build_task_context("request-3", "structured_query", _context(("query_structured_cases",)))

    def slow(_task, _payload):
        time.sleep(0.08)
        return _bundle("Structured Query Agent", "111111111111111111", "late")

    result = execute_task_graph(
        task,
        {"Structured Query Agent": slow},
        timeout_override_ms=10,
    )

    assert result.complete is False
    assert result.failed_agents == ("Structured Query Agent",)
    assert result.merged_evidence.rows_or_entities == ()
    assert "provider token" not in " ".join(result.merged_evidence.limitations)
    assert result.runs[0].error_code == "AGENT_TIMEOUT"


def test_task_graph_rejects_wrong_bundle_owner():
    task = build_task_context("request-4", "structured_query", _context(("query_structured_cases",)))

    def wrong_owner(_task, _payload):
        return _bundle("Narrative Retrieval Agent", "111111111111111111", "wrong")

    result = execute_task_graph(task, {"Structured Query Agent": wrong_owner})

    assert result.complete is False
    assert result.failed_agents == ("Structured Query Agent",)
    assert result.runs[0].error_code == "AGENT_CONTRACT_INVALID"


def test_task_graph_honors_expired_total_deadline_before_dispatch():
    task = build_task_context(
        "request-5", "structured_query", _context(("query_structured_cases",)),
        deadline=dt.datetime.now() - dt.timedelta(seconds=1),
    )
    called = []

    def handler(_task, _payload):
        called.append(True)
        return _bundle("Structured Query Agent", "111111111111111111", "late")

    result = execute_task_graph(task, {"Structured Query Agent": handler})

    assert called == []
    assert result.complete is False
    assert result.runs[0].error_code == "AGENT_TIMEOUT"


def test_composition_timeout_is_reported_and_does_not_claim_completion():
    task = build_task_context("request-6", "structured_query", _context(("query_structured_cases",)))

    def slow_composer(_merged, _payload):
        time.sleep(0.08)
        return "late answer"

    result = execute_task_graph(
        task,
        {"Structured Query Agent": lambda *_args: _bundle(
            "Structured Query Agent", "111111111111111111", "ok",
        )},
        composer=slow_composer,
        timeout_override_ms=10,
        parallel=False,
    )

    assert result.complete is False
    assert result.composition is None
    assert "Composition Agent" in result.failed_agents
    composition_run = next(run for run in result.runs if run.agent_name == "Composition Agent")
    assert composition_run.error_code == "AGENT_TIMEOUT"
