from unittest.mock import MagicMock, patch

import pytest
import requests

from functions.crime_query import llm


def test_fake_llm_returns_scripted_responses_in_order():
    fake = llm.FakeLLM(["first", "second"])
    assert fake.complete("a") == "first"
    assert fake.complete("b") == "second"
    assert fake.prompts == ["a", "b"]


def test_fake_llm_raises_when_script_exhausted():
    fake = llm.FakeLLM(["only"])
    fake.complete("a")
    with pytest.raises(llm.LLMError):
        fake.complete("b")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SELECT 1", "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("  ```sql\nSELECT 1;\n```  ", "SELECT 1"),
        ("SELECT 1;", "SELECT 1"),
    ],
)
def test_strip_fence(raw, expected):
    assert llm.strip_fence(raw) == expected


def _make_client():
    return llm.QuickMLLLM("https://quickml.example/complete", "test-token", "test-org")


def _quickml_response(text):
    return {"response": text, "usage": {"total_tokens": 1}}


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_success_sends_temperature_zero(mock_post):
    mock_post.return_value = MagicMock(json=lambda: _quickml_response("SELECT 1"))
    client = _make_client()

    result = client.complete("give me sql")

    assert result == "SELECT 1"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["temperature"] == 0.0
    assert kwargs["json"]["model"] == llm.QuickMLLLM.MODEL
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "give me sql"}]
    assert kwargs["headers"]["Authorization"] == "Zoho-oauthtoken test-token"
    assert kwargs["headers"]["CATALYST-ORG"] == "test-org"


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_strips_thinking_trace(mock_post):
    """GLM-4.7-Flash emits a visible reasoning trace with no opening tag,
    ending in </think>, before the real answer -- confirmed against a live
    call to the deployed model, not documentation."""
    mock_post.return_value = MagicMock(
        json=lambda: _quickml_response("some reasoning...</think>SELECT 1")
    )
    client = _make_client()

    assert client.complete("give me sql") == "SELECT 1"


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_connection_error(mock_post):
    mock_post.side_effect = requests.ConnectionError("boom")
    client = _make_client()

    with pytest.raises(llm.LLMError):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_http_error(mock_post):
    response = MagicMock()
    response.raise_for_status.side_effect = requests.HTTPError("500")
    mock_post.return_value = response
    client = _make_client()

    with pytest.raises(llm.LLMError):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_non_json_body(mock_post):
    response = MagicMock()
    response.json.side_effect = ValueError("not json")
    mock_post.return_value = response
    client = _make_client()

    with pytest.raises(llm.LLMError):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_non_dict_body(mock_post):
    mock_post.return_value = MagicMock(json=lambda: [1, 2, 3])
    client = _make_client()

    with pytest.raises(llm.LLMError):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_non_string_response(mock_post):
    mock_post.return_value = MagicMock(json=lambda: {"response": 42})
    client = _make_client()

    with pytest.raises(llm.LLMError):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_empty_response(mock_post):
    mock_post.return_value = MagicMock(json=lambda: _quickml_response(""))
    client = _make_client()

    with pytest.raises(llm.LLMError, match="empty completion"):
        client.complete("give me sql")


@patch("functions.crime_query.llm.requests.post")
def test_quickml_complete_raises_llm_error_on_missing_response(mock_post):
    mock_post.return_value = MagicMock(json=lambda: {"error": "bad request"})
    client = _make_client()

    with pytest.raises(llm.LLMError, match="empty completion"):
        client.complete("give me sql")
