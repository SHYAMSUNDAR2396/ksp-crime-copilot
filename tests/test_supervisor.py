import datetime as dt

from functions.crime_query.access import AccessContext
from functions.crime_query.supervisor import (
    AGENT_SPECS,
    build_task_context,
    select_agents,
    task_deadline,
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


def test_graph_task_orders_structured_narrative_graph_then_composition():
    context = _context(
        ("query_structured_cases", "retrieve_narratives", "view_graph")
    )

    selected = select_agents("graph", context)

    assert selected == (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Composition Agent",
    )


def test_graph_task_exposes_parallel_specialists_before_composition():
    task = build_task_context(
        request_id="req-graph-groups",
        task_type="graph",
        access_context=_context(("query_structured_cases", "retrieve_narratives", "view_graph")),
    )

    assert task.execution_groups == (
        ("Structured Query Agent", "Narrative Retrieval Agent", "Graph Agent"),
        ("Composition Agent",),
    )


def test_mixed_task_orders_all_available_evidence_agents_before_composition():
    context = _context(
        ("query_structured_cases", "retrieve_narratives", "view_graph")
    )

    selected = select_agents("mixed", context)

    assert selected == (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Analytics Agent",
        "Composition Agent",
    )


def test_analytics_task_adds_optional_graph_evidence_for_command_roles():
    selected = select_agents(
        "analytics", _context(("query_structured_cases", "view_graph"))
    )

    assert selected == (
        "Structured Query Agent",
        "Analytics Agent",
        "Graph Agent",
        "Composition Agent",
    )


def test_silent_match_task_orders_structured_narrative_graph_silent_match_then_composition():
    context = _context(
        (
            "query_structured_cases",
            "retrieve_narratives",
            "view_graph",
            "view_cross_jurisdiction_alerts",
        )
    )

    selected = select_agents("silent_match", context)

    assert selected == (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Silent-Match Agent",
        "Composition Agent",
    )


def test_graph_task_keeps_optional_agents_but_denies_when_graph_capability_is_missing():
    context = _context(("query_structured_cases", "retrieve_narratives"))

    task = build_task_context(
        request_id="req-graph",
        task_type="graph",
        access_context=context,
    )

    assert task.selected_agents == (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Composition Agent",
    )
    assert task.denials == (("CAPABILITY_DENIED", "view_graph"),)
    assert task.execution_groups == (
        ("Structured Query Agent", "Narrative Retrieval Agent"),
        ("Composition Agent",),
    )


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
        "Analytics Agent",
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


def test_task_deadline_is_server_owned_and_uses_bounded_fallback():
    now = dt.datetime(2026, 7, 23, tzinfo=dt.timezone.utc)

    assert task_deadline({"KSP_TASK_DEADLINE_MS": "2500"}, now) == (
        now + dt.timedelta(milliseconds=2500)
    )
    assert task_deadline({"KSP_TASK_DEADLINE_MS": "not-a-number"}, now) == (
        now + dt.timedelta(milliseconds=8000)
    )
    assert task_deadline({"KSP_TASK_DEADLINE_MS": "999999"}, now) == (
        now + dt.timedelta(milliseconds=60000)
    )
