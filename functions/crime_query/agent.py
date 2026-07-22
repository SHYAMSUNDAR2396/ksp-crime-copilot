"""Orchestration: generate -> validate -> scope -> execute -> redact -> compose
-> verify -> audit.

Every path writes exactly one audit row, including refusals.
"""
import datetime as dt
import re
from dataclasses import dataclass, field

from sqlglot import exp

try:
    from . import prompt as prompt_module
    from . import rbac, validate
    from .db import DBError
    from .llm import LLMError, strip_fence
except ImportError:
    import prompt as prompt_module
    import rbac, validate
    from db import DBError
    from llm import LLMError, strip_fence

CRIMENO_RE = re.compile(r"\b\d{18}\b")

REFUSAL_TEXT = (
    "I could not answer that safely. {reason} "
    "Try naming the crime type, station, or date range explicitly."
)


@dataclass
class Answer:
    text: str
    sql: str = ""
    rows: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    filter_citation: str = ""
    hallucinated_crimenos: list = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""
    audit_failed: bool = False
    policy_code: str = ""


def crime_numbers(rows):
    """Every 18-digit crime number present in the result rows, in row order."""
    found = []
    for row in rows:
        for value in row.values():
            if isinstance(value, str) and CRIMENO_RE.fullmatch(value):
                if value not in found:
                    found.append(value)
    return found


def verify_citations(text, allowed):
    """Strip crime numbers the rows do not contain. Returns (text, cited, hallucinated)."""
    allowed_set = set(allowed)
    cited, hallucinated = [], []

    for candidate in CRIMENO_RE.findall(text):
        if candidate in allowed_set:
            if candidate not in cited:
                cited.append(candidate)
        elif candidate not in hallucinated:
            hallucinated.append(candidate)

    clean = text
    for bad in hallucinated:
        clean = clean.replace(bad, "[unverified reference removed]")
    return clean, cited, hallucinated


def _filter_citation(sql):
    """The WHERE clause that produced an aggregate, rendered for display."""
    try:
        select = validate.validate(sql)
    except validate.ValidationError:
        return ""
    where = select.args.get("where")
    if where is None:
        return "no filter (all cases in scope)"
    return where.this.sql()


def _generate_sql(question, caller, db, llm, today):
    """One generation, one repair. Returns validated AST or raises ValidationError."""
    base_prompt = prompt_module.build_prompt(question, db, today)
    raw = strip_fence(llm.complete(base_prompt))
    try:
        return validate.validate(raw), raw
    except validate.ValidationError as first_error:
        repair = prompt_module.repair_prompt(raw, str(first_error), base_prompt)
        retry = strip_fence(llm.complete(repair))
        try:
            return validate.validate(retry), retry
        except validate.ValidationError as second_error:
            second_error.sql = retry  # preserve what was tried for the audit trail
            raise


def _audit(db, caller, question, generated, executed, citations, rows, now):
    """Returns True if the audit row was written, False if the write failed.

    A broken audit sink must never crash the user-facing answer path, so the
    failure is caught here -- but only DBError, since db.py now guarantees
    both backends raise DBError (never a raw driver exception) on failure.
    """
    try:
        db.append_audit(
            EmployeeID=caller.employee_id,
            RankHierarchy=caller.rank_hierarchy,
            Question=question,
            GeneratedSQL=generated,
            ExecutedSQL=executed,
            CrimeNos=",".join(citations),
            RowCount=len(rows),
            LoggedAt=now.isoformat(),
        )
        return True
    except DBError:
        return False


def _refuse(db, caller, question, generated, reason, now):
    audit_ok = _audit(db, caller, question, generated, "", [], [], now)
    return Answer(
        text=REFUSAL_TEXT.format(reason=reason),
        sql=generated,
        refused=True,
        refusal_reason=reason,
        audit_failed=not audit_ok,
    )


def answer(question, caller, db, llm, today, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    generated = ""

    try:
        select, generated = _generate_sql(question, caller, db, llm, today)
    except (validate.ValidationError, LLMError, DBError) as err:
        # DBError belongs here too: build_prompt reads lookup values from the DB.
        generated = getattr(err, "sql", generated)
        return _refuse(db, caller, question, generated, str(err), now)

    try:
        units = rbac.allowed_units(caller, db)
        executed_sql, redact_keys = rbac.apply(select, caller, units)
    except rbac.RbacError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    try:
        rows = db.execute(executed_sql)
    except DBError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    rows = rbac.redact_rows(rows, redact_keys)
    allowed = crime_numbers(rows)

    try:
        composed = llm.complete(prompt_module.build_answer_prompt(question, rows, executed_sql))
    except LLMError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    text, _mentioned, hallucinated = verify_citations(composed, allowed)
    filter_citation = _filter_citation(executed_sql) if not allowed else ""

    # Citations are the crime numbers the *rows* contain, not the ones the model
    # chose to mention. A model that answers "three cases were found" without
    # listing them still produces a fully citable answer.
    audit_ok = _audit(db, caller, question, generated, executed_sql, allowed, rows, now)

    return Answer(
        text=text,
        sql=executed_sql,
        rows=rows,
        citations=allowed,
        filter_citation=filter_citation,
        hallucinated_crimenos=hallucinated,
        audit_failed=not audit_ok,
    )
