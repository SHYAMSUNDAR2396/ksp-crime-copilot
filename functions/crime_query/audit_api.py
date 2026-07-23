"""Authenticated, bounded audit viewer for command and district roles."""
import datetime as dt

try:
    from . import access, policy_audit
    from .db import DBError
    from .evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
except ImportError:  # pragma: no cover
    import access, policy_audit
    from db import DBError
    from evidence import EvidenceBundle, filter_visible_bundle, merge_bundles


AUDIT_PROJECTION = (
    "SELECT AuditLog.AuditID, AuditLog.EmployeeID, AuditLog.RankHierarchy, "
    "AuditLog.Question, AuditLog.GeneratedSQL, AuditLog.ExecutedSQL, "
    "AuditLog.CrimeNos, AuditLog.RowCount, AuditLog.LoggedAt "
    "FROM AuditLog ORDER BY AuditLog.AuditID DESC LIMIT 200"
)


def _number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _evidence(status, limitations=()):
    bundle = EvidenceBundle(
        agent_name="Audit Viewer",
        status=status,
        claims=(),
        rows_or_entities=(),
        citations=(),
        evidence_signals=("fixed_audit_projection", "rank_scoped_audit_rows"),
        confidence=1.0 if status == "ok" else 0.0,
        limitations=tuple(limitations),
        index_or_model_version="audit-v1",
        elapsed_ms=0,
    )
    visible = filter_visible_bundle(bundle, lambda row: True)
    merged = merge_bundles((visible,))
    return {
        "status": merged.status,
        "claims": list(merged.claims),
        "citations": list(merged.citations),
        "limitations": list(merged.limitations),
        "version": merged.index_or_model_version,
    }


def _refused(answer, code):
    return {
        "refused": True,
        "answer": answer,
        "data": {"rows": []},
        "citations": [],
        "policy_code": code,
        "evidence": _evidence("scope_denied", ("Audit visibility was denied by rank policy.",)),
    }


def _visible_rows(context, rows, db):
    # AuditLog intentionally has no FK to Employee, so the scope join is
    # performed through the trusted caller loader rather than a free-form
    # client filter or an undeclared Catalyst ZCQL relationship.
    visible = []
    for row in rows:
        employee_id = _number(row.get("EmployeeID"))
        if employee_id is None:
            continue
        if context.audit_visibility == "own_actions":
            allowed = employee_id == context.employee_id
        elif context.audit_visibility == "statewide_summary":
            allowed = True
        else:
            caller = db.caller_for(employee_id)
            allowed = bool(
                caller is not None
                and context.district_ids is not None
                and caller.district_id in context.district_ids
            )
        if not allowed:
            continue
        visible.append({
            "AuditID": _number(row.get("AuditID")),
            "EmployeeID": employee_id,
            "RankHierarchy": _number(row.get("RankHierarchy")),
            "Question": str(row.get("Question") or ""),
            "GeneratedSQL": str(row.get("GeneratedSQL") or ""),
            "ExecutedSQL": str(row.get("ExecutedSQL") or ""),
            "CrimeNos": str(row.get("CrimeNos") or ""),
            "RowCount": _number(row.get("RowCount")) or 0,
            "LoggedAt": str(row.get("LoggedAt") or ""),
        })
    return visible


def handle_operation(payload, db, today=None):
    """Return only audit rows allowed by the authenticated caller's bucket."""
    payload = payload or {}
    employee_id = payload.get("employee_id")
    try:
        caller = (
            db.caller_for(employee_id)
            if isinstance(employee_id, int) and not isinstance(employee_id, bool) and employee_id > 0
            else None
        )
    except DBError:
        return _refused("The audit service is temporarily unavailable.", "SERVICE_UNAVAILABLE")
    if caller is None:
        return _refused("You are not authorised to view the audit trail.", access.CAPABILITY_DENIED)
    context = access.resolve_access_context(caller, db)
    try:
        access.require_capability(context, "view_audit")
    except access.AccessPolicyError as exc:
        denial = policy_audit.record_policy_decision(
            context=context, capability="view_audit",
            task_id=str(payload.get("request_id") or ""),
            resource_type="audit", allowed=False, policy_code=exc.code,
            action="view_audit", outcome="refused",
        )
        policy_audit.persist_record(
            db, denial, dt.datetime.combine(today or dt.date.today(), dt.time(0, 0))
        )
        return _refused("Your rank does not permit audit viewing.", exc.code)

    try:
        rows = _visible_rows(context, db.execute_raw(AUDIT_PROJECTION), db)
    except DBError:
        return _refused(
            "The audit service is temporarily unavailable.",
            "SERVICE_UNAVAILABLE",
        )
    allowed = policy_audit.record_policy_decision(
        context=context, capability="view_audit",
        task_id=str(payload.get("request_id") or ""), resource_type="audit",
        allowed=True, action="view_audit", outcome="completed",
    )
    policy_audit.persist_record(
        db, allowed, dt.datetime.combine(today or dt.date.today(), dt.time(0, 0))
    )
    citations = tuple(
        value.strip()
        for row in rows
        for value in row["CrimeNos"].split(",")
        if value.strip()
    )
    return {
        "refused": False,
        "answer": "Audit trail ready.",
        "data": {"rows": rows, "visibility": context.audit_visibility},
        "citations": list(dict.fromkeys(citations)),
        "policy_code": "",
        "evidence": _evidence("ok"),
    }
