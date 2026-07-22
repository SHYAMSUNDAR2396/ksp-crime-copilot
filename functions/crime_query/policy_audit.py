"""Stable, identifier-safe policy audit records."""

from dataclasses import dataclass, field
from typing import Tuple


POLICY_VERSION = "access-policy-v1"


@dataclass(frozen=True)
class PolicyAuditRecord:
    employee_id: int
    rank_hierarchy: int
    access_bucket: str
    capability: str
    task_id: str
    resource_type: str
    resource_identifier: str
    result: str
    policy_code: str
    action: str
    selected_agents: Tuple[str, ...] = field(default_factory=tuple)
    evidence_bundle_ids: Tuple[str, ...] = field(default_factory=tuple)
    outcome: str = ""
    policy_version: str = POLICY_VERSION

    def as_dict(self):
        return {
            "employee_id": self.employee_id,
            "rank_hierarchy": self.rank_hierarchy,
            "access_bucket": self.access_bucket,
            "capability": self.capability,
            "task_id": self.task_id,
            "resource_type": self.resource_type,
            "resource_identifier": self.resource_identifier,
            "result": self.result,
            "policy_code": self.policy_code,
            "action": self.action,
            "selected_agents": self.selected_agents,
            "evidence_bundle_ids": self.evidence_bundle_ids,
            "outcome": self.outcome,
            "policy_version": self.policy_version,
        }


def _stable_bundle_ids(bundles):
    return tuple(bundle.bundle_id for bundle in bundles)


def record_policy_decision(
    context,
    capability,
    task_id,
    resource_type,
    allowed,
    policy_code="",
    resource_identifier="",
    action="",
    selected_agents=(),
    evidence_bundle_ids=(),
    outcome="",
):
    return PolicyAuditRecord(
        employee_id=context.employee_id,
        rank_hierarchy=context.rank_hierarchy,
        access_bucket=context.access_bucket,
        capability=capability,
        task_id=task_id,
        resource_type=resource_type,
        resource_identifier=resource_identifier if allowed else "",
        result="allowed" if allowed else "denied",
        policy_code=policy_code,
        action=action,
        selected_agents=tuple(selected_agents),
        evidence_bundle_ids=tuple(evidence_bundle_ids),
        outcome=outcome,
    )


def record_agent_selection(task, bundles, outcome):
    capability = ""
    if task.required_agents:
        first = task.required_agents[0]
        capability = {
            "Structured Query Agent": "query_structured_cases",
            "Narrative Retrieval Agent": "retrieve_narratives",
            "Graph Agent": "view_graph",
            "Analytics Agent": "query_structured_cases",
            "Silent-Match Agent": "view_cross_jurisdiction_alerts",
        }.get(first, "")

    return PolicyAuditRecord(
        employee_id=task.access_context.employee_id,
        rank_hierarchy=task.access_context.rank_hierarchy,
        access_bucket=task.access_context.access_bucket,
        capability=capability,
        task_id=task.request_id,
        resource_type=task.task_type,
        resource_identifier="",
        result="allowed",
        policy_code="",
        action="select_agents",
        selected_agents=task.selected_agents,
        evidence_bundle_ids=_stable_bundle_ids(bundles),
        outcome=outcome,
    )
