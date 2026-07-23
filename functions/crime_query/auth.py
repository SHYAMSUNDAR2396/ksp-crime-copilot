"""Catalyst principal-to-police-employee identity boundary.

The browser may send a display hint, but it cannot choose the employee used
for authorization. Catalyst authenticates the principal; deployment-owned
mapping then resolves that principal to the existing Employee row.
"""
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Trusted Catalyst identity and its policy-scope Employee row."""

    kind: str
    subject: str
    employee_id: int


def _field(user, *names):
    if isinstance(user, dict):
        for name in names:
            if user.get(name) not in (None, ""):
                return user[name]
        return None
    for name in names:
        value = getattr(user, name, None)
        if value not in (None, ""):
            return value
    return None


def employee_id_from_user(user, mapping):
    """Return the mapped EmployeeID, or ``None`` on any identity mismatch."""
    if not isinstance(mapping, dict):
        return None
    for value in (
        _field(user, "user_id", "userId"),
        _field(user, "zuid", "ZUID"),
        _field(user, "email_id", "email", "emailId"),
    ):
        if value is None:
            continue
        mapped = mapping.get(str(value))
        try:
            employee_id = int(mapped)
        except (TypeError, ValueError):
            continue
        if employee_id > 0:
            return employee_id
    return None


def _subjects_from_user(user):
    return tuple(
        str(value) for value in (
            _field(user, "user_id", "userId"),
            _field(user, "zuid", "ZUID"),
            _field(user, "email_id", "email", "emailId"),
        ) if value is not None
    )


def _mapped_employee_id(subject, mapping):
    try:
        employee_id = int(mapping.get(subject))
    except (AttributeError, TypeError, ValueError):
        return None
    return employee_id if employee_id > 0 else None


def principal_from_user(user, employee_mapping, service_mapping=None):
    """Resolve a user or explicitly configured service principal.

    Service mappings are separate from human mappings so a scheduled trigger
    cannot accidentally inherit a browser identity.  The mapped Employee row
    supplies policy scope; the ``kind`` remains available to route guards.
    """
    service_mapping = service_mapping or {}
    for subject in _subjects_from_user(user):
        employee_id = _mapped_employee_id(subject, service_mapping)
        if employee_id is not None:
            return AuthenticatedPrincipal("service", subject, employee_id)
    for subject in _subjects_from_user(user):
        employee_id = _mapped_employee_id(subject, employee_mapping)
        if employee_id is not None:
            return AuthenticatedPrincipal("user", subject, employee_id)
    return None


def configured_identity_mapping(environ=None):
    raw = (environ or os.environ).get("KSP_AUTH_EMPLOYEE_MAP", "")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return mapping if isinstance(mapping, dict) else {}


def configured_service_mapping(environ=None):
    raw = (environ or os.environ).get("KSP_AUTH_SERVICE_MAP", "")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return mapping if isinstance(mapping, dict) else {}


def principal_allowed_for_route(kind, method, path):
    """Keep service identities on bounded maintenance/job routes only."""
    if kind == "service":
        return (method, path) in {
            ("POST", "/index"),
            ("POST", "/scan"),
            ("POST", "/graph-projection"),
        }
    return kind == "user"


def authenticated_principal(app, caller_loader, environ=None):
    """Resolve the authenticated Catalyst principal, failing closed."""
    try:
        authentication = app.authentication()
        user = authentication.get_current_user()
    except Exception:
        return None
    principal = principal_from_user(
        user,
        configured_identity_mapping(environ),
        configured_service_mapping(environ),
    )
    if principal is None:
        return None
    try:
        return principal if caller_loader(principal.employee_id) is not None else None
    except Exception:
        return None


def authenticated_employee_id(app, caller_loader, environ=None):
    """Resolve the authenticated Catalyst user to a valid Employee row.

    A missing auth service, missing mapping, malformed mapping, or unknown
    Employee all fail closed. ``caller_loader`` is deliberately injected so
    this boundary is testable without Catalyst SDK objects.
    """
    principal = authenticated_principal(app, caller_loader, environ)
    return principal.employee_id if principal is not None else None
