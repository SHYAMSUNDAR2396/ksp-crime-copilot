import json
import logging

from functions.crime_query.observability import emit_task_graph_metric
from functions.crime_query.supervisor import build_task_context
from functions.crime_query.supervisor_runtime import AgentRun, TaskGraphResult
from functions.crime_query.evidence import EvidenceBundle
from functions.crime_query.access import AccessContext


def _task():
    context = AccessContext(
        9, 3, "SP_COMMAND", (1,), (1,),
        frozenset({"query_structured_cases"}), "rbac_masked", frozenset(), "district",
    )
    return build_task_context("req-observe", "structured_query", context)


def _result():
    bundle = EvidenceBundle(
        "Structured Query Agent", "ok", (),
        ({"CrimeNo": "111111111111111111", "BriefFacts": "private"},),
        ("111111111111111111",), (), 1.0, (), "test-v1", 7,
    )
    return TaskGraphResult(
        "req-observe", bundle,
        (AgentRun("Structured Query Agent", "completed", 2, 7),),
        (), True, None,
    )


def test_task_graph_metric_excludes_case_data_and_keeps_operational_fields():
    records = []
    logger = logging.getLogger("test.ksp.observability")
    logger.handlers = []
    logger.addHandler(logging.Handler())
    logger.handlers[0].emit = records.append
    logger.setLevel(logging.INFO)

    assert emit_task_graph_metric(_task(), _result(), logger) is True

    payload = json.loads(records[0].getMessage())
    assert payload["event"] == "task_graph_metric"
    assert payload["task_type"] == "structured_query"
    assert payload["runs"][0]["attempts"] == 2
    assert payload["total_elapsed_ms"] == 7
    rendered = json.dumps(payload)
    assert "111111111111111111" not in rendered
    assert "private" not in rendered
