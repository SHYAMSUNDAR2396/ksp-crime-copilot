import pytest

from functions.crime_query.conversation import ConversationTurn, InMemoryConversationStore
from functions.crime_query.conversation_api import export_session
from functions.crime_query.conversation_export import SmartBrowzPdfRenderer
from functions.crime_query.db import DBError
from functions.crime_query.rbac import Caller


class DB:
    def __init__(self):
        self.audit = []

    def caller_for(self, employee_id):
        if int(employee_id) != 9:
            return None
        return Caller(9, 1, 10, 4)

    def units_in_district(self, district_id):
        return [1, 2]

    def append_audit(self, **fields):
        self.audit.append(fields)


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


class Transport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


def test_export_session_uses_owned_cached_answers_and_citations():
    store = InMemoryConversationStore()
    store.append(
        "session-1", 9,
        ConversationTurn(1, "text", "<question>", "en", ("FIR/1",), "<answer>"),
    )
    result = export_session({"session_id": "session-1", "employee_id": 9}, DB(), store)
    assert result["code"] == "OK"
    assert result["content_type"] == "text/html"
    assert "&lt;question&gt;" in result["body"]
    assert "&lt;answer&gt;" in result["body"]
    assert "FIR/1" in result["body"]


def test_export_session_rejects_unknown_caller_without_content():
    result = export_session({"session_id": "session-1", "employee_id": 99}, DB(), InMemoryConversationStore())
    assert result["code"] == "CAPABILITY_DENIED"
    assert result["body"] == ""


def test_export_session_returns_bounded_service_error_when_identity_store_fails():
    class BrokenDB(DB):
        def caller_for(self, employee_id):
            raise DBError("connection details must not escape")

    result = export_session(
        {"session_id": "session-1", "employee_id": 9},
        BrokenDB(), InMemoryConversationStore(),
    )

    assert result == {
        "code": "SERVICE_UNAVAILABLE",
        "content_type": "text/plain",
        "body": "",
    }


def test_smartbrowz_renderer_posts_verified_document_as_pdf():
    transport = Transport(Response(b"%PDF-1.7\nverified"))
    renderer = SmartBrowzPdfRenderer("https://smartbrowz.example/convert", "token", transport=transport)

    result = renderer.render("<html><body>verified</body></html>")

    assert result.startswith(b"%PDF")
    args, kwargs = transport.calls[0]
    assert args == ("https://smartbrowz.example/convert",)
    assert kwargs["headers"]["Authorization"] == "Zoho-oauthtoken token"
    assert kwargs["json"]["output_options"] == {"output_type": "pdf"}
    assert kwargs["json"]["url"].startswith("data:text/html;base64,")


def test_smartbrowz_renderer_rejects_non_pdf_response():
    renderer = SmartBrowzPdfRenderer("endpoint", "token", transport=Transport(Response(b"not-pdf")))
    with pytest.raises(ValueError):
        renderer.render("<html></html>")
