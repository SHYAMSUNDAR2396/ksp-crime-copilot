from functions.crime_query.access import AccessContext
from functions.crime_query.evidence import EvidenceBundle
from functions.crime_query.policy_audit import (
    POLICY_VERSION,
    persist_record,
    record_agent_selection,
    record_policy_decision,
)
from functions.crime_query.supervisor import build_task_context
from functions.crime_query import db as db_module


def _context(capabilities, audit_visibility="district"):
    return AccessContext(
        employee_id=97,
        rank_hierarchy=3,
        access_bucket="SP_COMMAND",
        unit_ids=(1, 2, 3),
        district_ids=(1,),
        capabilities=frozenset(capabilities),
        sensitive_data_policy="rbac_masked",
        alert_actions=frozenset(("review", "Linked", "Dismissed")),
        audit_visibility=audit_visibility,
    )


def test_denial_record_is_identifier_free_and_stable():
    record = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="view_graph",
        task_id="req-3",
        resource_type="graph",
        allowed=False,
        policy_code="CAPABILITY_DENIED",
        resource_identifier="CrimeNo 111111111111111111",
        outcome="refused",
    )

    assert record.result == "denied"
    assert record.resource_identifier == ""
    assert record.policy_version == POLICY_VERSION
    assert record.as_dict()["selected_agents"] == ()


def test_allowed_resource_identifier_is_sanitized_before_storage():
    safe = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="query_structured_cases",
        task_id="req-5",
        resource_type="structured_query",
        allowed=True,
        resource_identifier="unit:17",
        outcome="answered",
    )
    crime_no = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="query_structured_cases",
        task_id="req-6",
        resource_type="structured_query",
        allowed=True,
        resource_identifier="111111111111111111",
        outcome="answered",
    )
    name = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="query_structured_cases",
        task_id="req-7",
        resource_type="structured_query",
        allowed=True,
        resource_identifier="Ravi Kumar",
        outcome="answered",
    )

    assert safe.resource_identifier == "unit:17"
    assert crime_no.resource_identifier == ""
    assert name.resource_identifier == ""


def test_agent_selection_record_uses_stable_bundle_ids():
    context = _context(("query_structured_cases", "retrieve_narratives"))
    task = build_task_context(
        request_id="req-4",
        task_type="mixed",
        access_context=context,
    )
    bundles = (
        EvidenceBundle(
            agent_name="Structured Query Agent",
            status="ok",
            claims=(),
            rows_or_entities=((("CrimeNo", "111111111111111111"),),),
            citations=("111111111111111111",),
            evidence_signals=(),
            confidence=0.9,
            limitations=(),
            index_or_model_version="structured-v1",
            elapsed_ms=14,
            policy_version=POLICY_VERSION,
        ),
    )

    record = record_agent_selection(task, bundles, outcome="answered")

    assert record.selected_agents == task.selected_agents
    assert record.evidence_bundle_ids == ("Structured Query Agent:ok:structured-v1",)
    assert record.policy_version == POLICY_VERSION


class _AuditDB(object):
    def __init__(self, failure=None):
        self.rows = []
        self.failure = failure

    def append_audit(self, **fields):
        if self.failure is not None:
            raise self.failure
        self.rows.append(fields)


def test_persist_record_writes_only_schema_supported_safe_fields():
    now = "2026-07-22T11:30:00"
    record = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="view_graph",
        task_id="req-8",
        resource_type="graph",
        allowed=False,
        policy_code="CAPABILITY_DENIED",
        resource_identifier="CrimeNo 111111111111111111 Ravi Kumar",
        action="deny_task",
        selected_agents=("Structured Query Agent",),
        outcome="refused",
    )
    db = _AuditDB()

    persisted = persist_record(db, record, now)

    assert persisted is True
    assert db.rows == [
        {
            "EmployeeID": 97,
            "RankHierarchy": 3,
            "Question": "policy_audit:deny_task:graph:denied",
            "GeneratedSQL": "capability=view_graph policy=CAPABILITY_DENIED",
            "ExecutedSQL": "task=req-8 outcome=refused",
            "CrimeNos": "",
            "RowCount": 0,
            "LoggedAt": now,
        }
    ]


def test_persist_record_returns_false_on_dberror():
    record = record_policy_decision(
        context=_context(("query_structured_cases",)),
        capability="view_graph",
        task_id="req-9",
        resource_type="graph",
        allowed=False,
        policy_code="CAPABILITY_DENIED",
    )

    persisted = persist_record(
        _AuditDB(db_module.DBError("audit unavailable")),
        record,
        "2026-07-22T12:00:00",
    )

    assert persisted is False
