"""Capability-gated supervisor DTOs and specialist selection."""

import datetime as dt
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

try:
    from .access import CAPABILITY_DENIED
except ImportError:
    from access import CAPABILITY_DENIED


POLICY_VERSION = "access-policy-v1"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    required_capabilities: Tuple[str, ...]
    resource_types: Tuple[str, ...]
    supports_partial_results: bool
    timeout_ms: int
    retry_policy: str


@dataclass(frozen=True)
class TaskContext:
    request_id: str
    task_type: str
    access_context: object
    resource_scope: Mapping[str, Optional[Tuple[int, ...]]]
    selected_agents: Tuple[str, ...]
    execution_groups: Tuple[Tuple[str, ...], ...]
    deadline: Optional[dt.datetime]
    retry_budget: int
    required_agents: Tuple[str, ...]
    denials: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    policy_version: str = POLICY_VERSION


AGENT_SPECS = {
    "Structured Query Agent": AgentSpec(
        name="Structured Query Agent",
        required_capabilities=("query_structured_cases",),
        resource_types=("cases", "zcql"),
        supports_partial_results=False,
        timeout_ms=4000,
        retry_policy="single_repair",
    ),
    "Narrative Retrieval Agent": AgentSpec(
        name="Narrative Retrieval Agent",
        required_capabilities=("retrieve_narratives",),
        resource_types=("cases", "narratives"),
        supports_partial_results=True,
        timeout_ms=4000,
        retry_policy="single_retry",
    ),
    "Graph Agent": AgentSpec(
        name="Graph Agent",
        required_capabilities=("view_graph",),
        resource_types=("cases", "graph"),
        supports_partial_results=True,
        timeout_ms=4000,
        retry_policy="single_retry",
    ),
    "Analytics Agent": AgentSpec(
        name="Analytics Agent",
        required_capabilities=("query_structured_cases",),
        resource_types=("cases", "analytics"),
        supports_partial_results=True,
        timeout_ms=4000,
        retry_policy="single_retry",
    ),
    "Silent-Match Agent": AgentSpec(
        name="Silent-Match Agent",
        required_capabilities=("view_cross_jurisdiction_alerts",),
        resource_types=("alerts", "similar_cases"),
        supports_partial_results=False,
        timeout_ms=4000,
        retry_policy="single_retry",
    ),
    "Composition Agent": AgentSpec(
        name="Composition Agent",
        required_capabilities=(),
        resource_types=("answer",),
        supports_partial_results=True,
        timeout_ms=4000,
        retry_policy="none",
    ),
}

TASK_AGENT_ORDER = {
    "structured_query": ("Structured Query Agent", "Composition Agent"),
    "narrative_query": ("Narrative Retrieval Agent", "Composition Agent"),
    "analytics": ("Structured Query Agent", "Analytics Agent", "Composition Agent"),
    "graph": (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Composition Agent",
    ),
    "silent_match": (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Silent-Match Agent",
        "Composition Agent",
    ),
    "mixed": (
        "Structured Query Agent",
        "Narrative Retrieval Agent",
        "Graph Agent",
        "Analytics Agent",
        "Composition Agent",
    ),
}

REQUIRED_AGENTS = {
    "structured_query": ("Structured Query Agent",),
    "narrative_query": ("Narrative Retrieval Agent",),
    "analytics": ("Structured Query Agent",),
    "graph": ("Structured Query Agent", "Graph Agent"),
    "silent_match": ("Structured Query Agent", "Silent-Match Agent"),
    "mixed": ("Structured Query Agent",),
}


def _execution_groups(task_type, selected_agents):
    """Return parallel specialist groups followed by composition.

    Independent evidence producers share a group and may be dispatched by a
    Catalyst Function fan-out or Circuit. Composition is deliberately isolated
    in the final group so it can only receive verified merged evidence.
    """
    selected = set(selected_agents)
    specialists = tuple(
        name for name in _task_agents(task_type)
        if name != "Composition Agent" and name in selected
    )
    groups = []
    if specialists:
        groups.append(specialists)
    if "Composition Agent" in selected:
        groups.append(("Composition Agent",))
    return tuple(groups)


def _task_agents(task_type):
    return TASK_AGENT_ORDER.get(task_type, TASK_AGENT_ORDER["structured_query"])


def select_agents(task_type, access_context):
    selected = []
    for name in _task_agents(task_type):
        spec = AGENT_SPECS[name]
        if all(access_context.has(capability) for capability in spec.required_capabilities):
            selected.append(name)
    return tuple(selected)


def _task_denials(task_type, access_context, selected_agents):
    selected = set(selected_agents)
    denials = []
    for name in REQUIRED_AGENTS.get(task_type, ()):
        if name in selected:
            continue
        spec = AGENT_SPECS[name]
        for capability in spec.required_capabilities:
            if not access_context.has(capability):
                denials.append((CAPABILITY_DENIED, capability))
    return tuple(denials)


def build_task_context(
    request_id,
    task_type,
    access_context,
    deadline=None,
    retry_budget=1,
):
    selected = select_agents(task_type, access_context)
    scope = MappingProxyType(
        {
            "unit_ids": access_context.unit_ids,
            "district_ids": access_context.district_ids,
        }
    )
    return TaskContext(
        request_id=request_id,
        task_type=task_type,
        access_context=access_context,
        resource_scope=scope,
        selected_agents=selected,
        execution_groups=_execution_groups(task_type, selected),
        deadline=deadline,
        retry_budget=retry_budget,
        required_agents=REQUIRED_AGENTS.get(task_type, ("Structured Query Agent",)),
        denials=_task_denials(task_type, access_context, selected),
    )
