from functions.crime_query.access import AccessContext
from functions.crime_query.mo_embeddings import DeterministicEmbeddingProvider
from functions.crime_query.mo_matcher import MoMatcher


class MemoryIndex:
    def search(self, query, records, limit, excluded_case_id):
        from functions.crime_query.mo_index import _cosine, IndexHit
        values = sorted(((_cosine(query, item["vector"]), item) for item in records), reverse=True)
        return [IndexHit(item["case_id"], item["crime_no"], score, item["narrative"], "test")
                for score, item in values[:limit]]


def _context():
    return AccessContext(9, 6, "CONSTABLE", (1,), (1,), frozenset(("retrieve_similar_cases",)), "rbac_masked", frozenset(), "own_actions")


def _case(case_id, crime_no, unit, text):
    return {"CaseMasterID": case_id, "CrimeNo": crime_no, "PoliceStationID": unit, "DistrictID": 1, "BriefFacts": text}


def test_matcher_returns_cited_original_excerpts():
    source = _case(1, "1" * 18, 1, "ಬೀಗ ಮುರಿದು ರಾತ್ರಿ ಬೈಕ್ ತೆಗೆದುಕೊಂಡರು।")
    candidate = _case(2, "2" * 18, 1, "Broken lock at night; motorcycle stolen.")
    result = MoMatcher(MemoryIndex(), DeterministicEmbeddingProvider()).similar_cases(source, [candidate], _context())
    assert result[0].matched_crime_no == "2" * 18
    assert result[0].source_excerpt != result[0].matched_excerpt


def test_matcher_excludes_other_station():
    source = _case(1, "1" * 18, 1, "phone stolen")
    candidate = _case(2, "2" * 18, 2, "phone stolen")
    assert MoMatcher(MemoryIndex(), DeterministicEmbeddingProvider()).similar_cases(source, [candidate], _context()) == []


def test_matcher_does_not_embed_inaccessible_narratives():
    class SpyProvider(DeterministicEmbeddingProvider):
        def __init__(self):
            super().__init__()
            self.seen = []

        def embed_documents(self, texts):
            self.seen.extend(texts)
            return super().embed_documents(texts)

    source = _case(1, "Ravi Kumar", 1, "source")
    visible = _case(2, "Ravi K", 1, "visible")
    hidden = _case(3, "Hidden Person", 2, "must never leave server")
    provider = SpyProvider()
    result = MoMatcher(MemoryIndex(), provider).similar_cases(source, [visible, hidden], _context())
    assert result
    assert provider.seen == ["source", "visible"]


def test_matcher_uses_persisted_vectors_without_embedding_candidates():
    class PersistedIndex(MemoryIndex):
        uses_persisted_vectors = True

        def search(self, query, records, limit, excluded_case_id):
            from functions.crime_query.mo_index import IndexHit
            candidate = records[0]
            return [IndexHit(
                candidate["CaseMasterID"], candidate["CrimeNo"], 0.9,
                candidate.get("BriefFacts", ""), "mo-v1",
            )]

    class SpyProvider(DeterministicEmbeddingProvider):
        def __init__(self):
            super().__init__()
            self.seen = []

        def embed_documents(self, texts):
            self.seen.extend(texts)
            return super().embed_documents(texts)

    source = _case(1, "1" * 18, 1, "source")
    candidate = _case(2, "2" * 18, 1, "candidate")
    provider = SpyProvider()
    result = MoMatcher(PersistedIndex(), provider).similar_cases(
        source, [candidate], _context()
    )

    assert result[0].matched_case_id == 2
    assert provider.seen == ["source"]
