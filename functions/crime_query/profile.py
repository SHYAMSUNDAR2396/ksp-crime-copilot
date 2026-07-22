"""Cited decision-support profiles assembled from linked case evidence."""
from collections import Counter

try:
    from .mo_normalize import extract_mo_concepts
except ImportError:  # pragma: no cover
    from mo_normalize import extract_mo_concepts


def behavioral_profile(cases):
    """Summarize common patterns; never produce a person risk score."""
    rows = list(cases or ())
    sections = Counter()
    time_bands = Counter()
    concepts = Counter()
    citations = []
    for row in rows:
        for section in row.get("SectionCodes", ()) or ():
            sections[str(section)] += 1
        incident = str(row.get("IncidentFromDate", ""))
        hour = None
        try:
            hour = int(incident.split(" ")[1].split(":")[0])
        except (IndexError, ValueError):
            pass
        if hour is not None:
            time_bands["night" if hour < 6 or hour >= 20 else "day"] += 1
        for concept in extract_mo_concepts(row.get("BriefFacts", "")):
            concepts[concept] += 1
        if row.get("CrimeNo") and row["CrimeNo"] not in citations:
            citations.append(row["CrimeNo"])
    return {
        "case_count": len(rows),
        "common_sections": tuple(sections.most_common()),
        "time_bands": tuple(time_bands.most_common()),
        "mo_concepts": tuple(concepts.most_common()),
        "citations": tuple(citations),
        "limitations": (
            "Decision-support summary only; it is not a person risk score.",
        ),
    }
