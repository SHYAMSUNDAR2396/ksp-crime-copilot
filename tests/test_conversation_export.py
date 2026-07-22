from functions.crime_query.access import AccessContext
from functions.crime_query.conversation_export import export_conversation


def context():
    return AccessContext(9, 4, "INSPECTOR", (1,), (10,),
                         frozenset({"export_conversation"}), "rbac_masked",
                         frozenset(), "own_actions")


def test_export_escapes_content_and_preserves_citations():
    result = export_conversation(context(), "s1", 9, [{
        "question": "<script>bad</script>",
        "answer": "Answer",
        "citations": ["FIR/1"],
        "raw_audio": "never export",
    }])
    assert result["content_type"] == "text/html"
    assert "<script>" not in result["body"]
    assert "FIR/1" in result["body"]
    assert "never export" not in result["body"]


def test_export_requires_session_owner():
    result = export_conversation(context(), "s1", 10, [{"answer": "secret"}])
    assert result["code"] == "SCOPE_DENIED"
    assert result["body"] == ""
