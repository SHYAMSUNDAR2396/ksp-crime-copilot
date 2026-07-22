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
