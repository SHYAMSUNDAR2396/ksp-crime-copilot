import pytest

from functions.crime_query.access import AccessContext, AccessPolicyError
from functions.crime_query.narrative import (
    DeterministicNarrativeRetriever,
    NarrativeRetrievalError,
    QuickMLRagProvider,
)


def _context():
    return AccessContext(
        9, 6, "CONSTABLE", (1,), (10,),
        frozenset({"retrieve_narratives"}), "rbac_masked", frozenset(), "own_actions",
    )


def _cases():
    return [
        {"CaseMasterID": 1, "CrimeNo": "1" * 18, "PoliceStationID": 1,
         "DistrictID": 10, "BriefFacts": "Broken lock and motorcycle stolen."},
        {"CaseMasterID": 2, "CrimeNo": "2" * 18, "PoliceStationID": 2,
         "DistrictID": 10, "BriefFacts": "A phone was lost near the market."},
    ]


def test_deterministic_retriever_returns_original_cited_excerpt_in_scope():
    hits = DeterministicNarrativeRetriever().search(
        "broken lock motorcycle", _cases(), _context()
    )

    assert [hit.case_id for hit in hits] == [1]
    assert hits[0].crime_no == "1" * 18
    assert hits[0].excerpt == "Broken lock and motorcycle stolen."
    assert hits[0].index_version == "brief-facts-token-v1"


def test_deterministic_retriever_does_not_return_other_station():
    hits = DeterministicNarrativeRetriever().search(
        "phone market", _cases(), _context()
    )
    assert hits == ()


class _Response:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        return None


class _Transport:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.body)


def test_quickml_rag_provider_rejects_out_of_scope_case():
    provider = QuickMLRagProvider(
        "https://rag.example", "token", "org",
        transport=_Transport({"matches": [{"case_id": 2, "score": 0.9}]}),
    )
    with pytest.raises(NarrativeRetrievalError, match="out-of-scope"):
        provider.search("phone", _cases()[:1], _context())


def test_narrative_retrieval_requires_capability():
    context = AccessContext(9, 6, "CONSTABLE", (1,), (10,), frozenset(),
                            "rbac_masked", frozenset(), "own_actions")
    with pytest.raises(AccessPolicyError):
        DeterministicNarrativeRetriever().search("theft", _cases(), context)
