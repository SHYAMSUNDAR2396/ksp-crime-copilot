"""Pure, explainable scorer for cross-jurisdiction silent matches."""
import datetime as dt
import math
import re

try:
    from .silent_match_models import ScoreResult
except ImportError:
    from silent_match_models import ScoreResult


def _text(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _name_similarity(left, right):
    a, b = _text(left), _text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    shorter, longer = sorted((a, b), key=len)
    if shorter in longer:
        return 0.85
    overlap = len(set(a) & set(b)) / max(len(set(a) | set(b)), 1)
    return round(overlap, 3)


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _distance_km(anchor, candidate):
    try:
        lat1, lon1 = float(anchor["latitude"]), float(anchor["longitude"])
        lat2, lon2 = float(candidate["latitude"]), float(candidate["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def score_candidate(anchor, candidate, semantic_signal=None):
    evidence = []
    identity = _name_similarity(anchor.get("AccusedName"), candidate.get("AccusedName"))
    if identity >= 0.8:
        evidence.append(("person_name_similarity", identity))
    if anchor.get("CrimeSubHeadID") == candidate.get("CrimeSubHeadID"):
        evidence.append(("shared_crime_subhead", 15))
    sections = set(anchor.get("SectionCodes", ())) & set(candidate.get("SectionCodes", ()))
    if sections:
        evidence.append(("shared_section", 15))
    left_date, right_date = _date(anchor.get("CrimeRegisteredDate")), _date(candidate.get("CrimeRegisteredDate"))
    if left_date and right_date and abs((left_date - right_date).days) <= 30:
        evidence.append(("date_proximity", 10))
    distance = _distance_km(anchor, candidate)
    if distance is not None and distance <= 5:
        evidence.append(("geo_proximity", 10))
    if isinstance(semantic_signal, dict):
        raw_similarity = semantic_signal.get("similarity", 0.0)
    else:
        raw_similarity = getattr(semantic_signal, "similarity", 0.0)
    similarity = float(raw_similarity or 0.0)
    if similarity > 0:
        evidence.append(("mo_similarity", min(10.0, max(0.0, similarity * 10.0))))

    score = 0
    if identity >= 0.8:
        score += 50
    for key in ("shared_crime_subhead", "shared_section", "date_proximity", "geo_proximity"):
        score += int(next((value for name, value in evidence if name == key), 0))
    score += int(next((value for name, value in evidence if name == "mo_similarity"), 0))
    alert_type = "possible_same_person" if identity >= 0.8 else "possible_linked_pattern"
    band = "High" if score >= 80 else "Medium" if score >= 60 else "Low"
    persistable = score >= 60 and (identity >= 0.8 or any(name in {"shared_section", "shared_crime_subhead"} for name, _ in evidence))
    limitation = "Semantic similarity is bounded evidence and cannot create an alert alone."
    return ScoreResult(alert_type, score, band, tuple(evidence), persistable, limitation)
