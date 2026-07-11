"""Prompt construction for NL->SQL generation and answer composition.

Lookup values are read live from the database so the model never invents a
crime head or a station that does not exist in the data (PLAN.md 1.1).
"""
import json

try:
    from . import catalog
except ImportError:
    import catalog

LOOKUP_FIELDS = [
    ("CrimeHead", "CrimeGroupName"),
    ("CrimeSubHead", "CrimeHeadName"),
    ("CaseStatusMaster", "CaseStatusName"),
    ("District", "DistrictName"),
    ("Unit", "UnitName"),
    ("Act", "ShortName"),
    ("CaseCategory", "LookupValue"),
    ("GravityOffence", "LookupValue"),
    ("OccupationMaster", "OccupationName"),
]

MAX_ROWS_IN_ANSWER_PROMPT = 40

_RULES = """Rules, all mandatory:
1. Emit exactly one SELECT statement. Nothing else. No INSERT, UPDATE, DELETE, DROP.
2. Qualify every column with its table name, e.g. CaseMaster.CrimeNo, never CrimeNo.
3. Use only these functions: COUNT, SUM, AVG, MIN, MAX. No date functions, no CAST,
   no string functions.
4. No subqueries, no CTEs, no UNION, no window functions.
5. Dates are stored as text in 'YYYY-MM-DD' form. Compare them with string literals
   you compute yourself from today's date. Example: the last 6 months is
   CaseMaster.CrimeRegisteredDate >= '2026-01-09'.
6. Any query that reads case data must include CaseMaster, joining back to it on
   CaseMasterID, so the result can be scoped to the caller's role.
7. Any query returning individual cases (not aggregated) must select CaseMaster.CrimeNo,
   so the answer can cite them. An aggregate query need not select CaseMaster.CrimeNo,
   unless it also projects a column that names a person (e.g. an accused, victim, or
   complainant name) or reproduces case narrative text (BriefFacts) - then it must
   select CaseMaster.CrimeNo too, so those rows can still be cited.
8. Add a LIMIT. Never above 200.
9. Use only the exact lookup values listed below. If the question names something not
   in those lists, choose the closest listed value.

Return only the SQL. No explanation, no markdown fence."""

_ANSWER_RULES = """Rules:
1. Answer only from the rows given. Do not use outside knowledge.
2. Cite crime numbers only if they appear verbatim in the rows above. Never invent,
   complete, or adjust a crime number.
3. If the rows are empty, say plainly that no matching cases were found.
4. Keep names and crime numbers exactly as written.
5. Two or three sentences."""


def lookup_values(db):
    """Read the live distinct values for every lookup field."""
    values = {}
    for table, column in LOOKUP_FIELDS:
        key = "{0}.{1}".format(table, column)
        values[key] = db.lookup(table, column)
    return values


def build_prompt(question, db, today):
    values = lookup_values(db)
    lookup_block = "\n".join(
        "{0}: {1}".format(key, ", ".join(str(v) for v in vals))
        for key, vals in values.items()
    )
    return (
        "You translate questions about the Karnataka police crime database into SQL.\n\n"
        "Today's date is {today}.\n\n"
        "Schema:\n{schema}\n\n"
        "Lookup values that exist in the data:\n{lookups}\n\n"
        "{rules}\n\n"
        "Question: {question}\nSQL:"
    ).format(
        today=today.isoformat(),
        schema=catalog.describe(),
        lookups=lookup_block,
        rules=_RULES,
        question=question,
    )


def build_answer_prompt(question, rows, sql):
    shown = rows[:MAX_ROWS_IN_ANSWER_PROMPT]
    body = json.dumps(shown, indent=None, default=str)
    return (
        "You answer questions about police case data using only the rows provided.\n\n"
        "Question: {question}\n\n"
        "SQL that produced the rows:\n{sql}\n\n"
        "Rows returned: {total} (showing the first {shown})\n{body}\n\n"
        "{rules}\n\nAnswer:"
    ).format(
        question=question,
        sql=sql,
        total=len(rows),
        shown=len(shown),
        body=body,
        rules=_ANSWER_RULES,
    )


def repair_prompt(previous_sql, error, original_prompt):
    """Second attempt after a ValidationError. The error text is the hint."""
    return (
        "{original}\n\n"
        "Your previous attempt was rejected.\n"
        "SQL: {sql}\n"
        "Reason: {error}\n\n"
        "Emit corrected SQL only.\nSQL:"
    ).format(original=original_prompt, sql=previous_sql, error=error)
