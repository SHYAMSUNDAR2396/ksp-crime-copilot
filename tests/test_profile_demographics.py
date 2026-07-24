import pytest

from functions.crime_query.access import AccessContext, AccessPolicyError
from functions.crime_query.demographics import demographic_aggregate
from functions.crime_query.profile import behavioral_profile


def context(rank=4):
    return AccessContext(9, rank, "INSPECTOR", (1,), (10,),
                         frozenset({"query_structured_cases"}), "rbac_masked",
                         frozenset(), "district")


def test_behavioral_profile_is_cited_and_has_no_risk_score():
    result = behavioral_profile([{
        "CrimeNo": "FIR/1", "SectionCodes": ("379",),
        "IncidentFromDate": "2026-06-01 22:00:00",
        "BriefFacts": "Two-wheeler parked near house found missing.",
    }])
    assert result["citations"] == ("FIR/1",)
    assert result["time_bands"] == (("night", 1),)
    assert "risk_score" not in result


def test_sensitive_demographic_is_aggregate_only_for_command_roles():
    result = demographic_aggregate(context(3), [
        {"CasteID": 1}, {"CasteID": 1}, {"CasteID": 2},
    ], "CasteID")
    assert result["aggregate_only"] is True
    assert result["groups"] == (("1", 2), ("2", 1))
    with pytest.raises(AccessPolicyError) as error:
        demographic_aggregate(context(4), [{"ReligionID": 1}], "ReligionID")
    assert error.value.code == "SENSITIVE_FIELD_DENIED"
