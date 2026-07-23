"""LLM clients. FakeLLM for tests, QuickMLLLM for Catalyst QuickML LLM Serving."""
import re

import requests

_FENCE = re.compile(r"^\s*```(?:sql)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)
_THINK_END = "</think>"


class LLMError(Exception):
    """Raised when the model cannot be reached or returns nothing usable."""


def strip_fence(text):
    """Remove a markdown code fence and a single trailing semicolon."""
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    return text.strip().rstrip(";").strip()


def _strip_thinking(text):
    """GLM-4.7-Flash emits a visible reasoning trace ending in </think>
    before its real answer, with no matching opening tag in the response
    body (the chat template opens it implicitly). Keep only what follows."""
    if _THINK_END in text:
        return text.split(_THINK_END, 1)[1].strip()
    return text.strip()


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
    """GLM-4.7-Flash served by Catalyst QuickML LLM Serving.

    POST {"model", "messages", ...} -> {"response": "...", "usage": {...}}.
    Confirmed empirically against the live deployment, not the console's own
    documented sample -- the sample shows an OpenAI-style {"choices": [...]}
    shape that this deployment does not actually return. Two more things
    only a live call revealed: this deployment has its own large baked-in
    system prompt and refuses (misreading it as an override attempt) if the
    caller supplies its own "system"-role message, so `messages` is
    user-role only; and it's a "thinking" model whose response text
    contains a visible reasoning trace ending in </think> before the real
    answer, which _strip_thinking() removes.
    """

    MODEL = "crm-di-glm47b_30b_it"

    def __init__(self, endpoint, token, org_id, timeout=60, model=None):
        self._endpoint = endpoint
        self._token = token
        self._org_id = org_id
        self._timeout = timeout
        self._model = model or self.MODEL

    def complete(self, prompt):
        try:
            response = requests.post(
                self._endpoint,
                headers={
                    "Authorization": "Zoho-oauthtoken {0}".format(self._token),
                    "CATALYST-ORG": self._org_id,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 2048,
                    "stream": False,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise LLMError(
                    "QuickML returned an unexpected response shape: {0}".format(type(payload).__name__)
                )
            raw = payload.get("response")
            text = _strip_thinking(raw) if isinstance(raw, str) else ""
        except requests.RequestException as err:
            raise LLMError("QuickML request failed: {0}".format(err))
        except ValueError as err:
            raise LLMError("QuickML returned non-JSON: {0}".format(err))

        if not text.strip():
            raise LLMError("QuickML returned an empty completion")
        return text
