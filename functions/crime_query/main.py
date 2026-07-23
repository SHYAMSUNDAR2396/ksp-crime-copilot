"""Catalyst Advanced I/O entrypoint.

Thin by design: pick the backend, resolve the caller, pivot the language,
shape the response. Everything else is tested library code.
"""
import datetime as dt
import os
import uuid

try:
    # Local/test context: main.py imported as functions.crime_query.main.
    from . import access, agent, audit_api, auth, catalog, conversation_api, intelligence_api, narrative_api, policy_audit, supervisor, supervisor_runtime, translate
    from .narrative import QuickMLRagProvider
    from .analytics import QuickMLAnalyticsProvider
    from .conversation import CatalystCacheConversationStore, ConversationStoreError, ConversationTurn
    from .conversation_export import SmartBrowzPdfRenderer
    from .evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
    from .db import ZcqlDB
    from .llm import QuickMLLLM
    from .rbac import MASK
    from .voice import validate_voice_request, voice_response
except ImportError:
    # Catalyst runtime context: main.py loaded standalone via
    # importlib.util.spec_from_file_location with no parent package,
    # dependencies vendored flat alongside it.
    import access, agent, audit_api, auth, catalog, conversation_api, intelligence_api, narrative_api, policy_audit, supervisor, supervisor_runtime, translate
    from narrative import QuickMLRagProvider
    from analytics import QuickMLAnalyticsProvider
    from conversation import CatalystCacheConversationStore, ConversationStoreError, ConversationTurn
    from conversation_export import SmartBrowzPdfRenderer
    from evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
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


def _evidence_payload(status, claims=(), rows=(), citations=(), limitations=(), confidence=0.0):
    merged = merge_bundles((_evidence_bundle(
        status, claims=claims, rows=rows, citations=citations,
        limitations=limitations, confidence=confidence,
    ),))
    return {
        "status": merged.status,
        "claims": list(merged.claims),
        "citations": list(merged.citations),
        "limitations": list(merged.limitations),
        "version": merged.index_or_model_version,
    }


def _evidence_bundle(status, claims=(), rows=(), citations=(), limitations=(), confidence=0.0):
    bundle = EvidenceBundle(
        agent_name="Structured Query Agent",
        status=status,
        claims=tuple(claims),
        rows_or_entities=tuple(rows),
        citations=tuple(citations),
        evidence_signals=("validated_sql", "rbac_scoped_rows"),
        confidence=confidence,
        limitations=tuple(limitations),
        index_or_model_version="sql-evidence-v1",
        elapsed_ms=0,
    )
    return filter_visible_bundle(bundle, lambda row: True)


def _verified_evidence(result):
    return _evidence_payload(
        "scope_denied" if result.refused else "ok",
        claims=() if result.refused else (result.text,),
        rows=result.rows,
        citations=result.citations,
        limitations=("No visible structured evidence was available.",) if result.refused else (),
        confidence=0.0 if result.refused else 1.0,
    )


def _http_status(result):
    if result.get("policy_code") == "SERVICE_UNAVAILABLE":
        return 503
    return 403 if result.get("refused") else 200


def _task_type(payload):
    task_type = payload.get("task_type")
    if isinstance(task_type, str) and task_type in supervisor.TASK_AGENT_ORDER:
        return task_type
    return "structured_query"


