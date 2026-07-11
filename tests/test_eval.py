import pytest

from eval import run_eval
from functions.crime_query import db as db_module
from functions.crime_query import validate
from functions.crime_query.llm import FakeLLM
from tools import gen_data


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


@pytest.fixture(scope="module")
def questions():
    return run_eval.load_questions(run_eval.QUESTIONS_PATH)


def test_thirty_questions_with_unique_ids(questions):
    assert len(questions) == 30
    assert len({q["id"] for q in questions}) == 30


def test_every_gold_query_passes_the_validator(questions):
    for question in questions:
        validate.validate(question["sql"])  # raises on failure


def test_every_gold_query_returns_at_least_one_row(db, questions):
    for question in questions:
        rows = db.execute(question["sql"])
        assert rows, question["id"]


def test_ipc_302_count_is_not_silently_zero(db, questions):
    """Question 20 used to filter ActSectionAssociation.ActID = 'IPC'
    directly -- a business-key literal against a column that now holds
    Act's ROWID after the remap in tools/gen_data.py. Verified live: this
    silently returned 0 instead of the correct 67. A COUNT query always
    returns exactly one row even when the count itself is wrong, so
    test_every_gold_query_returns_at_least_one_row can't catch this class
    of bug -- this test checks the actual value."""
    q20 = next(q for q in questions if q["id"] == 20)
    rows = db.execute(q20["sql"])
    assert rows[0]["n"] == 67


def test_normalise_is_order_insensitive():
    a = [{"x": 1, "y": "b"}, {"x": 2, "y": "a"}]
    b = [{"x": 2, "y": "a"}, {"x": 1, "y": "b"}]
    assert run_eval.normalise(a) == run_eval.normalise(b)


def test_normalise_ignores_column_names_but_not_values():
    assert run_eval.normalise([{"n": 5}]) == run_eval.normalise([{"count": 5}])
    assert run_eval.normalise([{"n": 5}]) != run_eval.normalise([{"n": 6}])


def test_score_accepts_equivalent_aggregate_spellings(db):
    gold = db.execute('SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster')
    generated = db.execute('SELECT COUNT(*) AS total FROM CaseMaster')
    assert run_eval.score(generated, gold)


def test_run_scores_a_perfect_model_at_one(db, questions):
    subset = questions[:3]
    scripted = []
    for question in subset:
        scripted.extend([question["sql"], "Answer."])
    report = run_eval.run(db, FakeLLM(scripted), subset, run_eval.TODAY)
    assert report["accuracy"] == 1.0
    assert report["hallucination_rate"] == 0.0
    assert report["p95_latency_s"] >= 0


def test_run_counts_a_hallucinated_crimeno(db, questions):
    question = questions[3]  # the murder-crime-number listing
    invented = "9" * 18
    llm = FakeLLM([question["sql"], "The case is {0}.".format(invented)])
    report = run_eval.run(db, llm, [question], run_eval.TODAY)
    assert report["hallucination_rate"] == 1.0
    assert report["accuracy"] == 1.0  # the SQL was right; only the prose lied
