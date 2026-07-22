"""Rank-derived capability access policy for supervisor-facing actions."""

from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple


CAPABILITY_DENIED = "CAPABILITY_DENIED"
SCOPE_DENIED = "SCOPE_DENIED"
ACTION_DENIED = "ACTION_DENIED"
SENSITIVE_FIELD_DENIED = "SENSITIVE_FIELD_DENIED"

BUCKET_DGP_STATEWIDE = "DGP_STATEWIDE"
BUCKET_SP_COMMAND = "SP_COMMAND"
BUCKET_INSPECTOR = "INSPECTOR"
BUCKET_SI_IO = "SI_IO"
BUCKET_CONSTABLE = "CONSTABLE"


class AccessPolicyError(Exception):
    """Raised when an access policy decision denies the requested action."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AccessContext:
    employee_id: int
    rank_hierarchy: int
    access_bucket: str
    unit_ids: Optional[Tuple[int, ...]]
    district_ids: Optional[Tuple[int, ...]]
    capabilities: FrozenSet[str]
    sensitive_data_policy: str
    alert_actions: FrozenSet[str]
    audit_visibility: str

    def has(self, capability):
        return capability in self.capabilities


def bucket_for_rank(rank_hierarchy):
    if rank_hierarchy <= 2:
        return BUCKET_DGP_STATEWIDE
    if rank_hierarchy == 3:
        return BUCKET_SP_COMMAND
    if rank_hierarchy == 4:
        return BUCKET_INSPECTOR
    if rank_hierarchy == 5:
        return BUCKET_SI_IO
    return BUCKET_CONSTABLE


def _immutable_scope(ids):
    if ids is None:
        return None
    return tuple(sorted(set(ids)))


def _capabilities_for_bucket(bucket):
    shared_reads = {
        "query_structured_cases",
        "retrieve_narratives",
        "retrieve_similar_cases",
        "export_conversation",
    }

    if bucket == BUCKET_DGP_STATEWIDE:
        return frozenset(
            shared_reads
            | {
                "view_graph",
                "view_cross_jurisdiction_alerts",
                "review_alerts",
                "dispose_alerts",
                "run_batch_scan",
                "run_live_scan",
                "view_deadline_risk",
                "view_audit",
            }
        )
    if bucket == BUCKET_SP_COMMAND:
        return frozenset(
            shared_reads
            | {
                "view_graph",
                "view_cross_jurisdiction_alerts",
                "review_alerts",
                "dispose_alerts",
                "run_batch_scan",
                "run_live_scan",
                "view_deadline_risk",
                "view_audit",
            }
        )
    if bucket == BUCKET_INSPECTOR:
        return frozenset(
            shared_reads
            | {
                "view_graph",
                "view_cross_jurisdiction_alerts",
                "review_alerts",
                "dispose_alerts",
                "run_live_scan",
                "view_deadline_risk",
                "view_audit",
            }
        )
    if bucket == BUCKET_SI_IO:
        return frozenset(
            shared_reads
            | {
                "view_graph",
                "view_cross_jurisdiction_alerts",
                "review_alerts",
                "dispose_alerts",
                "run_live_scan",
                "view_deadline_risk",
            }
        )
    return frozenset(shared_reads)


def _alert_actions_for_bucket(bucket):
    if bucket == BUCKET_CONSTABLE:
        return frozenset()
    return frozenset({"review", "Linked", "Dismissed"})


def _audit_visibility_for_bucket(bucket):
    if bucket in (BUCKET_DGP_STATEWIDE,):
        return "statewide_summary"
    if bucket in (BUCKET_SP_COMMAND, BUCKET_INSPECTOR):
        return "district"
    return "own_actions"


def resolve_access_context(caller, db):
    bucket = bucket_for_rank(caller.rank_hierarchy)
    if bucket == BUCKET_DGP_STATEWIDE:
        unit_ids = None
        district_ids = None
    elif bucket == BUCKET_CONSTABLE:
        unit_ids = _immutable_scope([caller.unit_id])
        district_ids = _immutable_scope([caller.district_id])
    else:
        unit_ids = _immutable_scope(db.units_in_district(caller.district_id))
        district_ids = _immutable_scope([caller.district_id])

    return AccessContext(
        employee_id=caller.employee_id,
        rank_hierarchy=caller.rank_hierarchy,
        access_bucket=bucket,
        unit_ids=unit_ids,
        district_ids=district_ids,
        capabilities=_capabilities_for_bucket(bucket),
        sensitive_data_policy="rbac_masked",
        alert_actions=_alert_actions_for_bucket(bucket),
        audit_visibility=_audit_visibility_for_bucket(bucket),
    )


def require_capability(context, capability):
    if not context.has(capability):
        raise AccessPolicyError(
            CAPABILITY_DENIED,
            "Capability '{0}' is not allowed for {1}".format(
                capability, context.access_bucket
            ),
        )


def _in_scope(value, scope_ids):
    if value is None:
        return False
    if scope_ids is None:
        return True
    return value in scope_ids


def can_read_case(context, case_row, capability="query_structured_cases"):
    require_capability(context, capability)
    station_id = case_row.get("PoliceStationID")
    district_id = case_row.get("DistrictID")
    if station_id is None or district_id is None:
        return False
    return _in_scope(station_id, context.unit_ids) and _in_scope(
        district_id, context.district_ids
    )


def can_read_case_pair(context, left_case, right_case, capability="query_structured_cases"):
    return (can_read_case(context, left_case, capability)
            and can_read_case(context, right_case, capability))


def _non_empty_note(alert):
    note = alert.get("note")
    return isinstance(note, str) and bool(note.strip())


def _visible_alert_cases(alert):
    return alert.get("anchor_case"), alert.get("matched_case")


def _assigned_employee_id(case_row):
    for field in ("PolicePersonID", "assigned_employee_id", "IOID"):
        employee_id = case_row.get(field)
        if employee_id is not None:
            return employee_id
    return None


def _assigned_to_caller(case_row, employee_id):
    return _assigned_employee_id(case_row) == employee_id


def can_act_on_alert(context, alert, action):
    if action == "review":
        capability = "review_alerts"
    elif action in ("Linked", "Dismissed"):
        capability = "dispose_alerts"
    else:
        raise AccessPolicyError(
            ACTION_DENIED, "Alert action '{0}' is not supported".format(action)
        )

    require_capability(context, capability)

    if action not in context.alert_actions:
        raise AccessPolicyError(
            ACTION_DENIED,
            "Alert action '{0}' is not allowed for {1}".format(
                action, context.access_bucket
            ),
        )

    anchor_case, matched_case = _visible_alert_cases(alert)
    if anchor_case is None or matched_case is None:
        raise AccessPolicyError(
            SCOPE_DENIED, "Alert cases are outside the caller's scope"
        )

    if not can_read_case_pair(context, anchor_case, matched_case):
        raise AccessPolicyError(
            SCOPE_DENIED, "Alert cases are outside the caller's scope"
        )

    if (
        context.access_bucket == BUCKET_SI_IO
        and action in ("Linked", "Dismissed")
        and not (
            _assigned_to_caller(anchor_case, context.employee_id)
            and _assigned_to_caller(matched_case, context.employee_id)
        )
    ):
        raise AccessPolicyError(
            ACTION_DENIED,
            "Alert disposition requires the caller to be assigned to both cases",
        )

    if action in ("Linked", "Dismissed") and not _non_empty_note(alert):
        raise AccessPolicyError(
            ACTION_DENIED,
            "Alert disposition '{0}' requires a non-empty note".format(action),
        )

    return True
