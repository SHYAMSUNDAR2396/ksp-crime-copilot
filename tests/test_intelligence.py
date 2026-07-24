import pytest

from functions.crime_query.access import AccessContext, AccessPolicyError
from functions.crime_query.graph import DerivedEdge
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


def test_network_view_accepts_active_persisted_projection():
    edges = (
        DerivedEdge("near", "case:1", "case:2", 0.9, ("FIR/1", "FIR/2")),
    )
    result = network_view(
        context(("view_graph",)), "case:1", cases(), hops=1,
        derived_edges=edges,
    )
    assert result["citations"] == ("FIR/1", "FIR/2")
    assert result["metrics"]["degree"]["case:1"] == 1


def test_analytics_view_returns_aggregate_warning():
    result = analytics_view(context(("query_structured_cases",)), cases())
    assert "warning" in result
    assert "prevention" in result
    assert all("FIR/" in citation for citation in result["citations"])


def test_prevention_repeat_offender_leads_are_command_scoped_and_cited():
    command = context(
        ("query_structured_cases", "view_graph"), bucket="SP_COMMAND"
    )
    rows = [
        dict(cases()[0], AccusedProfiles=(("Ravi Kumar", "30", "1"),)),
        dict(cases()[1], CaseMasterID=2, CrimeNo="FIR/2",
             AccusedProfiles=(("Ravi K", "31", "1"),)),
        dict(cases()[1], CaseMasterID=3, CrimeNo="FIR/3",
             AccusedProfiles=(("Another Person", "40", "2"),)),
        {"CaseMasterID": 4, "CrimeNo": "FIR/4", "PoliceStationID": 1,
         "DistrictID": 10, "CrimeRegisteredDate": "2026-06-04",
         "latitude": 14.0, "longitude": 77.0,
         "AccusedProfiles": (("Ravi Kumar", "30", "1"),)},
    ]

    result = analytics_view(command, rows)
    leads = result["prevention"]["repeat_offender_leads"]

    assert len(leads) == 1
    assert leads[0]["case_ids"] == (1, 2)
    assert leads[0]["citations"] == ("FIR/1", "FIR/2")
    assert "Ravi" in " ".join(leads[0]["names"])
    assert result["citations"] == ("FIR/1", "FIR/2", "FIR/3", "FIR/4")

    inspector = analytics_view(context(("query_structured_cases", "view_graph")), rows)
    assert inspector["prevention"]["repeat_offender_leads"] == ()
