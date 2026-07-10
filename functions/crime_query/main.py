"""Catalyst Advanced I/O entrypoint.

Thin by design: pick the backend, resolve the caller, pivot the language,
shape the response. Everything else is tested library code.
"""
import datetime as dt
import json
import os

from . import agent, translate
from .db import SqliteDB, ZcqlDB
from .llm import QuickMLLLM


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
    english_question = translate.to_english(question, translator)

    result = agent.answer(english_question, caller, db, llm, today)

    protected = list(result.citations)
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


def handler(context, basic_io):
    """Signature must match the stub the Catalyst CLI generated in Task 2."""
    import zcatalyst_sdk

    app = zcatalyst_sdk.initialize()
    db = ZcqlDB(app)
    llm = QuickMLLLM(os.environ["QUICKML_ENDPOINT"], os.environ["QUICKML_API_KEY"])
    translator = translate.ZiaTranslator(app)

    payload = json.loads(basic_io.get_argument("body") or "{}")
    result = handle_question(payload, db, llm, translator, dt.date.today())

    basic_io.set_status(403 if result["refused"] else 200)
    basic_io.write(json.dumps(result, default=str))
