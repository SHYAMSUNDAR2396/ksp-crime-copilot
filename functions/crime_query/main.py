"""Catalyst Advanced I/O entrypoint.

Thin by design: pick the backend, resolve the caller, pivot the language,
shape the response. Everything else is tested library code.
"""
import datetime as dt
import os

from . import agent, catalog, translate
from .db import ZcqlDB
from .llm import QuickMLLLM
from .rbac import MASK


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
                "sql": "", "rows": [], "citations": [], "language": "en"}

    language = translate.detect(question)
    try:
        english_question = translate.to_english(question, translator)
    except translate.TranslationError:
        return {"refused": True,
                "answer": "Translation service is unavailable; please try again in English.",
                "sql": "", "rows": [], "citations": [], "language": "en"}

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
    }


def handler(request):
    """Catalyst Advanced I/O Python entrypoint. Real signature confirmed by
    running `catalyst init` (Task 2): a Flask ``Request`` in, a Flask
    response out -- not the ``(context, basic_io)`` shape the plan guessed.
    """
    import zcatalyst_sdk
    from flask import jsonify, make_response

    app = zcatalyst_sdk.initialize()
    db = ZcqlDB(app)
    llm = QuickMLLLM(os.environ["QUICKML_ENDPOINT"], os.environ["QUICKML_API_KEY"])
    translator = translate.ZiaTranslator(app)

    payload = request.get_json(silent=True) or {}
    result = handle_question(payload, db, llm, translator, dt.date.today())

    return make_response(jsonify(result), 403 if result["refused"] else 200)
