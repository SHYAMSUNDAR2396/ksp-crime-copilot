import pytest

from functions.crime_query.access import AccessContext, AccessPolicyError
from functions.crime_query.intelligence import analytics_view, network_view


def context(capabilities, bucket="INSPECTOR"):
    return AccessContext(9, 4, bucket, (1,), (10,), frozenset(capabilities),
                         "rbac_masked", frozenset(), "district")


def cases():
    return [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "PoliceStationID": 1, "DistrictID": 10,
         "CrimeRegisteredDate": "2026-06-01", "latitude": 12.97, "longitude": 77.59},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "PoliceStationID": 1, "DistrictID": 10,
         "CrimeRegisteredDate": "2026-06-02", "latitude": 12.9701, "longitude": 77.5901},
    ]


def test_network_view_is_cited_and_capability_gated():
    rows = [{"CaseMasterID": 1, "CrimeNo": "FIR/1", "PoliceStationID": 1, "DistrictID": 10,
             "AccusedName": "Ravi Kumar", "AgeYear": 30, "GenderID": 1},
            {"CaseMasterID": 2, "CrimeNo": "FIR/2", "PoliceStationID": 1, "DistrictID": 10,
             "AccusedName": "Ravi Kumar", "AgeYear": 30, "GenderID": 1}]
    result = network_view(context(("view_graph",)), "case:1", cases(), rows, hops=2)
    assert result["citations"] == ("FIR/1", "FIR/2")
    with pytest.raises(AccessPolicyError):
        network_view(context(()), "case:1", cases())


def test_analytics_view_returns_aggregate_warning():
    result = analytics_view(context(("query_structured_cases",)), cases())
    assert "warning" in result
    assert all("FIR/" in citation for citation in result["citations"])
