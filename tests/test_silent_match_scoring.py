import datetime as dt

from functions.crime_query.silent_match_scoring import score_candidate


def _case(case_id, name, unit=1, sections=("IPC:379",), lat=12.9716, lon=77.5946):
    return {
        "CaseMasterID": case_id,
        "CrimeNo": str(case_id).zfill(18),
        "PoliceStationID": unit,
        "DistrictID": 1,
        "AccusedName": name,
        "AgeYear": 30,
        "GenderID": 1,
        "CrimeSubHeadID": 6,
        "SectionCodes": sections,
        "CrimeRegisteredDate": dt.date(2026, 6, 1),
        "latitude": lat,
        "longitude": lon,
        "BriefFacts": "two wheeler theft near market",
    }


def test_same_person_requires_identity_and_scores_transparently():
    result = score_candidate(_case(1, "Ravi Kumar"), _case(2, "Ravi K", unit=2))
    assert result.alert_type == "possible_same_person"
    assert result.score >= 60
    assert any(name == "person_name_similarity" for name, _ in result.evidence)
    assert result.persistable is True


def test_semantic_similarity_alone_cannot_create_alert():
    result = score_candidate(
        dict(_case(1, "Ravi Kumar"), CrimeSubHeadID=5, CrimeRegisteredDate=dt.date(2024, 1, 1), latitude=15.0, longitude=75.0),
        dict(_case(2, "Anita Rao", unit=2, sections=("IPC:302",)), CrimeSubHeadID=4),
        semantic_signal={"similarity": 0.99},
    )
    assert result.persistable is False
    assert result.score <= 10


def test_score_bands_and_semantic_contribution_are_bounded():
    result = score_candidate(
        _case(1, "Ravi Kumar"), _case(2, "Ravi K"), semantic_signal={"similarity": 1.0}
    )
    assert result.confidence_band in ("Medium", "High")
    assert sum(value for key, value in result.evidence if key == "mo_similarity") <= 10


def test_semantic_index_version_is_preserved_in_score_evidence():
    result = score_candidate(
        _case(1, "Ravi Kumar"), _case(2, "Ravi K"),
        semantic_signal={"similarity": 0.9, "index_version": "mo-v2"},
    )
    assert result.index_version == "mo-v2"


def test_later_accused_profile_can_supply_identity_evidence():
    anchor = _case(1, "Anitha Kumar")
    candidate = _case(2, "Lakshmi Bhat", unit=2)
    anchor["AccusedProfiles"] = (("Anitha Kumar", "32", "1"), ("Ravi Kumar", "31", "1"))
    candidate["AccusedProfiles"] = (("Lakshmi Bhat", "54", "2"), ("Ravi K", "31", "1"))
    result = score_candidate(anchor, candidate)
    assert result.alert_type == "possible_same_person"
    assert result.persistable is True
