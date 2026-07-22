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
