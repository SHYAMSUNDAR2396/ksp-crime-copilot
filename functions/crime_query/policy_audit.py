"""Stable, identifier-safe policy audit records."""

from dataclasses import dataclass, field
import re
from typing import Tuple

try:
    from . import access
    from .db import DBError
except ImportError:
    import access
    from db import DBError


POLICY_VERSION = "access-policy-v1"
CRIMENO_RE = re.compile(r"\b\d{18}\b")
SAFE_RESOURCE_IDENTIFIER_RE = re.compile(
    r"^(unit|district|employee|task|capability|scope|resource):[a-z0-9_.-]+$"
)
SAFE_TASK_ID_RE = re.compile(r"^(req-[a-z0-9_.-]+|[0-9a-f-]{36})$")


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


@dataclass(frozen=True)
class ScopeSafeResult:
    code: str
    rows: Tuple[dict, ...]
    limitations: Tuple[str, ...] = ()


def scope_safe_export(context, requested_session_id, owner_employee_id, rows):
    """Authorize an export before serializing any transcript/case content."""
    if not context.has("export_conversation"):
        return ScopeSafeResult("CAPABILITY_DENIED", (), ())
    if str(owner_employee_id) != str(context.employee_id):
        return ScopeSafeResult("SCOPE_DENIED", (), ())
    safe_rows = []
    for row in rows or ():
        safe = dict(row)
        # Cached content is untrusted: do not export raw audio or policy-only
        # metadata, and preserve only the already-cited answer contract.
        safe.pop("raw_audio", None)
        safe.pop("audio", None)
        safe_rows.append(safe)
    return ScopeSafeResult("OK", tuple(safe_rows))


def filter_audit_rows(context, rows):
    """Apply fixed audit visibility rules; callers cannot choose a scope."""
    visible = []
    for row in rows or ():
        if context.audit_visibility == "statewide_summary":
            visible.append(dict(row))
        elif context.audit_visibility == "district":
            if access.in_scope(row.get("DistrictID"), context.district_ids):
                visible.append(dict(row))
        elif access.same_identifier(row.get("EmployeeID"), context.employee_id):
            visible.append(dict(row))
    return tuple(visible)


def _stable_bundle_ids(bundles):
    return tuple(bundle.bundle_id for bundle in bundles)


def _sanitize_resource_identifier(resource_identifier):
    if not resource_identifier:
        return ""
    if CRIMENO_RE.search(resource_identifier):
        return ""
    if not SAFE_RESOURCE_IDENTIFIER_RE.fullmatch(resource_identifier):
        return ""
    return resource_identifier


def _sanitize_task_id(task_id):
    if SAFE_TASK_ID_RE.fullmatch(task_id):
        return task_id
    return ""


def _text(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


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
        resource_identifier=_sanitize_resource_identifier(resource_identifier)
        if allowed
        else "",
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


def persist_record(db, record, now):
    task_id = _sanitize_task_id(record.task_id)
    executed = ["outcome={0}".format(record.outcome or record.result)]
    if task_id:
        executed.insert(0, "task={0}".format(task_id))

    try:
        db.append_audit(
            EmployeeID=record.employee_id,
            RankHierarchy=record.rank_hierarchy,
            Question="policy_audit:{0}:{1}:{2}".format(
                record.action or "record",
                record.resource_type or "unknown",
                record.result,
            ),
            GeneratedSQL="capability={0} policy={1}".format(
                record.capability or "",
                record.policy_code or "",
            ).strip(),
            ExecutedSQL=" ".join(part for part in executed if part),
            CrimeNos="",
            RowCount=0 if record.result == "denied" else len(record.evidence_bundle_ids),
            LoggedAt=_text(now),
        )
    except DBError:
        return False
    return True
