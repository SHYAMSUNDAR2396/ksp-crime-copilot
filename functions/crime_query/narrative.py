"""Provider-neutral, RBAC-filtered retrieval over CaseMaster.BriefFacts."""
import re
from dataclasses import dataclass

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

try:
    from .access import require_capability
    from .mo_normalize import extract_mo_concepts, split_sentences
except ImportError:  # pragma: no cover
    from access import require_capability
    from mo_normalize import extract_mo_concepts, split_sentences


class NarrativeRetrievalError(Exception):
    """Raised when the configured narrative provider cannot be trusted."""


@dataclass(frozen=True)
class NarrativeHit:
    case_id: int
    crime_no: str
    excerpt: str
    score: float
    language_flags: tuple
    concepts: tuple
    index_version: str


def _tokens(value):
    return set(re.findall(r"[\w\u0c80-\u0cff]+", str(value or "").casefold()))


def _language_flags(value):
    flags = []
    if re.search(r"[\u0c80-\u0cff]", value or ""):
        flags.append("kn")
    if re.search(r"[A-Za-z]", value or ""):
        flags.append("en")
    return tuple(flags or ("unknown",))


def _visible(context, cases):
    result = []
    for case in cases or ():
        try:
            station = int(case.get("PoliceStationID"))
            district = int(case.get("DistrictID"))
        except (TypeError, ValueError):
            continue
        units = context.unit_ids
        districts = context.district_ids
        if units is not None and station not in tuple(int(value) for value in units):
            continue
        if districts is not None and district not in tuple(int(value) for value in districts):
            continue
        result.append(case)
    return result


class DeterministicNarrativeRetriever:
    """Offline fallback using explainable token/concept overlap only."""

    index_version = "brief-facts-token-v1"

    def search(self, question, cases, context, limit=5):
        require_capability(context, "retrieve_narratives")
        query_tokens = _tokens(question)
        if not query_tokens:
            raise ValueError("narrative question is required")
        query_concepts = set(extract_mo_concepts(question))
        scored = []
        for case in _visible(context, cases):
            narrative = str(case.get("BriefFacts") or "")
            if not narrative or not case.get("CrimeNo"):
                continue
            narrative_tokens = _tokens(narrative)
            token_score = len(query_tokens & narrative_tokens) / max(len(query_tokens), 1)
            concept_score = len(query_concepts & set(extract_mo_concepts(narrative)))
            score = min(1.0, token_score + min(0.5, concept_score * 0.25))
            if score <= 0:
                continue
            sentences = split_sentences(narrative)
            scored.append((
                score, int(case["CaseMasterID"]), case,
                sentences[0] if sentences else narrative,
            ))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            NarrativeHit(
                case_id=case_id,
                crime_no=case["CrimeNo"],
                excerpt=excerpt,
                score=round(score, 6),
                language_flags=_language_flags(excerpt),
                concepts=tuple(extract_mo_concepts(excerpt)),
                index_version=self.index_version,
            )
            for score, case_id, case, excerpt in scored[:max(1, min(int(limit), 10))]
        )


class QuickMLRagProvider:
    """Optional authenticated Catalyst RAG adapter.

    The response is accepted only when every returned case ID belongs to the
    already scope-filtered document set. If this endpoint is not configured,
    callers use ``DeterministicNarrativeRetriever`` for local/rehearsal work.
    """

    def __init__(self, endpoint, token, org_id, model="brief-facts-rag-v1",
                 timeout=10, transport=None):
        if not endpoint:
            raise ValueError("narrative endpoint is required")
        if timeout <= 0:
            raise ValueError("narrative timeout must be positive")
        self.endpoint = endpoint
        self.token = token
        self.org_id = org_id
        self.model = model
        self.timeout = timeout
        self.transport = transport or (requests.Session() if requests else None)
        if self.transport is None:
            raise NarrativeRetrievalError("HTTP transport is unavailable")
        self.index_version = model

    def search(self, question, cases, context, limit=5):
        require_capability(context, "retrieve_narratives")
        visible = _visible(context, cases)
        documents = [
            {"case_id": int(case["CaseMasterID"]), "crime_no": case["CrimeNo"],
             "text": str(case.get("BriefFacts") or "")}
            for case in visible if case.get("BriefFacts") and case.get("CrimeNo")
        ]
        allowed = {item["case_id"]: item for item in documents}
        payload = {"query": str(question), "documents": documents,
                   "top_k": min(max(int(limit), 1), 10), "model": self.model}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Zoho-oauthtoken " + self.token
        if self.org_id:
            headers["X-ZOHO-ORGID"] = str(self.org_id)
        try:
            response = self.transport.post(
                self.endpoint, json=payload, headers=headers, timeout=self.timeout,
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            body = response.json() if hasattr(response, "json") else response
        except Exception as exc:
            raise NarrativeRetrievalError("QuickML narrative request failed") from exc
        matches = body.get("matches") if isinstance(body, dict) else None
        if not isinstance(matches, list):
            raise NarrativeRetrievalError("QuickML narrative response is invalid")
        result = []
        for match in matches[:10]:
            try:
                case_id = int(match["case_id"])
                score = float(match.get("score", 0.0))
            except (KeyError, TypeError, ValueError):
                raise NarrativeRetrievalError("QuickML narrative match is invalid")
            document = allowed.get(case_id)
            if document is None:
                raise NarrativeRetrievalError("QuickML returned an out-of-scope case")
            excerpt = document["text"]
            result.append(NarrativeHit(
                case_id=case_id, crime_no=document["crime_no"], excerpt=excerpt,
                score=max(0.0, min(1.0, score)),
                language_flags=_language_flags(excerpt),
                concepts=tuple(extract_mo_concepts(excerpt)),
                index_version=self.index_version,
            ))
        return tuple(result)
