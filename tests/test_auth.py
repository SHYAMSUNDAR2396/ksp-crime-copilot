from functions.crime_query.auth import (
    authenticated_employee_id,
    authenticated_principal,
    employee_id_from_user,
    principal_allowed_for_route,
)


def test_explicit_identity_mapping_returns_employee_id():
    user = {"user_id": "catalyst-42", "email_id": "officer@example.test"}
    assert employee_id_from_user(user, {"catalyst-42": 9}) == 9


def test_unmapped_authenticated_user_is_rejected():
    user = {"user_id": "catalyst-42", "email_id": "officer@example.test"}
    assert employee_id_from_user(user, {}) is None


def test_client_employee_id_is_not_an_identity_source():
    user = {"user_id": "catalyst-42"}
    assert employee_id_from_user(user, {"client-payload": 97}) is None


def test_authenticated_principal_is_checked_against_employee_scope(monkeypatch):
    class Authentication:
        def get_current_user(self):
            return {"user_id": "catalyst-42"}

    class App:
        def authentication(self):
            return Authentication()

    monkeypatch.setenv("KSP_AUTH_EMPLOYEE_MAP", '{"catalyst-42": 9}')
    assert authenticated_employee_id(App(), lambda employee_id: object()) == 9


def test_unknown_authenticated_principal_fails_closed(monkeypatch):
    class Authentication:
        def get_current_user(self):
            return {"user_id": "catalyst-42"}

    class App:
        def authentication(self):
            return Authentication()

    monkeypatch.setenv("KSP_AUTH_EMPLOYEE_MAP", '{"catalyst-42": 9}')
    assert authenticated_employee_id(App(), lambda employee_id: None) is None


def test_user_management_accessor_is_preferred_when_available(monkeypatch):
    calls = []

    class Authentication:
        def get_current_user(self):
            return {"user_id": "catalyst-42"}

    class App:
        def user_management(self):
            calls.append("user_management")
            return Authentication()

        def authentication(self):
            calls.append("deprecated_authentication")
            raise AssertionError("deprecated accessor must not be used")

    monkeypatch.setenv("KSP_AUTH_EMPLOYEE_MAP", '{"catalyst-42": 9}')
    assert authenticated_employee_id(App(), lambda employee_id: object()) == 9
    assert calls == ["user_management"]


def test_service_principal_uses_explicit_service_mapping(monkeypatch):
    class Authentication:
        def get_current_user(self):
            return {"user_id": "catalyst-cron"}

    class App:
        def authentication(self):
            return Authentication()

    monkeypatch.setenv("KSP_AUTH_EMPLOYEE_MAP", '{"catalyst-cron": 9}')
    monkeypatch.setenv("KSP_AUTH_SERVICE_MAP", '{"catalyst-cron": 9001}')
    principal = authenticated_principal(App(), lambda employee_id: object())

    assert principal.kind == "service"
    assert principal.subject == "catalyst-cron"
    assert principal.employee_id == 9001


def test_service_principal_is_restricted_to_job_routes():
    assert principal_allowed_for_route("service", "POST", "/index") is True
    assert principal_allowed_for_route("service", "POST", "/scan") is True
    assert principal_allowed_for_route("service", "POST", "/graph-projection") is True
    assert principal_allowed_for_route("service", "GET", "/alerts") is False
    assert principal_allowed_for_route("service", "POST", "/alerts/1/transition") is False
    assert principal_allowed_for_route("user", "GET", "/alerts") is True
