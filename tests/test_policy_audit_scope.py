from functions.crime_query.access import AccessContext
from functions.crime_query.policy_audit import filter_audit_rows, scope_safe_export


def context(capabilities=("export_conversation",), visibility="own_actions"):
    return AccessContext(
        9, 4, "INSPECTOR", (1,), (10,), frozenset(capabilities),
        "rbac_masked", frozenset(), visibility,
    )


def test_export_requires_exact_session_owner_and_removes_audio():
    denied = scope_safe_export(context(), "other", 10, [{"answer": "secret"}])
    assert denied.code == "SCOPE_DENIED"
    assert denied.rows == ()
    allowed = scope_safe_export(context(), "own", 9, [{"answer": "safe", "audio": "raw"}])
    assert allowed.code == "OK"
    assert allowed.rows == ({"answer": "safe"},)


def test_audit_visibility_is_fixed_by_context():
    rows = [
        {"EmployeeID": 9, "DistrictID": 10},
        {"EmployeeID": 10, "DistrictID": 11},
    ]
    assert filter_audit_rows(context(), rows) == (rows[0],)
    district = filter_audit_rows(context(visibility="district"), rows)
    assert district == (rows[0],)
    statewide = filter_audit_rows(context(visibility="statewide_summary"), rows)
    assert statewide == tuple(rows)
