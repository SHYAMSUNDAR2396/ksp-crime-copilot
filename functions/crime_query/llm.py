"""LLM clients. FakeLLM for tests, QuickMLLLM for Catalyst QuickML LLM Serving."""
import re

import requests

_FENCE = re.compile(r"^\s*```(?:sql)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    """Raised when the model cannot be reached or returns nothing usable."""


def strip_fence(text):
    """Remove a markdown code fence and a single trailing semicolon."""
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    return text.strip().rstrip(";").strip()


class FakeLLM(object):
    """Scripted responses. Records every prompt it was given."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if not self._responses:
            raise LLMError("FakeLLM script exhausted after {0} calls".format(len(self.prompts)))
        return self._responses.pop(0)


class QuickMLLLM(object):
    """Qwen 2.5-14B served by Catalyst QuickML LLM Serving."""

    def __init__(self, endpoint, api_key, timeout=30):
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout

    def complete(self, prompt):
        try:
            response = requests.post(
                self._endpoint,
                headers={
                    "Authorization": "Zoho-oauthtoken {0}".format(self._api_key),
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt, "temperature": 0.0, "max_tokens": 512},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as err:
            raise LLMError("QuickML request failed: {0}".format(err))
        except ValueError as err:
            raise LLMError("QuickML returned non-JSON: {0}".format(err))

        text = payload.get("output") or payload.get("text") or ""
        if not text.strip():
            raise LLMError("QuickML returned an empty completion")
        return text
