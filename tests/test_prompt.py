import datetime as dt

import pytest

from functions.crime_query import db as db_module
from functions.crime_query import prompt
from tools import gen_data

TODAY = dt.date(2026, 7, 9)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_lookup_values_include_real_data_values(db):
    values = prompt.lookup_values(db)
    assert "Two-Wheeler Theft" in values["CrimeSubHead.CrimeHeadName"]
    assert "Bengaluru East" in values["Unit.UnitName"]
    assert "Bengaluru City" in values["District.DistrictName"]
    assert "Charge Sheeted" in values["CaseStatusMaster.CaseStatusName"]


def test_prompt_contains_schema_lookups_question_and_today(db):
    text = prompt.build_prompt("how many burglaries last month", db, TODAY)
    assert "CaseMaster(" in text
    assert "Two-Wheeler Theft" in text
    assert "how many burglaries last month" in text
    assert "2026-07-09" in text


def test_prompt_states_the_hard_rules(db):
    text = prompt.build_prompt("x", db, TODAY)
    for rule in [
        "SELECT",
        "CaseMaster.CrimeNo",
        "qualify every column",
        "COUNT, SUM, AVG, MIN, MAX",
        "no subqueries",
        "date functions",
    ]:
        assert rule.lower() in text.lower(), rule


def test_prompt_names_catalyst_zcql_as_execution_dialect(db):
    text = prompt.build_prompt("recent burglary cases", db, TODAY)
    assert "Zoho Catalyst ZCQL" in text
    assert "not generic SQLite" in text


def test_prompt_includes_runtime_fk_map_and_server_scope_boundary(db):
    text = prompt.build_prompt("recent burglary cases", db, TODAY)
    assert "Catalyst Foreign Key" in text
    assert "parent.ROWID" in text
    assert "server adds and verifies" in text


def test_prompt_teaches_rowid_joins(db):
    """ZCQL Foreign Key columns reference the parent's internal ROWID, not
    any business primary key -- confirmed against a live deployment. The
    schema description and the rules must both say so, or the model has
    no way to know this and will generate SQL that fails at execution."""
    text = prompt.build_prompt("how many burglaries in Bengaluru East", db, TODAY)
    assert "-> Unit.ROWID" in text
    assert "-> Unit.UnitID" not in text
    assert "rowid" in text.lower()


def test_prompt_forbids_the_audit_table(db):
    assert "AuditLog" not in prompt.build_prompt("x", db, TODAY)


def test_answer_prompt_carries_rows_and_forbids_invented_crimenos():
    text = prompt.build_answer_prompt(
        "how many?",
        [{"CrimeNo": "1" * 18}],
        "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1",
    )
    assert "1" * 18 in text
    assert "never invent" in text.lower()


def test_prompt_requires_crimeno_for_identifying_aggregates(db):
    text = prompt.build_prompt("who are the most frequent accused persons?", db, TODAY)
    assert "names a person" in text.lower()
    assert "brieffacts" in text.lower()


def test_answer_prompt_truncates_large_row_sets():
    rows = [{"CrimeNo": str(i).zfill(18)} for i in range(500)]
    text = prompt.build_answer_prompt("q", rows, "SELECT 1")
    assert str(len(rows)) in text  # the true count is stated
    assert len(text) < 40000
