"""RBAC-filtered semantic MO retrieval."""
try:
    from .access import can_read_case_pair, require_capability
    from .mo_models import SemanticMatch
    from .mo_normalize import extract_mo_concepts, split_sentences
except ImportError:
    from access import can_read_case_pair, require_capability
    from mo_models import SemanticMatch
    from mo_normalize import extract_mo_concepts, split_sentences


class MoMatcher:
    def __init__(self, index, provider):
        self.index = index
        self.provider = provider

    def similar_cases(self, source_case, candidates, access_context, limit=10):
        require_capability(access_context, "retrieve_similar_cases")
        source_text = source_case.get("BriefFacts", "")
        texts = [source_text] + [case.get("BriefFacts", "") for case in candidates]
        vectors = self.provider.embed_documents(texts)
        searchable = []
        for case, vector in zip(candidates, vectors[1:]):
            if not can_read_case_pair(access_context, source_case, case, "retrieve_similar_cases"):
                continue
            searchable.append({"case_id": case["CaseMasterID"], "crime_no": case["CrimeNo"],
                               "vector": vector, "narrative": case.get("BriefFacts", "")})
        hits = self.index.search(vectors[0], searchable, limit, source_case["CaseMasterID"])
        source_concepts = set(extract_mo_concepts(source_text))
        results = []
        for hit in hits:
            matched = next(case for case in candidates if int(case["CaseMasterID"]) == hit.case_id)
            shared = tuple(sorted(source_concepts & set(extract_mo_concepts(matched.get("BriefFacts", "")))))
            results.append(SemanticMatch(
                source_case_id=int(source_case["CaseMasterID"]), matched_case_id=hit.case_id,
                source_crime_no=source_case["CrimeNo"], matched_crime_no=hit.crime_no,
                similarity=hit.similarity,
                similarity_band="High" if hit.similarity >= 0.8 else "Medium" if hit.similarity >= 0.5 else "Low",
                shared_concepts=shared,
                source_excerpt=split_sentences(source_text)[0] if split_sentences(source_text) else "",
                matched_excerpt=split_sentences(matched.get("BriefFacts", ""))[0] if split_sentences(matched.get("BriefFacts", "")) else "",
                index_version=hit.index_version,
            ))
        return results
