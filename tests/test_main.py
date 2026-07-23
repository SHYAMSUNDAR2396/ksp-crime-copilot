import datetime as dt

import pytest

from functions.crime_query.access import AccessContext
from functions.crime_query import db as db_module
from functions.crime_query import main, translate
from functions.crime_query.conversation import InMemoryConversationStore
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
    payload = {
        "employee_id": 9,
        "question": "recent cases",
        "task_type": "structured_query",
    }
    llm = FakeLLM([SQL, "Two cases found."])
    result = main.handle_question(payload, db, llm, translate.NullTranslator(), TODAY)
    assert result["language"] == "en"
    assert len(result["citations"]) == 2
    assert "PoliceStationID" in result["sql"]
    assert result["refused"] is False
    assert result["evidence"]["status"] == "ok"
    assert result["evidence"]["citations"] == result["citations"]


def test_unknown_employee_is_rejected_before_any_llm_call(db):
    llm = FakeLLM([])
    result = main.handle_question(
        {"employee_id": 999999, "question": "x"}, db, llm, translate.NullTranslator(), TODAY
    )
    assert result["refused"] is True
    assert llm.prompts == []


def test_malformed_analytics_provider_configuration_uses_safe_fallback(monkeypatch):
    monkeypatch.setenv("QUICKML_ANALYTICS_ENDPOINT", "https://analytics.example")

    class App:
        def credential(self):
            class Credential:
                def token(self):
                    return "token"
            return Credential()

    # A malformed timeout is a deployment issue, not a reason to break the
    # otherwise deterministic analytics path.
    monkeypatch.setenv("QUICKML_ANALYTICS_TIMEOUT", "not-a-number")
    assert main._analytics_provider(App()) is None


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

    name_sql = (
        "SELECT CaseMaster.CrimeNo, Accused.AccusedName FROM CaseMaster "
        "JOIN Accused ON Accused.CaseMasterID = CaseMaster.ROWID "
        "WHERE CaseMaster.PoliceStationID = 1 LIMIT 1"
    )
    accused_name = db.execute(name_sql)[0]["AccusedName"]

    payload = {"employee_id": 9, "question": "ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಪ್ರಕರಣಗಳು?"}
    llm = FakeLLM([
        name_sql,
        "Cases {0} and {1} involve accused {2}.".format(real[0], real[0], accused_name),
    ])
    result = main.handle_question(payload, db, llm, Echo(), TODAY)

    assert result["language"] == "kn"
    assert "<kn>" in result["answer"]
    # Crime numbers survive the round trip untranslated and unmangled.
    assert real[0] in result["answer"]
    # Names present in the row data survive the round trip too, not just citations.
    assert accused_name in result["answer"]
    assert accused_name.upper() not in result["answer"].replace(accused_name, "")


def test_translation_error_on_input_side_is_refused_gracefully(db):
    class Broken:
        def translate(self, text, source, target):
            raise translate.TranslationError("Zia is down")

    payload = {"employee_id": 9, "question": "ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಪ್ರಕರಣಗಳು?"}
    result = main.handle_question(payload, db, FakeLLM([]), Broken(), TODAY)

    assert result["refused"] is True
    assert result["sql"] == ""
    assert result["rows"] == []
    assert result["evidence"]["status"] == "scope_denied"
    assert result["citations"] == []
    assert result["language"] == "en"


def test_response_never_leaks_the_generated_sql_on_refusal(db):
    llm = FakeLLM(["DROP TABLE Unit", "DROP TABLE Unit"])
    result = main.handle_question(
        {"employee_id": 9, "question": "drop everything"}, db, llm,
        translate.NullTranslator(), TODAY,
    )
    assert result["refused"] is True
    assert result["sql"] == ""


def test_capability_denial_returns_stable_policy_code_without_identifiers(db, monkeypatch):
    llm = FakeLLM([])

    def deny_structured(_caller, _db):
        return AccessContext(
            employee_id=9,
            rank_hierarchy=6,
            access_bucket="CONSTABLE",
            unit_ids=(1,),
            district_ids=(1,),
            capabilities=frozenset(),
            sensitive_data_policy="rbac_masked",
            alert_actions=frozenset(),
            audit_visibility="own_actions",
        )

    monkeypatch.setattr(main.access, "resolve_access_context", deny_structured)
    result = main.handle_question(
        {"employee_id": 9, "question": "show case 111111111111111111 links"},
        db,
        llm,
        translate.NullTranslator(),
        TODAY,
    )

    assert result["refused"] is True
    assert result["policy_code"] == "CAPABILITY_DENIED"
    assert result["rows"] == []
    assert result["citations"] == []
    assert "111111111111111111" not in result["answer"]
    assert llm.prompts == []


