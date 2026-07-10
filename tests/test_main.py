import datetime as dt

import pytest

from functions.crime_query import db as db_module
from functions.crime_query import main, translate
from functions.crime_query.llm import FakeLLM
from tools import gen_data

TODAY = dt.date(2026, 7, 9)
SQL = "SELECT CaseMaster.CrimeNo FROM CaseMaster WHERE CaseMaster.PoliceStationID = 1 LIMIT 2"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_english_question_returns_answer_sql_and_citations(db):
    payload = {"employee_id": 9, "question": "recent cases"}
    llm = FakeLLM([SQL, "Two cases found."])
    result = main.handle_question(payload, db, llm, translate.NullTranslator(), TODAY)
    assert result["language"] == "en"
    assert len(result["citations"]) == 2
    assert "PoliceStationID" in result["sql"]
    assert result["refused"] is False


def test_unknown_employee_is_rejected_before_any_llm_call(db):
    llm = FakeLLM([])
    result = main.handle_question(
        {"employee_id": 999999, "question": "x"}, db, llm, translate.NullTranslator(), TODAY
    )
    assert result["refused"] is True
    assert llm.prompts == []


def test_missing_question_is_rejected(db):
    result = main.handle_question(
        {"employee_id": 9}, db, FakeLLM([]), translate.NullTranslator(), TODAY
    )
    assert result["refused"] is True


def test_kannada_question_is_pivoted_and_answer_rendered_back(db):
    class Echo:
        """Stands in for Zia. Mangles every character it is given, on purpose:
        anything that survives verbatim must have been protected."""

        def translate(self, text, source, target):
            return "<{0}>{1}".format(target, text.upper())

    real = [row["CrimeNo"] for row in db.execute(SQL)]
    assert len(real) == 2

    payload = {"employee_id": 9, "question": "ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಪ್ರಕರಣಗಳು?"}
    llm = FakeLLM([SQL, "Cases {0} and {1}.".format(*real)])
    result = main.handle_question(payload, db, llm, Echo(), TODAY)

    assert result["language"] == "kn"
    assert "<kn>" in result["answer"]
    assert sorted(result["citations"]) == sorted(real)
    # Crime numbers survive the round trip untranslated and unmangled.
    for crime_no in real:
        assert crime_no in result["answer"]


def test_response_never_leaks_the_generated_sql_on_refusal(db):
    llm = FakeLLM(["DROP TABLE Unit", "DROP TABLE Unit"])
    result = main.handle_question(
        {"employee_id": 9, "question": "drop everything"}, db, llm,
        translate.NullTranslator(), TODAY,
    )
    assert result["refused"] is True
    assert result["sql"] == ""
