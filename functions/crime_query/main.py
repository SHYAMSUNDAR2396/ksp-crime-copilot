"""Catalyst Advanced I/O entrypoint.

Thin by design: pick the backend, resolve the caller, pivot the language,
shape the response. Everything else is tested library code.
"""
import datetime as dt
import os
import uuid

try:
    # Local/test context: main.py imported as functions.crime_query.main.
    from . import access, agent, catalog, policy_audit, supervisor, translate
    from .conversation import CatalystCacheConversationStore, ConversationTurn
    from .db import ZcqlDB
    from .llm import QuickMLLLM
    from .rbac import MASK
    from .voice import validate_voice_request, voice_response
except ImportError:
    # Catalyst runtime context: main.py loaded standalone via
    # importlib.util.spec_from_file_location with no parent package,
    # dependencies vendored flat alongside it.
    import access, agent, catalog, policy_audit, supervisor, translate
    from conversation import CatalystCacheConversationStore, ConversationTurn
    from db import ZcqlDB
    from llm import QuickMLLLM
    from rbac import MASK
    from voice import validate_voice_request, voice_response


def _identifying_values(rows):
    """String values of any IDENTIFYING_COLUMNS present in result rows, so
    names and narrative text can be protected through the Kannada round trip
    just like crime numbers. Skips redacted (MASK) and non-string values."""
    bare_names = {col.split(".", 1)[1] for col in catalog.IDENTIFYING_COLUMNS}
    values = []
    for row in rows:
        for key, value in row.items():
            if key in bare_names and isinstance(value, str) and value != MASK:
                values.append(value)
    return values


def _audit_now(today):
    return dt.datetime.combine(today, dt.time(0, 0))


def _task_type(payload):
    task_type = payload.get("task_type")
    if task_type in supervisor.TASK_AGENT_ORDER:
        return task_type
    return "structured_query"


def handle_question(payload, db, llm, translator, today):
    """Pure core. No Catalyst types, no environment reads."""
    question = (payload.get("question") or "").strip()
    employee_id = payload.get("employee_id")

    if not question:
        return {"refused": True, "answer": "No question was provided.",
                "sql": "", "rows": [], "citations": [], "language": "en"}

    caller = db.caller_for(employee_id) if employee_id is not None else None
    if caller is None:
        return {"refused": True, "answer": "You are not authorised to query this system.",
                "sql": "", "rows": [], "citations": [], "language": "en", "policy_code": ""}

    access_context = access.resolve_access_context(caller, db)
    task = supervisor.build_task_context(
        request_id=str(payload.get("request_id") or uuid.uuid4()),
        task_type=_task_type(payload),
        access_context=access_context,
    )
    policy_record = policy_audit.record_agent_selection(task, (), outcome="selected")
    policy_audit.persist_record(db, policy_record, _audit_now(today))
    if task.denials:
        denial_code, denied_capability = task.denials[0]
        denial_record = policy_audit.record_policy_decision(
            context=access_context,
            capability=denied_capability,
            task_id=task.request_id,
            resource_type=task.task_type,
            allowed=False,
            policy_code=denial_code,
            action="deny_task",
            selected_agents=policy_record.selected_agents,
            outcome="refused",
        )
        policy_audit.persist_record(db, denial_record, _audit_now(today))
        return {
            "refused": True,
            "answer": "I could not answer that safely. Your access level does not allow this request.",
            "sql": "",
            "rows": [],
            "citations": [],
            "language": "en",
            "policy_code": denial_record.policy_code,
        }

    language = translate.detect(question)
    try:
        english_question = translate.to_english(question, translator)
    except translate.TranslationError:
        return {"refused": True,
                "answer": "Translation service is unavailable; please try again in English.",
                "sql": "", "rows": [], "citations": [], "language": "en", "policy_code": ""}

    result = agent.answer(english_question, caller, db, llm, today)

    protected = list(result.citations) + _identifying_values(result.rows)
    rendered = translate.to_user_language(result.text, language, translator, protected)

    return {
        "refused": result.refused,
        "answer": rendered,
        "sql": "" if result.refused else result.sql,
        "rows": result.rows,
        "citations": result.citations,
        "filter_citation": result.filter_citation,
        "hallucinated": result.hallucinated_crimenos,
        "language": language,
        "policy_code": result.policy_code,
    }


def handle_voice_question(payload, db, llm, translator, today, conversation_store):
    """Run a voice turn through the exact text query path and persist context."""
    request = validate_voice_request(payload)
    result = handle_question(
        dict(payload, employee_id=request.employee_id, question=request.transcript,
             input_mode=request.input_mode, turn_id=request.turn_id,
             session_id=request.session_id),
        db, llm, translator, today,
    )
    conversation_store.append(
        request.session_id,
        request.employee_id,
        ConversationTurn(
            request.turn_id, request.input_mode, request.transcript,
            result.get("language", request.response_language),
            tuple(result.get("citations", ())),
        ),
        prior_task={"task_type": _task_type(payload)},
    )
    return voice_response(request, result, speak=not result.get("refused", False))


def _quickml_token(app):
    """A live OAuth access token from the function's own execution context.

    Catalyst's SDK refreshes this internally (see credentials.py); reusing
    it means QuickML calls never need a manually-managed, expiring secret.
    QUICKML_ORG_ID still comes from catalyst-config.json's env_variables --
    unlike the token, it isn't injected by the runtime (confirmed by
    deploying: os.environ has no X_ZOHO_CATALYST_ORG_ID here, even though
    the SDK's own HTTP client optionally reads that name internally).
    credential.token() returns a bare token string for most credential
    types, but (cred_type, token) for the runtime's CatalystCredential --
    normalise both.
    """
    token = app.credential.token()
    return token[1] if isinstance(token, tuple) else token


def handler(request):
    """Catalyst Advanced I/O Python entrypoint. Real signature confirmed by
    running `catalyst init` (Task 2): a Flask ``Request`` in, a Flask
    response out -- not the ``(context, basic_io)`` shape the plan guessed.
    """
    import zcatalyst_sdk
    from flask import jsonify, make_response

    app = zcatalyst_sdk.initialize()
    db = ZcqlDB(app)
    llm = QuickMLLLM(
        os.environ["QUICKML_ENDPOINT"],
        _quickml_token(app),
        os.environ["QUICKML_ORG_ID"],
    )

    translator = translate.QuickMLTranslator(llm)

    payload = request.get_json(silent=True) or {}
    if payload.get("input_mode") == "voice" and payload.get("session_id") is not None:
        conversation_store = CatalystCacheConversationStore(app.cache())
        result = handle_voice_question(
            payload, db, llm, translator, dt.date.today(), conversation_store,
        )
        return make_response(jsonify(result), 403 if result["refused"] else 200)
    result = handle_question(payload, db, llm, translator, dt.date.today())

    return make_response(jsonify(result), 403 if result["refused"] else 200)
