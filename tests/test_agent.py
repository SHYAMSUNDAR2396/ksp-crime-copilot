import datetime as dt

import pytest

from functions.crime_query import agent
from functions.crime_query import db as db_module
from functions.crime_query.llm import FakeLLM
from functions.crime_query.rbac import Caller, MASK
from tools import gen_data

TODAY = dt.date(2026, 7, 9)
NOW = dt.datetime(2026, 7, 9, 10, 0, 0)
CONSTABLE = Caller(employee_id=9, unit_id=1, district_id=1, rank_hierarchy=6)
SP = Caller(employee_id=97, unit_id=1, district_id=1, rank_hierarchy=3)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_crime_numbers_are_extracted_from_any_column(db):
    rows = [{"CrimeNo": "1" * 18}, {"cn": "2" * 18}, {"n": 5}]
    assert agent.crime_numbers(rows) == ["1" * 18, "2" * 18]


def test_verify_citations_keeps_real_numbers():
    allowed = ["1" * 18]
    text, cited, bad = agent.verify_citations("See case {0}.".format("1" * 18), allowed)
    assert cited == ["1" * 18]
    assert bad == []
    assert "1" * 18 in text


def test_verify_citations_strips_invented_numbers():
    allowed = ["1" * 18]
    invented = "9" * 18
    text, cited, bad = agent.verify_citations(
        "Cases {0} and {1}.".format("1" * 18, invented), allowed
    )
    assert bad == [invented]
    assert invented not in text
    assert "1" * 18 in text


def test_row_level_answer_cites_returned_crimenos(db):
    sql = (
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.PoliceStationID = 1 LIMIT 3"
    )
    llm = FakeLLM([sql, "Found three cases."])
    result = agent.answer("recent cases", CONSTABLE, db, llm, TODAY, NOW)
    assert not result.refused
    assert len(result.citations) == 3
    assert all(len(c) == 18 for c in result.citations)


def test_aggregate_answer_cites_the_filter_instead(db):
    llm = FakeLLM([
        "SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster "
        "WHERE CaseMaster.CaseStatusID = 1",
        "There are many open cases.",
    ])
    result = agent.answer("how many open cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.citations == []
    assert "CaseStatusID" in result.filter_citation
    assert "PoliceStationID" in result.filter_citation  # the injected scope is visible


def test_scope_is_applied_so_constable_sees_only_own_unit(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo, CaseMaster.PoliceStationID FROM CaseMaster LIMIT 200",
        "ok",
    ])
    result = agent.answer("all cases", CONSTABLE, db, llm, TODAY, NOW)
    assert {row["PoliceStationID"] for row in result.rows} == {1}


def test_sensitive_column_is_masked_for_constable(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster "
        "LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID LIMIT 5",
        "ok",
    ])
    result = agent.answer("complainant castes", CONSTABLE, db, llm, TODAY, NOW)
    assert all(row["CasteID"] == MASK for row in result.rows)


def test_sp_aggregate_over_caste_is_not_masked(db):
    llm = FakeLLM([
        "SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) AS n "
        "FROM CaseMaster LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID "
        "GROUP BY ComplainantDetails.CasteID",
        "Distribution follows.",
    ])
    result = agent.answer("caste distribution", SP, db, llm, TODAY, NOW)
    assert not result.refused
    assert all(row["CasteID"] != MASK for row in result.rows)


def test_invalid_sql_triggers_exactly_one_repair_attempt(db):
    good = "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 2"
    llm = FakeLLM(["SELECT CaseMaster.PhoneNumber FROM CaseMaster", good, "ok"])
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert not result.refused
    assert len(llm.prompts) == 3
    assert "PhoneNumber" in llm.prompts[1]  # the rejection reason was fed back


def test_two_invalid_attempts_refuse_without_executing(db):
    llm = FakeLLM([
        "SELECT CaseMaster.PhoneNumber FROM CaseMaster",
        "DROP TABLE CaseMaster",
    ])
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
    assert result.rows == []
    assert result.text


def test_rbac_rejection_refuses_and_does_not_retry(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID "
        "WHERE ComplainantDetails.CasteID = 2 LIMIT 5",
        "unused",
    ])
    result = agent.answer("cases by caste", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
    assert len(llm.prompts) == 1  # an authorisation refusal is not a repairable error


def test_hallucinated_crimeno_is_stripped_and_counted(db):
    invented = "9" * 18
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.PoliceStationID = 1 LIMIT 1",
        "The relevant case is {0}.".format(invented),
    ])
    result = agent.answer("a case", CONSTABLE, db, llm, TODAY, NOW)
    assert result.hallucinated_crimenos == [invented]
    assert invented not in result.text


def test_every_call_writes_exactly_one_audit_row(db):
    def audit_count():
        return db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]

    before = audit_count()
    agent.answer(
        "cases", CONSTABLE, db,
        FakeLLM(["SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1", "ok"]),
        TODAY, NOW,
    )
    agent.answer("bad", CONSTABLE, db, FakeLLM(["DROP TABLE Unit", "DROP TABLE Unit"]), TODAY, NOW)
    assert audit_count() == before + 2


def test_audit_row_records_question_sql_and_crimenos(db):
    agent.answer(
        "how many cases in my station",
        CONSTABLE, db,
        FakeLLM(["SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1", "ok"]),
        TODAY, NOW,
    )
    row = db.execute_raw(
        'SELECT * FROM "AuditLog" ORDER BY AuditID DESC LIMIT 1'
    )[0]
    assert row["Question"] == "how many cases in my station"
    assert "CrimeNo" in row["GeneratedSQL"]
    assert "PoliceStationID" in row["ExecutedSQL"]
    assert row["EmployeeID"] == CONSTABLE.employee_id
    assert len(row["CrimeNos"].split(",")[0]) == 18


def test_db_error_is_reported_not_raised(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1",
        "ok",
    ])
    db.close()  # force a DBError on execute
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
