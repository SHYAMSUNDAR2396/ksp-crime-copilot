import pytest

from functions.crime_query.access import (
    AccessPolicyError,
    bucket_for_rank,
    can_act_on_alert,
    can_read_case,
    can_read_case_pair,
    resolve_access_context,
    require_capability,
)
from functions.crime_query.rbac import Caller


class FakeDB:
    def units_in_district(self, district_id):
        return {1: [1, 2, 3, 4], 2: [5, 6, 7, 8]}[district_id]


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.mark.parametrize(
    "hierarchy,bucket",
    [
        (1, "DGP_STATEWIDE"),
        (2, "DGP_STATEWIDE"),
        (3, "SP_COMMAND"),
        (4, "INSPECTOR"),
        (5, "SI_IO"),
        (6, "CONSTABLE"),
        (99, "CONSTABLE"),
    ],
)
def test_bucket_for_rank(hierarchy, bucket):
    assert bucket_for_rank(hierarchy) == bucket


def test_sp_command_has_district_scans_but_constable_is_read_only(fake_db):
    sp = resolve_access_context(
        Caller(employee_id=1, unit_id=1, district_id=1, rank_hierarchy=3), fake_db
    )
    constable = resolve_access_context(
        Caller(employee_id=2, unit_id=7, district_id=2, rank_hierarchy=6), fake_db
    )
    assert sp.access_bucket == "SP_COMMAND"
    assert sp.has("run_batch_scan")
    assert sp.has("run_live_scan")
    assert constable.has("query_structured_cases")
    assert not constable.has("view_graph")
    assert not constable.has("view_cross_jurisdiction_alerts")
    assert not constable.has("run_live_scan")


def test_capability_vocabulary_matches_approved_design(fake_db):
    approved = {
        "query_structured_cases",
        "retrieve_narratives",
        "retrieve_similar_cases",
        "view_graph",
        "view_cross_jurisdiction_alerts",
        "review_alerts",
        "dispose_alerts",
        "run_batch_scan",
        "run_live_scan",
        "view_deadline_risk",
        "export_conversation",
        "view_audit",
    }
    observed = set()
    for hierarchy in (1, 3, 4, 5, 6):
        context = resolve_access_context(
            Caller(
                employee_id=100 + hierarchy,
                unit_id=1,
                district_id=1,
                rank_hierarchy=hierarchy,
            ),
            fake_db,
        )
        observed.update(context.capabilities)

    assert observed == approved
    assert "query_narrative_cases" not in observed
    assert "query_similar_cases" not in observed


def test_statewide_context_uses_unbounded_scope(fake_db):
    context = resolve_access_context(
        Caller(employee_id=3, unit_id=1, district_id=1, rank_hierarchy=1), fake_db
    )
    assert context.unit_ids is None
    assert context.district_ids is None
    assert can_read_case(context, {"PoliceStationID": 999, "DistrictID": 999})


def test_case_scope_and_pair_scope(fake_db):
    context = resolve_access_context(
        Caller(employee_id=4, unit_id=7, district_id=2, rank_hierarchy=6), fake_db
    )
    visible = {"PoliceStationID": 7, "DistrictID": 2}
    hidden = {"PoliceStationID": 8, "DistrictID": 2}
    assert can_read_case(context, visible)
    assert not can_read_case(context, hidden)
    assert can_read_case_pair(context, visible, visible)
    assert not can_read_case_pair(context, visible, hidden)


def test_case_scope_normalizes_catalyst_string_identifiers(fake_db):
    context = resolve_access_context(
        Caller(employee_id=41, unit_id=7, district_id=2, rank_hierarchy=6), fake_db
    )

    assert can_read_case(
        context, {"PoliceStationID": "7", "DistrictID": "2"}
    )
    assert not can_read_case(
        context, {"PoliceStationID": "8", "DistrictID": "2"}
    )


def test_access_context_scopes_are_immutable(fake_db):
    context = resolve_access_context(
        Caller(employee_id=14, unit_id=1, district_id=1, rank_hierarchy=4), fake_db
    )
    assert isinstance(context.unit_ids, tuple)
    assert isinstance(context.district_ids, tuple)
    assert isinstance(context.capabilities, frozenset)
    assert isinstance(context.alert_actions, frozenset)


