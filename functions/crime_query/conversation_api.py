"""Authenticated conversation export boundary."""
import datetime as dt

try:
    from . import access, policy_audit
    from .conversation_export import export_conversation
    from .conversation import ConversationStoreError
    from .db import DBError
except ImportError:  # pragma: no cover
    import access, policy_audit
    from conversation_export import export_conversation
    from conversation import ConversationStoreError
    from db import DBError


def _audit(db, context, allowed, code, request_id, now):
    record = policy_audit.record_policy_decision(
        context=context,
        capability="export_conversation",
        task_id=request_id,
        resource_type="conversation",
        allowed=allowed,
        policy_code="" if allowed else code,
        action="export_conversation",
        outcome="completed" if allowed else "refused",
    )
    policy_audit.persist_record(db, record, now)


def export_session(payload, db, conversation_store, renderer=None, today=None):
    payload = payload or {}
    try:
        employee_id = int(payload["employee_id"])
        session_id = str(payload["session_id"])
    except (KeyError, TypeError, ValueError):
        return {"code": "SCOPE_DENIED", "content_type": "text/plain", "body": ""}
    if not session_id:
        return {"code": "SCOPE_DENIED", "content_type": "text/plain", "body": ""}

    try:
        caller = db.caller_for(employee_id)
    except DBError:
        return {"code": "SERVICE_UNAVAILABLE", "content_type": "text/plain", "body": ""}
    if caller is None:
        return {"code": "CAPABILITY_DENIED", "content_type": "text/plain", "body": ""}
    context = access.resolve_access_context(caller, db)
    try:
        state = conversation_store.load(session_id, employee_id)
    except ConversationStoreError:
        return {"code": "SERVICE_UNAVAILABLE", "content_type": "text/plain", "body": ""}
    rows = [
        {
            "question": turn.transcript,
            "answer": turn.answer,
            "citations": turn.citations,
        }
        for turn in state.turns
    ]
    result = export_conversation(context, session_id, employee_id, rows, renderer)
    now = dt.datetime.combine(today or dt.date.today(), dt.time(0, 0))
    _audit(db, context, result["code"] == "OK", result["code"],
           str(payload.get("request_id") or ""), now)
    return result