def test_graph_task_type_denial_persists_safe_policy_audits(db):
    before = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    result = main.handle_question(
        {
            "employee_id": 4,
            "task_type": "graph",
            "question": "show links for CrimeNo 111111111111111111 and Ravi Kumar",
        },
        db,
        FakeLLM([]),
        translate.NullTranslator(),
        TODAY,
    )

    after = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    rows = db.execute_raw(
        'SELECT * FROM "AuditLog" ORDER BY AuditID DESC LIMIT 2'
    )

    assert result["refused"] is True
    assert result["policy_code"] == "CAPABILITY_DENIED"
    assert result["sql"] == ""
    assert result["rows"] == []
    assert result["citations"] == []
    assert "111111111111111111" not in result["answer"]
    assert "Ravi Kumar" not in result["answer"]
    assert after == before + 2
    assert len(rows) == 2
    for row in rows:
        assert row["CrimeNos"] == ""
        assert "111111111111111111" not in row["Question"]
        assert "111111111111111111" not in row["GeneratedSQL"]
        assert "111111111111111111" not in row["ExecutedSQL"]
        assert "Ravi Kumar" not in row["Question"]
        assert "Ravi Kumar" not in row["GeneratedSQL"]
        assert "Ravi Kumar" not in row["ExecutedSQL"]
    assert rows[0]["RowCount"] == 0


def test_voice_question_uses_text_path_and_persists_citations(db):
    llm = FakeLLM([SQL, "Two cases found."])
    store = InMemoryConversationStore()
    result = main.handle_voice_question(
        {
            "employee_id": 9,
            "session_id": "voice-session",
            "turn_id": 1,
            "transcript": "recent cases",
            "response_language": "en",
        },
        db, llm, translate.NullTranslator(), TODAY, store,
    )
    assert result["turn_id"] == 1
    assert result["voice"]["text"]
    assert result["citations"]
    assert store.load("voice-session", 9).turns[0].citations == tuple(result["citations"])


def test_typed_session_follow_up_reuses_prior_verified_context(db):
    llm = FakeLLM([SQL, "First.", SQL, "Follow-up."])
    store = InMemoryConversationStore()
    first = main.handle_session_question(
        {"employee_id": 9, "session_id": "text-session", "turn_id": 1,
         "question": "recent cases"},
        db, llm, translate.NullTranslator(), TODAY, store,
    )
    second = main.handle_session_question(
        {"employee_id": 9, "session_id": "text-session", "turn_id": 2,
         "question": "only theft"},
        db, llm, translate.NullTranslator(), TODAY, store,
    )
    assert first["turn_id"] == 1
    assert second["turn_id"] == 2
    assert "Previous verified question" in llm.prompts[-2]
    assert [turn.turn_id for turn in store.load("text-session", 9).turns] == [1, 2]


def test_unauthenticated_typed_session_fails_before_session_store_or_llm(db):
    class Store:
        def load(self, *args):
            raise AssertionError("unauthenticated session must not load state")

        def append(self, *args):
            raise AssertionError("unauthenticated session must not append state")

    llm = FakeLLM([])
    result = main.handle_session_question(
        {"employee_id": None, "session_id": "s", "turn_id": 1, "question": "recent cases"},
        db, llm, translate.NullTranslator(), TODAY, Store(),
    )

    assert result["refused"] is True
    assert result["turn_id"] == 1
    assert llm.prompts == []


def test_malformed_task_type_falls_back_to_structured_task(db):
    llm = FakeLLM([SQL, "ok"])
    result = main.handle_question(
        {"employee_id": 9, "task_type": [], "question": "recent cases"},
        db, llm, translate.NullTranslator(), TODAY,
    )
    assert result["refused"] is False


def test_non_string_question_is_rejected_without_llm_call(db):
    llm = FakeLLM([])
    result = main.handle_question(
        {"employee_id": 9, "question": []}, db, llm,
        translate.NullTranslator(), TODAY,
    )
    assert result["refused"] is True
    assert llm.prompts == []
