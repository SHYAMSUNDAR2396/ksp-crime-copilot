from functions.crime_query.mo_embeddings import DeterministicEmbeddingProvider, EmbeddingError


def test_local_provider_is_stable():
    provider = DeterministicEmbeddingProvider(dimension=64)
    assert provider.embed_documents(["ಬಾಗಿಲು ಮುರಿದು"])[0] == provider.embed_documents(["ಬಾಗಿಲು ಮುರಿದು"])[0]


def test_empty_narrative_is_rejected():
    try:
        DeterministicEmbeddingProvider().embed_documents([""])
    except EmbeddingError:
        return
    raise AssertionError("empty narrative was accepted")
import pytest

from functions.crime_query.mo_embeddings import (
    EmbeddingError,
    QuickMLMultilingualProvider,
)


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        return None


class FakeTransport:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResponse(self.body)


def test_quickml_provider_normalizes_batch_response():
    transport = FakeTransport({"embeddings": [[3.0, 4.0], [0.0, 2.0]]})
    provider = QuickMLMultilingualProvider("url", "token", "org", transport)
    assert provider.embed_documents(["ಕಳ್ಳತನ", "theft"]) == [[0.6, 0.8], [0.0, 1.0]]
    assert transport.calls[0][1]["headers"]["X-ZOHO-ORGID"] == "org"


def test_quickml_provider_rejects_vector_count_mismatch():
    provider = QuickMLMultilingualProvider(
        "url", "token", "org", FakeTransport({"embeddings": [[0.1, 0.2]]})
    )
    with pytest.raises(EmbeddingError, match="vector count"):
        provider.embed_documents(["kn", "en"])


def test_quickml_provider_enforces_batch_limit():
    provider = QuickMLMultilingualProvider(
        "url", batch_size=1, transport=FakeTransport({"embeddings": []})
    )
    with pytest.raises(EmbeddingError, match="batch"):
        provider.embed_documents(["one", "two"])
