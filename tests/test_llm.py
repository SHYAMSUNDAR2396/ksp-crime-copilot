import pytest

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
