from functions.crime_query.access import AccessContext
from functions.crime_query.evidence import EvidenceBundle
from functions.crime_query.policy_audit import (
    POLICY_VERSION,
    record_agent_selection,
    record_policy_decision,
)
from functions.crime_query.supervisor import build_task_context


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
            model_or_index_version="structured-v1",
            policy_version=POLICY_VERSION,
        ),
    )

    record = record_agent_selection(task, bundles, outcome="answered")

    assert record.selected_agents == task.selected_agents
    assert record.evidence_bundle_ids == ("Structured Query Agent:ok:structured-v1",)
    assert record.policy_version == POLICY_VERSION
