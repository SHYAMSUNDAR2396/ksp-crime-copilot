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
        "anchor_case": {"PoliceStationID": 1},
        "matched_case": {"PoliceStationID": 2},
        "note": "Reviewed against the case file.",
    }
    assert can_act_on_alert(context, alert, "review")
    assert can_act_on_alert(context, alert, "Linked")
    with pytest.raises(AccessPolicyError) as error:
        can_act_on_alert(context, dict(alert, note=""), "Dismissed")
    assert error.value.code == "ACTION_DENIED"
