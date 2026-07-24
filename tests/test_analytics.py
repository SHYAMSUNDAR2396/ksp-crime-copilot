from functions.crime_query.analytics import (
    AnalyticsProviderError,
    QuickMLAnalyticsProvider,
    dbscan_hotspots,
    early_warning,
    forecast_next_period,
    prevention_brief,
    series_warnings,
    trend_rollup,
)
import pytest


def test_trend_rollup_and_hotspot_preserve_crime_citations():
    rows = [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "CrimeRegisteredDate": "2026-06-01", "PoliceStationID": 1, "CrimeMinorHeadID": 6, "latitude": 12.97, "longitude": 77.59},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "CrimeRegisteredDate": "2026-06-02", "PoliceStationID": 1, "CrimeMinorHeadID": 6, "latitude": 12.9701, "longitude": 77.5901},
        {"CaseMasterID": 3, "CrimeNo": "FIR/3", "CrimeRegisteredDate": "2026-06-03", "PoliceStationID": 1, "CrimeMinorHeadID": 6, "latitude": 12.9702, "longitude": 77.5902},
    ]
    assert trend_rollup(rows)[0].count == 3
    hotspot = dbscan_hotspots(rows, eps_km=0.5, min_samples=2)[0]
    assert hotspot.citations == ("FIR/1", "FIR/2", "FIR/3")


def test_dbscan_uses_spatial_candidates_instead_of_all_pairs(monkeypatch):
    rows = [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "latitude": 12.97, "longitude": 77.59},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "latitude": 12.9701, "longitude": 77.5901},
        {"CaseMasterID": 3, "CrimeNo": "FIR/3", "latitude": 12.9702, "longitude": 77.5902},
    ]
    rows.extend(
        {"CaseMasterID": index, "CrimeNo": "FIR/{}".format(index),
         "latitude": 10 + index * 0.02, "longitude": 77.0}
        for index in range(4, 104)
    )
    from functions.crime_query import analytics

    calls = []
    original = analytics._distance_km

    def distance(left, right):
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(analytics, "_distance_km", distance)
    hotspots = dbscan_hotspots(rows, eps_km=0.5, min_samples=2)

    assert hotspots[0].citations == ("FIR/1", "FIR/2", "FIR/3")
    assert len(calls) < 1000


def test_warning_is_aggregate_only_and_prevention_brief_has_no_person_score():
    assert forecast_next_period([2, 2, 4])["forecast"] == pytest.approx(8 / 3, rel=1e-3)
    warning = early_warning([2, 2, 5], threshold_ratio=1.1, window=1)
    brief = prevention_brief(warning, ())
    assert warning["warning"] is True
    assert warning["scope"] == "station-by-crime-type aggregate"
    assert "risk score" in brief["claims"][1]


def test_series_warnings_do_not_mix_stations_or_crime_types():
    rows = [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "CrimeRegisteredDate": "2026-01-01",
         "PoliceStationID": 1, "CrimeMinorHeadID": 6},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "CrimeRegisteredDate": "2026-02-01",
         "PoliceStationID": 1, "CrimeMinorHeadID": 6},
        {"CaseMasterID": 3, "CrimeNo": "FIR/3", "CrimeRegisteredDate": "2026-03-01",
         "PoliceStationID": 1, "CrimeMinorHeadID": 6},
        {"CaseMasterID": 4, "CrimeNo": "FIR/4", "CrimeRegisteredDate": "2026-01-01",
         "PoliceStationID": 2, "CrimeMinorHeadID": 9},
        {"CaseMasterID": 5, "CrimeNo": "FIR/5", "CrimeRegisteredDate": "2026-02-01",
         "PoliceStationID": 2, "CrimeMinorHeadID": 9},
    ]
    warnings = series_warnings(trend_rollup(rows), threshold_ratio=1.1)

    assert {(row["station_id"], row["crime_subhead_id"]) for row in warnings} == {
        (1, 6), (2, 9),
    }
    first = next(row for row in warnings if row["station_id"] == 1)
    assert first["observations"] == 3
    assert first["warning"] is False


def test_series_warnings_use_validated_provider_output_per_series():
    class Provider:
        def __init__(self):
            self.calls = []

        def forecast(self, counts, window, threshold_ratio, station_id, crime_subhead_id):
            self.calls.append((tuple(counts), station_id, crime_subhead_id))
            return {"baseline": 2, "forecast": 4, "observations": len(counts),
                    "provider": "quickml-analytics-v1"}

    provider = Provider()
    warnings = series_warnings(
        trend_rollup([
            {"CrimeRegisteredDate": "2026-01-01", "PoliceStationID": 1,
             "CrimeMinorHeadID": 7, "CrimeNo": "FIR/1"},
            {"CrimeRegisteredDate": "2026-02-01", "PoliceStationID": 2,
             "CrimeMinorHeadID": 7, "CrimeNo": "FIR/2"},
        ]), provider=provider, threshold_ratio=1.5,
    )

    assert len(provider.calls) == 2
    assert warnings[0]["provider"] == "quickml-analytics-v1"
    assert warnings[0]["warning"] is True


def test_provider_failure_falls_back_without_leaking_error_details():
    class Provider:
        def forecast(self, *args, **kwargs):
            raise AnalyticsProviderError("secret endpoint response")

    warning = series_warnings(
        trend_rollup([
            {"CrimeRegisteredDate": "2026-01-01", "PoliceStationID": 1,
             "CrimeMinorHeadID": 7, "CrimeNo": "FIR/1"},
        ]), provider=Provider(),
    )[0]

    assert warning["provider"] == "deterministic_moving_average"
    assert warning["provider_fallback"] is True
    assert "secret" not in repr(warning)


def test_quickml_analytics_provider_sends_aggregate_series_and_validates_response():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"baseline": 3, "forecast": 5, "observations": 4,
                              "provider": "quickml-analytics-v1"}}

    def transport(endpoint, **kwargs):
        assert endpoint == "https://quickml.example/analytics"
        calls.append(kwargs)
        return Response()

    provider = QuickMLAnalyticsProvider(
        "https://quickml.example/analytics", "token", "org-1", transport=transport,
    )
    result = provider.forecast([1, 2, 3, 4], 3, 1.25, 7, 9)

    assert result["forecast"] == 5
    assert calls[0]["headers"]["Authorization"] == "Zoho-oauthtoken token"
    assert calls[0]["json"]["series_key"] == {
        "station_id": 7, "crime_subhead_id": 9,
    }
    assert calls[0]["json"]["counts"] == [1, 2, 3, 4]