def test_missing_case_scope_identifiers_fail_closed(fake_db):
    statewide = resolve_access_context(
        Caller(employee_id=15, unit_id=1, district_id=1, rank_hierarchy=1), fake_db
    )
    district = resolve_access_context(
        Caller(employee_id=16, unit_id=1, district_id=1, rank_hierarchy=4), fake_db
    )

    assert not can_read_case(statewide, {"PoliceStationID": 999})
    assert not can_read_case(statewide, {"DistrictID": 999})
    assert not can_read_case(district, {"PoliceStationID": 1})
    assert not can_read_case(district, {"DistrictID": 1})


def test_unknown_capability_is_default_denied(fake_db):
    context = resolve_access_context(
        Caller(employee_id=5, unit_id=7, district_id=2, rank_hierarchy=6), fake_db
    )
    with pytest.raises(AccessPolicyError) as error:
        require_capability(context, "invented_capability")
    assert error.value.code == "CAPABILITY_DENIED"


def test_alert_review_and_disposition_are_separate(fake_db):
    context = resolve_access_context(
        Caller(employee_id=6, unit_id=1, district_id=1, rank_hierarchy=4), fake_db
    )
    alert = {
        "anchor_case": {"PoliceStationID": 1, "DistrictID": 1},
        "matched_case": {"PoliceStationID": 2, "DistrictID": 1},
        "note": "Reviewed against the case file.",
    }
    assert can_act_on_alert(context, alert, "review")
    assert can_act_on_alert(context, alert, "Linked")
    with pytest.raises(AccessPolicyError) as error:
        can_act_on_alert(context, dict(alert, note=""), "Dismissed")
    assert error.value.code == "ACTION_DENIED"


def test_alert_review_denies_missing_cases_without_identifier_leak(fake_db):
    context = resolve_access_context(
        Caller(employee_id=17, unit_id=1, district_id=1, rank_hierarchy=4), fake_db
    )
    alert = {
        "anchor_case": {
            "CrimeNo": "112/2026",
            "CaseMasterID": 88,
            "PoliceStationID": 1,
            "DistrictID": 1,
        },
        "note": "Ready for review.",
    }

    with pytest.raises(AccessPolicyError) as error:
        can_act_on_alert(context, alert, "review")

    message = str(error.value)
    assert error.value.code == "SCOPE_DENIED"
    assert "112/2026" not in message
    assert "88" not in message
    assert "CrimeNo" not in message


def test_si_io_may_review_visible_unassigned_alert_but_not_dispose_it(fake_db):
    context = resolve_access_context(
        Caller(employee_id=18, unit_id=1, district_id=1, rank_hierarchy=5), fake_db
    )
    alert = {
        "anchor_case": {
            "CrimeNo": "113/2026",
            "PoliceStationID": 1,
            "DistrictID": 1,
            "PolicePersonID": 99,
        },
        "matched_case": {
            "CrimeNo": "114/2026",
            "PoliceStationID": 2,
            "DistrictID": 1,
            "PolicePersonID": 100,
        },
        "note": "Checked the district records.",
    }

    assert can_act_on_alert(context, alert, "review")
    with pytest.raises(AccessPolicyError) as error:
        can_act_on_alert(context, alert, "Linked")

    message = str(error.value)
    assert error.value.code == "ACTION_DENIED"
    assert "113/2026" not in message
    assert "114/2026" not in message
    assert "CrimeNo" not in message


def test_si_io_may_dispose_alert_when_cases_are_assigned_to_caller(fake_db):
    context = resolve_access_context(
        Caller(employee_id=19, unit_id=1, district_id=1, rank_hierarchy=5), fake_db
    )
    alert = {
        "anchor_case": {
            "PoliceStationID": 1,
            "DistrictID": 1,
            "assigned_employee_id": 19,
        },
        "matched_case": {
            "PoliceStationID": 2,
            "DistrictID": 1,
            "IOID": 19,
        },
        "note": "Same investigation officer confirmed the linkage.",
    }

    assert can_act_on_alert(context, alert, "Dismissed")


def test_alert_assignment_normalizes_catalyst_string_identifiers(fake_db):
    context = resolve_access_context(
        Caller(employee_id=20, unit_id=1, district_id=1, rank_hierarchy=5), fake_db
    )
    alert = {
        "anchor_case": {
            "PoliceStationID": "1", "DistrictID": "1",
            "PolicePersonID": "20",
        },
        "matched_case": {
            "PoliceStationID": "2", "DistrictID": "1",
            "IOID": "20",
        },
        "note": "Assigned investigation confirmed.",
    }

    assert can_act_on_alert(context, alert, "Linked")
