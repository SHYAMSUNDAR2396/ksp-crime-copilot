"""Catalyst principal-to-police-employee identity boundary.

The browser may send a display hint, but it cannot choose the employee used
for authorization. Catalyst authenticates the principal; deployment-owned
mapping then resolves that principal to the existing Employee row.
"""
import json
import os


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


def configured_identity_mapping(environ=None):
    raw = (environ or os.environ).get("KSP_AUTH_EMPLOYEE_MAP", "")
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return mapping if isinstance(mapping, dict) else {}


def authenticated_employee_id(app, caller_loader, environ=None):
    """Resolve the authenticated Catalyst user to a valid Employee row.

    A missing auth service, missing mapping, malformed mapping, or unknown
    Employee all fail closed. ``caller_loader`` is deliberately injected so
    this boundary is testable without Catalyst SDK objects.
    """
    try:
        authentication = app.authentication()
        user = authentication.get_current_user()
    except Exception:
        return None
    employee_id = employee_id_from_user(user, configured_identity_mapping(environ))
    if employee_id is None:
        return None
    try:
        return employee_id if caller_loader(employee_id) is not None else None
    except Exception:
        return None
