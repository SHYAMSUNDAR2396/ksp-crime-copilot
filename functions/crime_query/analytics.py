"""Deterministic geographic and temporal crime analytics.

These functions are decision-support summaries over counts and coordinates.
They do not consume names, caste, religion, or other person attributes.
"""
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass

import requests


class AnalyticsProviderError(Exception):
    """Raised when a configured forecast provider cannot return safe output."""


class QuickMLAnalyticsProvider:
    """Validated adapter for an account-provisioned QuickML analytics endpoint.

    The endpoint receives aggregate time-series counts only. Its response is
    treated as untrusted provider data and must contain non-negative finite
    baseline/forecast values before it can influence an early-warning card.
    """

    def __init__(self, endpoint, token, org_id, model="crime-trend-v1",
                 timeout=10.0, transport=None):
        self.endpoint = str(endpoint or "").strip()
        self.token = str(token or "")
        self.org_id = str(org_id or "")
        self.model = str(model or "crime-trend-v1")
        self.timeout = float(timeout)
        self.transport = transport or requests.post
        if not self.endpoint or not self.token or not self.org_id:
            raise ValueError("analytics provider credentials are required")
        if not self.endpoint.startswith("https://") or self.timeout <= 0:
            raise ValueError("analytics provider configuration is invalid")

    def forecast(self, counts, window, threshold_ratio, station_id, crime_subhead_id):
        values = []
        for value in counts:
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise AnalyticsProviderError("provider input is invalid")
            if not math.isfinite(number) or number < 0:
                raise AnalyticsProviderError("provider input is invalid")
            values.append(int(number) if number.is_integer() else number)
        try:
            response = self.transport(
                self.endpoint,
                headers={
                    "Authorization": "Zoho-oauthtoken {0}".format(self.token),
                    "X-Catalyst-Org-Id": self.org_id,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "counts": values,
                    "window": int(window),
                    "threshold_ratio": float(threshold_ratio),
                    "series_key": {
                        "station_id": station_id,
                        "crime_subhead_id": crime_subhead_id,
                    },
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            body = response.json()
            result = body.get("data", body) if isinstance(body, dict) else None
            if not isinstance(result, dict):
                raise AnalyticsProviderError("provider response is invalid")
            baseline = float(result["baseline"])
            forecast = float(result["forecast"])
            observations = int(result.get("observations", len(values)))
            provider = str(result.get("provider") or self.model).strip()
        except AnalyticsProviderError:
            raise
        except (requests.RequestException, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise AnalyticsProviderError("provider request failed") from exc
        if (
            not math.isfinite(baseline) or not math.isfinite(forecast)
            or baseline < 0 or forecast < 0 or observations < 1
            or not provider or len(provider) > 80
        ):
            raise AnalyticsProviderError("provider response is invalid")
        return {
            "baseline": round(baseline, 3),
            "forecast": round(forecast, 3),
            "observations": observations,
            "provider": provider,
        }


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


def _spatial_neighbors(points, eps_km):
    """Return exact DBSCAN neighbours using a bounded geographic grid.

    Karnataka-scale coordinates are indexed in latitude/longitude cells
    roughly one epsilon wide. The longitude search spans two cells because a
    degree of longitude is shorter than a degree of latitude away from the
    equator. Exact haversine distance remains the final predicate, so the grid
    only removes impossible pairs and does not change clustering semantics.
    """
    if eps_km < 0:
        return {index: () for index in range(len(points))}
    cell_degrees = max(float(eps_km) / 111.0, 1e-9)
    buckets = defaultdict(list)
    cells = []
    for index, (latitude, longitude) in enumerate(points):
        cell = (int(math.floor(latitude / cell_degrees)),
                int(math.floor(longitude / cell_degrees)))
        cells.append(cell)
        buckets[cell].append(index)

    result = {}
    for index, (latitude, longitude) in enumerate(points):
        row, column = cells[index]
        candidates = set()
        for row_delta in (-1, 0, 1):
            for column_delta in (-2, -1, 0, 1, 2):
                candidates.update(buckets.get((row + row_delta, column + column_delta), ()))
        result[index] = tuple(
            other for other in sorted(candidates)
            if _distance_km((latitude, longitude), points[other]) <= eps_km
        )
    return result


def dbscan_hotspots(cases, eps_km=0.5, min_samples=3):
    rows = [row for row in cases or () if row.get("latitude") is not None and row.get("longitude") is not None]
    points = [(float(row["latitude"]), float(row["longitude"])) for row in rows]
    neighbors = _spatial_neighbors(points, eps_km)
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
    if isinstance(window, bool) or not isinstance(window, int) or window < 1:
        raise ValueError("forecast window must be a positive integer")
    values = [float(value) for value in counts if value is not None]
    if not values:
        return {"baseline": 0.0, "forecast": 0.0, "observations": 0}
    sample = values[-window:]
    baseline = sum(values) / len(values)
    forecast = sum(sample) / len(sample)
    return {"baseline": round(baseline, 3), "forecast": round(forecast, 3),
            "observations": len(values)}


def early_warning(counts, threshold_ratio=1.25, window=3):
    if isinstance(threshold_ratio, bool) or float(threshold_ratio) <= 0:
        raise ValueError("warning threshold must be positive")
    forecast = forecast_next_period(counts, window)
    baseline = forecast["baseline"]
    ratio = (forecast["forecast"] / baseline) if baseline else 0.0
    return {
        **forecast,
        "ratio": round(ratio, 3),
        "warning": bool(baseline and ratio >= threshold_ratio),
        "scope": "station-by-crime-type aggregate",
        "provider": "deterministic_moving_average",
    }


def series_warnings(trends, threshold_ratio=1.25, window=3, provider=None):
    """Forecast each station/crime series independently.

    A warning for one station and crime type must never be inflated by trend
    points belonging to another series.  Citations remain attached to the
    same series so an operator can inspect the source cases.
    """
    groups = defaultdict(lambda: {"counts": [], "citations": []})
    for point in trends or ():
        key = (point.station_id, point.crime_subhead_id)
        groups[key]["counts"].append(point.count)
        for citation in point.citations:
            if citation and citation not in groups[key]["citations"]:
                groups[key]["citations"].append(citation)
    result = []
    for (station_id, crime_subhead_id), values in sorted(groups.items(), key=lambda item: str(item[0])):
        if provider is None:
            warning = early_warning(values["counts"], threshold_ratio, window)
        else:
            try:
                warning = provider.forecast(
                    values["counts"], window, threshold_ratio,
                    station_id, crime_subhead_id,
                )
                baseline = warning["baseline"]
                forecast = warning["forecast"]
                warning = {
                    **warning,
                    "ratio": round((forecast / baseline) if baseline else 0.0, 3),
                    "warning": bool(baseline and (forecast / baseline) >= threshold_ratio),
                    "scope": "station-by-crime-type aggregate",
                }
            except (AnalyticsProviderError, ValueError, TypeError, KeyError, AttributeError):
                warning = early_warning(values["counts"], threshold_ratio, window)
                warning["provider_fallback"] = True
        result.append({
            "station_id": station_id,
            "crime_subhead_id": crime_subhead_id,
            **warning,
            "citations": tuple(values["citations"]),
        })
    return tuple(result)


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