def handle_question(payload, db, llm, translator, today):
    """Pure core. No Catalyst types, no environment reads."""
    raw_question = payload.get("question")
    question = raw_question.strip() if isinstance(raw_question, str) else ""
    employee_id = payload.get("employee_id")

    if not question:
        return {"refused": True, "answer": "No question was provided.",
                "sql": "", "rows": [], "citations": [], "language": "en",
                "evidence": _evidence_payload("scope_denied", limitations=("A question is required.",))}

    caller = (
        db.caller_for(employee_id)
        if isinstance(employee_id, int) and not isinstance(employee_id, bool) and employee_id > 0
        else None
    )
    if caller is None:
        return {"refused": True, "answer": "You are not authorised to query this system.",
                "sql": "", "rows": [], "citations": [], "language": "en", "policy_code": "",
                "evidence": _evidence_payload("scope_denied", limitations=("Caller identity was not verified.",))}

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
            "evidence": _evidence_payload("scope_denied", limitations=("Capability denied by access policy.",)),
        }

    language = translate.detect(question)
    try:
        english_question = translate.to_english(question, translator)
    except translate.TranslationError:
        return {"refused": True,
                "answer": "Translation service is unavailable; please try again in English.",
                "sql": "", "rows": [], "citations": [], "language": "en", "policy_code": "",
                "evidence": _evidence_payload("scope_denied", limitations=("Input translation was unavailable.",))}

    execution_state = {}

    def structured_handler(_task, _payload):
        try:
            prepared = agent.prepare_query(english_question, caller, db, llm, today)
            execution_state["prepared"] = prepared
            return _evidence_bundle(
                "ok", rows=prepared.rows, citations=prepared.citations,
                confidence=1.0,
            )
        except agent.PreparationError as err:
            execution_state["answer"] = agent._refuse(
                db, caller, english_question, err.generated, str(err),
                dt.datetime.now(dt.timezone.utc),
            )
            return _evidence_bundle(
                "scope_denied", limitations=("Structured query evidence was unavailable.",)
            )

    def compose_handler(_merged, _payload):
        if "answer" not in execution_state:
            execution_state["answer"] = agent.compose_prepared(execution_state["prepared"])
        return execution_state["answer"]

    graph_result = supervisor_runtime.execute_task_graph(
        task,
        {"Structured Query Agent": structured_handler},
        payload={"question": english_question},
        composer=compose_handler,
        # SqliteDB is deliberately thread-bound for deterministic local
        # tests; the Catalyst ZCQL adapter uses bounded specialist fan-out.
        parallel=supervisor_runtime.parallel_for_backend(db),
    )
    result = graph_result.composition
    if not isinstance(result, agent.Answer):
        result = agent.Answer(
            text="I could not answer that safely. The query agent is temporarily unavailable.",
            refused=True,
            refusal_reason="Structured Query Agent unavailable",
        )

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
        "evidence": _verified_evidence(result),
    }


def handle_voice_question(payload, db, llm, translator, today, conversation_store):
    """Run a voice turn through the exact text query path and persist context."""
    request = validate_voice_request(payload)
    state = conversation_store.load(request.session_id, request.employee_id)
    contextual_transcript = request.transcript
    if state.turns:
        contextual_transcript = (
            "Previous verified question: {0}\nCurrent follow-up: {1}"
            .format(state.turns[-1].transcript, request.transcript)
        )
    result = handle_question(
        dict(payload, employee_id=request.employee_id, question=contextual_transcript,
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
            result.get("answer", ""),
        ),
        prior_task={"task_type": _task_type(payload)},
    )
    return voice_response(request, result, speak=not result.get("refused", False))


def handle_session_question(payload, db, llm, translator, today, conversation_store):
    """Persist typed turns through the same verified query path as voice."""
    if payload.get("employee_id") is None:
        result = handle_question(dict(payload, employee_id=None), db, llm, translator, today)
        return dict(result, turn_id=payload.get("turn_id"))
    raw_employee_id = payload["employee_id"]
    raw_turn_id = payload["turn_id"]
    if (
        isinstance(raw_employee_id, bool)
        or not isinstance(raw_employee_id, int)
        or raw_employee_id < 1
        or isinstance(raw_turn_id, bool)
        or not isinstance(raw_turn_id, int)
        or raw_turn_id < 0
        or not isinstance(payload["session_id"], str)
        or not payload["session_id"].strip()
    ):
        raise ValueError("session request fields are invalid")
    employee_id = raw_employee_id
    session_id = payload["session_id"]
    turn_id = raw_turn_id
    state = conversation_store.load(session_id, employee_id)
    question = payload.get("question", "")
    if state.turns:
        question = "Previous verified question: {0}\nCurrent follow-up: {1}".format(
            state.turns[-1].transcript, question,
        )
    result = handle_question(dict(payload, question=question), db, llm, translator, today)
    conversation_store.append(
        session_id, employee_id,
        ConversationTurn(turn_id, "text", payload.get("question", ""),
                         result.get("language", "en"),
                         tuple(result.get("citations", ())),
                         result.get("answer", "")),
        prior_task={"task_type": _task_type(payload)},
    )
    return dict(result, turn_id=turn_id)


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


def _smartbrowz_renderer(app):
    endpoint = os.environ.get("SMARTBROWZ_ENDPOINT", "").strip()
    if not endpoint:
        return None
    return SmartBrowzPdfRenderer(endpoint, _quickml_token(app))


