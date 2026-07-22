import datetime as dt

from functions.crime_query.access import AccessContext
from functions.crime_query.supervisor import (
    AGENT_SPECS,
    build_task_context,
    select_agents,
)


def _context(capabilities):
    return AccessContext(
        employee_id=9,
        rank_hierarchy=6,
        access_bucket="CONSTABLE",
        unit_ids=(1,),
        district_ids=(1,),
        capabilities=frozenset(capabilities),
        sensitive_data_policy="rbac_masked",
        alert_actions=frozenset(),
        audit_visibility="own_actions",
    )


def test_supervisor_omits_agents_without_capability():
    context = _context(("query_structured_cases",))

    selected = select_agents("mixed", context)

    assert "Structured Query Agent" in selected
    assert "Graph Agent" not in selected
    assert "Composition Agent" in selected


def test_build_task_context_freezes_scope_and_selected_agents():
    context = _context(("query_structured_cases", "retrieve_narratives"))

    task = build_task_context(
        request_id="req-3",
        task_type="mixed",
        access_context=context,
        deadline=dt.datetime(2026, 7, 22, 12, 0, 0),
    )

    assert task.request_id == "req-3"
    assert task.resource_scope["unit_ids"] == (1,)
    assert task.resource_scope["district_ids"] == (1,)
    assert task.retry_budget == 1
    assert task.selected_agents == (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Composition Agent",
    )


def test_agent_specs_use_plan_capabilities():
    assert AGENT_SPECS["Structured Query Agent"].required_capabilities == (
        "query_structured_cases",
    )
    assert AGENT_SPECS["Narrative Retrieval Agent"].required_capabilities == (
        "retrieve_narratives",
    )
    assert AGENT_SPECS["Graph Agent"].required_capabilities == ("view_graph",)
