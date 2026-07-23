"""Authenticated Narrative Retrieval Agent request boundary."""
import datetime as dt
from dataclasses import asdict, is_dataclass

try:
    from . import access, intelligence_api, policy_audit, supervisor, supervisor_runtime
    from .db import DBError
    from .evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
    from .narrative import DeterministicNarrativeRetriever, NarrativeRetrievalError
except ImportError:  # pragma: no cover
    import access, intelligence_api, policy_audit, supervisor, supervisor_runtime
    from db import DBError
    from evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
    from narrative import DeterministicNarrativeRetriever, NarrativeRetrievalError


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _evidence(hits, limitations=()):
    rows = tuple({"CrimeNo": hit.crime_no, "BriefFacts": hit.excerpt} for hit in hits)
    citations = tuple(hit.crime_no for hit in hits)
    bundle = EvidenceBundle(
        agent_name="Narrative Retrieval Agent",
        status="ok" if hits else "empty",
        claims=tuple("Original narrative excerpt retrieved for {0}.".format(hit.crime_no)
                     for hit in hits),
        rows_or_entities=rows,
        citations=citations,
        evidence_signals=("brief_facts_retrieval",),
        confidence=max((hit.score for hit in hits), default=0.0),
        limitations=tuple(limitations),
        index_or_model_version=tuple(sorted({hit.index_version for hit in hits})),
        elapsed_ms=0,
    )
    return _jsonable(merge_bundles((filter_visible_bundle(bundle, lambda row: True),)))


def _evidence_bundle(hits, limitations=()):
    rows = tuple({"CrimeNo": hit.crime_no, "BriefFacts": hit.excerpt} for hit in hits)
    bundle = EvidenceBundle(
        agent_name="Narrative Retrieval Agent",
        status="ok" if hits else "empty",
        claims=tuple(
            "Original narrative excerpt retrieved for {0}.".format(hit.crime_no)
            for hit in hits
        ),
        rows_or_entities=rows,
        citations=tuple(hit.crime_no for hit in hits),
        evidence_signals=("brief_facts_retrieval",),
        confidence=max((hit.score for hit in hits), default=0.0),
        limitations=tuple(limitations),
        index_or_model_version=tuple(sorted({hit.index_version for hit in hits})),
        elapsed_ms=0,
    )
    return filter_visible_bundle(bundle, lambda row: True)


def _refused(answer, code, limitation):
    return {
        "refused": True, "answer": answer, "data": {"matches": []},
        "citations": [], "policy_code": code,
        "evidence": {
            "status": "scope_denied", "claims": [], "citations": [],
            "limitations": [limitation], "version": "narrative-v1",
        },
    }


def handle_operation(payload, db, retriever=None, today=None):
    payload = payload or {}
    employee_id = payload.get("employee_id")
    try:
        caller = (
            db.caller_for(employee_id)
            if isinstance(employee_id, int) and not isinstance(employee_id, bool) and employee_id > 0
            else None
        )
    except DBError:
        return _refused(
            "Narrative retrieval is temporarily unavailable.",
            "SERVICE_UNAVAILABLE",
            "The caller scope could not be resolved.",
        )
    if caller is None:
        return _refused("You are not authorised to retrieve narratives.",
                        access.CAPABILITY_DENIED, "Caller identity was not verified.")
    context = access.resolve_access_context(caller, db)
    task = supervisor.build_task_context(
        request_id=str(payload.get("request_id") or "narrative"),
        task_type="narrative_query", access_context=context,
    )
    selection = policy_audit.record_agent_selection(task, (), outcome="selected")
    now = dt.datetime.combine(today or dt.date.today(), dt.time(0, 0))
    policy_audit.persist_record(db, selection, now)
    if task.denials:
        code, capability = task.denials[0]
        denial = policy_audit.record_policy_decision(
            context, capability, task.request_id, task.task_type, False,
            policy_code=code, action="deny_task", selected_agents=selection.selected_agents,
            outcome="refused",
        )
        policy_audit.persist_record(db, denial, now)
        return _refused("Your rank does not permit narrative retrieval.", code,
                        "Narrative retrieval capability was denied.")

    question = str(payload.get("question") or "").strip()
    if not question:
        return _refused("A narrative question is required.", access.SCOPE_DENIED,
                        "A narrative question was not provided.")
    try:
        cases = intelligence_api._scope_rows(context, intelligence_api._case_rows(db))
        service = retriever or DeterministicNarrativeRetriever()
        hits = service.search(question, cases, context,
                              limit=min(max(int(payload.get("limit", 5)), 1), 10))
    except (TypeError, ValueError, NarrativeRetrievalError, access.AccessPolicyError) as exc:
        return _refused("Narrative retrieval was unavailable.", access.SCOPE_DENIED, str(exc))
    except DBError:
        return _refused(
            "Narrative retrieval is temporarily unavailable.",
            "SERVICE_UNAVAILABLE",
            "The scoped Data Store read could not be completed.",
        )
    data = {
        "matches": _jsonable(hits),
        "partial": isinstance(service, DeterministicNarrativeRetriever),
    }
    limitations = (
        ("Deterministic local retrieval fallback is active.",)
        if isinstance(service, DeterministicNarrativeRetriever) else ()
    )
    graph_result = supervisor_runtime.execute_task_graph(
        task,
        {"Narrative Retrieval Agent": lambda _task, _payload: _evidence_bundle(hits, limitations)},
        payload={"question": question},
        composer=lambda _merged, _payload: data,
        parallel=supervisor_runtime.parallel_for_backend(db),
    )
    if not graph_result.complete:
        return _refused(
            "Narrative retrieval was unavailable.",
            "SERVICE_UNAVAILABLE",
            graph_result.merged_evidence.limitations,
        )
    merged = graph_result.merged_evidence
    evidence = {
        "status": merged.status,
        "claims": list(merged.claims),
        "citations": list(merged.citations),
        "limitations": list(merged.limitations),
        "version": merged.index_or_model_version,
    }
    return {
        "refused": False,
        "answer": "Original narrative excerpts retrieved.",
        "data": data,
        "citations": [hit.crime_no for hit in hits],
        "policy_code": "",
        "evidence": evidence,
    }