def _narrative_retriever(app):
    endpoint = os.environ.get("QUICKML_RAG_ENDPOINT", "").strip()
    if not endpoint:
        return None
    return QuickMLRagProvider(
        endpoint=endpoint,
        token=_quickml_token(app),
        org_id=os.environ.get("QUICKML_ORG_ID"),
        model=os.environ.get("QUICKML_RAG_MODEL", "brief-facts-rag-v1"),
        timeout=float(os.environ.get("QUICKML_RAG_TIMEOUT", "10")),
        max_documents=int(os.environ.get("QUICKML_RAG_MAX_DOCUMENTS", "500")),
    )


def _analytics_provider(app):
    endpoint = os.environ.get("QUICKML_ANALYTICS_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        return QuickMLAnalyticsProvider(
            endpoint=endpoint,
            token=_quickml_token(app),
            org_id=os.environ.get("QUICKML_ORG_ID"),
            model=os.environ.get("QUICKML_ANALYTICS_MODEL", "crime-trend-v1"),
            timeout=float(os.environ.get("QUICKML_ANALYTICS_TIMEOUT", "10")),
        )
    except (AttributeError, TypeError, ValueError):
        # Preflight reports malformed deployment configuration; the request
        # path still has the deterministic geographic/temporal fallback.
        return None


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
        model=os.environ.get("QUICKML_MODEL", QuickMLLLM.MODEL),
    )

    translator = translate.QuickMLTranslator(llm)

    raw_payload = request.get_json(silent=True)
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    # Security Rules must require Catalyst authentication. The client-supplied
    # employee_id is intentionally discarded; only the authenticated
    # principal-to-Employee mapping can select an RBAC caller.
    payload["employee_id"] = auth.authenticated_employee_id_for_route(
        app, db.caller_for, request.method, request.path
    )
    if payload.get("operation") == "export":
        conversation_store = CatalystCacheConversationStore(app.cache())
        result = conversation_api.export_session(
            payload, db, conversation_store,
            renderer=_smartbrowz_renderer(app),
            today=dt.date.today(),
        )
        if result["code"] != "OK":
            status = 503 if result["code"] in {"EXPORT_UNAVAILABLE", "SERVICE_UNAVAILABLE"} else 403
            return make_response(jsonify(result), status)
        response = make_response(result["body"])
        response.headers["Content-Type"] = result["content_type"]
        suffix = "pdf" if result["content_type"] == "application/pdf" else "html"
        response.headers["Content-Disposition"] = "attachment; filename=ksp-conversation.{0}".format(suffix)
        return response
    if payload.get("operation") == "audit":
        result = audit_api.handle_operation(payload, db, dt.date.today())
        return make_response(jsonify(result), _http_status(result))
    if payload.get("operation") == "narrative":
        result = narrative_api.handle_operation(
            payload, db, retriever=_narrative_retriever(app), today=dt.date.today(),
        )
        return make_response(jsonify(result), _http_status(result))
    if payload.get("operation"):
        result = intelligence_api.handle_operation(
            payload, db, dt.date.today(), analytics_provider=_analytics_provider(app),
        )
        return make_response(jsonify(result), _http_status(result))
    if payload.get("session_id") is not None and payload.get("turn_id") is not None:
        conversation_store = CatalystCacheConversationStore(app.cache())
        if payload.get("employee_id") is None:
            result = handle_question(
                payload, db, llm, translator, dt.date.today(),
            )
        else:
            try:
                if payload.get("input_mode") == "voice":
                    result = handle_voice_question(
                        payload, db, llm, translator, dt.date.today(), conversation_store,
                    )
                else:
                    result = handle_session_question(
                        payload, db, llm, translator, dt.date.today(), conversation_store,
                    )
            except ValueError as exc:
                return make_response(jsonify({
                    "refused": True,
                    "answer": "The session request is invalid.",
                    "error": str(exc),
                    "citations": [],
                    "evidence": _evidence_payload(
                        "scope_denied", limitations=("The session request was malformed.",)
                    ),
                }), 400)
            except ConversationStoreError:
                return make_response(jsonify({
                    "refused": True,
                    "answer": "Conversation context is temporarily unavailable.",
                    "citations": [],
                    "evidence": _evidence_payload(
                        "scope_denied",
                        limitations=("Conversation cache was unavailable.",),
                    ),
                }), 503)
        return make_response(jsonify(result), 403 if result["refused"] else 200)
    result = handle_question(payload, db, llm, translator, dt.date.today())

    return make_response(jsonify(result), 403 if result["refused"] else 200)
