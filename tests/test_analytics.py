from functions.crime_query.analytics import (
    dbscan_hotspots,
    early_warning,
    forecast_next_period,
    prevention_brief,
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


def test_warning_is_aggregate_only_and_prevention_brief_has_no_person_score():
    assert forecast_next_period([2, 2, 4])["forecast"] == pytest.approx(8 / 3, rel=1e-3)
    warning = early_warning([2, 2, 5], threshold_ratio=1.1, window=1)
    brief = prevention_brief(warning, ())
    assert warning["warning"] is True
    assert warning["scope"] == "station-by-crime-type aggregate"
    assert "risk score" in brief["claims"][1]
