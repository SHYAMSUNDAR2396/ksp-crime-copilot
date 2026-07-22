"""Deterministic geographic and temporal crime analytics.

These functions are decision-support summaries over counts and coordinates.
They do not consume names, caste, religion, or other person attributes.
"""
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class TrendPoint:
    period: str
    station_id: object
    crime_subhead_id: object
    count: int
    citations: tuple


@dataclass(frozen=True)
class Hotspot:
    cluster_id: int
    case_ids: tuple
    latitude: float
    longitude: float
    radius_km: float
    citations: tuple


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _month(value):
    date = _date(value)
    return date.strftime("%Y-%m") if date else None


def trend_rollup(cases):
    groups = defaultdict(list)
    for row in cases or ():
        period = _month(row.get("CrimeRegisteredDate"))
        if period is None:
            continue
        key = (period, row.get("PoliceStationID"), row.get("CrimeMinorHeadID", row.get("CrimeSubHeadID")))
        groups[key].append(row.get("CrimeNo"))
    return tuple(
        TrendPoint(period, station, subhead, len(values), tuple(value for value in values if value))
        for (period, station, subhead), values in sorted(groups.items())
    )


def _distance_km(left, right):
    p1, p2 = math.radians(left[0]), math.radians(right[0])
    dp, dl = math.radians(right[0] - left[0]), math.radians(right[1] - left[1])
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def dbscan_hotspots(cases, eps_km=0.5, min_samples=3):
    rows = [row for row in cases or () if row.get("latitude") is not None and row.get("longitude") is not None]
    points = [(float(row["latitude"]), float(row["longitude"])) for row in rows]
    neighbors = {
        index: tuple(other for other, point in enumerate(points)
                     if _distance_km(points[index], point) <= eps_km)
        for index in range(len(points))
    }
    visited, clusters = set(), []
    for start in range(len(rows)):
        if start in visited or len(neighbors[start]) < min_samples:
            continue
        visited.add(start)
        cluster = set([start])
        frontier = list(neighbors[start])
        while frontier:
            current = frontier.pop()
            if current not in visited:
                visited.add(current)
                if len(neighbors[current]) >= min_samples:
                    frontier.extend(item for item in neighbors[current] if item not in visited)
            cluster.add(current)
        clusters.append(cluster)
    result = []
    for cluster_id, cluster in enumerate(clusters, 1):
        selected = [rows[index] for index in sorted(cluster)]
        lat = sum(float(row["latitude"]) for row in selected) / len(selected)
        lon = sum(float(row["longitude"]) for row in selected) / len(selected)
        radius = max(_distance_km((lat, lon), (float(row["latitude"]), float(row["longitude"]))) for row in selected)
        result.append(Hotspot(
            cluster_id, tuple(row["CaseMasterID"] for row in selected), round(lat, 6),
            round(lon, 6), round(radius, 3),
            tuple(row["CrimeNo"] for row in selected if row.get("CrimeNo")),
        ))
    return tuple(result)


def forecast_next_period(counts, window=3):
    """Return a mean baseline and next-period estimate from aggregate counts."""
    values = [float(value) for value in counts if value is not None]
    if not values:
        return {"baseline": 0.0, "forecast": 0.0, "observations": 0}
    sample = values[-window:]
    baseline = sum(values) / len(values)
    forecast = sum(sample) / len(sample)
    return {"baseline": round(baseline, 3), "forecast": round(forecast, 3),
            "observations": len(values)}


def early_warning(counts, threshold_ratio=1.25, window=3):
    forecast = forecast_next_period(counts, window)
    baseline = forecast["baseline"]
    ratio = (forecast["forecast"] / baseline) if baseline else 0.0
    return {
        **forecast,
        "ratio": round(ratio, 3),
        "warning": bool(baseline and ratio >= threshold_ratio),
        "scope": "station-by-crime-type aggregate",
    }


def prevention_brief(warning, hotspots, network_nodes=()):
    """Compose a bounded command summary without naming a person as risky."""
    if not warning.get("warning"):
        return {"status": "no_alert", "claims": (), "citations": ()}
    citations = []
    for hotspot in hotspots:
        citations.extend(value for value in hotspot.citations if value not in citations)
    claims = (
        "The station-by-crime-type count is above its historical aggregate baseline.",
        "Hotspot evidence is geographic and temporal; it is not a person risk score.",
    )
    if network_nodes:
        claims += ("Related case-network nodes are provided as investigation leads, not predictions.",)
    return {"status": "early_warning", "claims": claims, "citations": tuple(citations)}
