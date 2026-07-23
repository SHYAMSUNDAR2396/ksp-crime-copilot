"""Catalyst Advanced I/O adapter for the injected silent-match service.

Dependency construction belongs to the deployment bootstrap. Keeping the
request adapter injectable makes the HTTP contract fully testable offline and
prevents Catalyst SDK objects from leaking into the domain API.
"""


def handle_request(request, api):
    """Translate a Flask-like request into ``(body, status_code)``."""
    payload = request.get_json(silent=True) or {}
    status, body = api.handle(request.method, request.path, payload)
    return body, status


def create_handler(api):
    """Create a Catalyst/Flask-compatible handler around an already-built API."""
    from flask import jsonify, make_response

    def handler(request):
        body, status = handle_request(request, api)
        return make_response(jsonify(body), status)

    return handler


def handler(request):
    import zcatalyst_sdk
    from flask import jsonify, make_response

    try:
        from ..crime_query import auth
        from .runtime import build_api
    except ImportError:
        from functions.crime_query import auth
        from runtime import build_api

    app = zcatalyst_sdk.initialize()
    api = build_api(app)
    employee_id = auth.authenticated_employee_id(app, api.caller_loader)
    raw_payload = request.get_json(silent=True)
    payload = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    payload["employee_id"] = employee_id
    status, body = api.handle(request.method, request.path, payload)
    return make_response(jsonify(body), status)
