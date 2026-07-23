"""Thin request/response contracts for semantic search and alert actions."""
from dataclasses import asdict, is_dataclass

try:
    from .access import ACTION_DENIED, CAPABILITY_DENIED, AccessPolicyError, can_act_on_alert, can_read_case_pair, require_capability
    from .db import DBError
    from .mo_embeddings import EmbeddingError
except ImportError:  # pragma: no cover
    from access import ACTION_DENIED, CAPABILITY_DENIED, AccessPolicyError, can_act_on_alert, can_read_case_pair, require_capability
    from db import DBError
    from mo_embeddings import EmbeddingError


def _value(value):
    if is_dataclass(value):
        return {key: _value(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    return value


class SilentMatchAPI:
    def __init__(self, caller_loader, access_resolver, case_loader,
                 matcher, scanner, repository, scanner_factory=None,
                 index_job_factory=None, graph_projection_job_factory=None):
        self.caller_loader = caller_loader
        self.access_resolver = access_resolver
        self.case_loader = case_loader
        self.matcher = matcher
        self.scanner = scanner
        self.repository = repository
        self.scanner_factory = scanner_factory
        self.index_job_factory = index_job_factory
        self.graph_projection_job_factory = graph_projection_job_factory

    def handle(self, method, path, payload=None):
        payload = payload or {}
        try:
            if method == "POST" and path == "/similar-cases":
                return 200, self.similar_cases(payload)
            if method == "POST" and path == "/scan":
                return 200, self.scan(payload)
            if method == "POST" and path == "/index":
                return 200, self.index(payload)
            if method == "POST" and path == "/graph-projection":
                return 200, self.graph_projection(payload)
            if method == "GET" and path == "/alerts":
                return 200, self.list_alerts(payload)
            if method == "GET" and path.startswith("/alerts/"):
                return 200, self.alert_detail(int(path.rsplit("/", 1)[1]), payload)
            if method == "POST" and path.startswith("/alerts/") and path.endswith("/transition"):
                alert_id = int(path.split("/")[2])
                return 200, self.transition(alert_id, payload)
        except (AccessPolicyError, ValueError, KeyError, TypeError) as exc:
            return 403 if isinstance(exc, AccessPolicyError) else 400, {"error": str(exc)}
        except (DBError, EmbeddingError):
            # Provider and persistence details are internal diagnostics. Keep
            # the HTTP contract bounded and do not expose endpoints, SQL, or
            # provider response bodies to the browser.
            return 503, {"error": "silent-match service is temporarily unavailable"}
        return 404, {"error": "route not found"}

    def _context(self, employee_id):
        if (
            employee_id is None
            or isinstance(employee_id, bool)
            or not isinstance(employee_id, int)
            or employee_id < 1
        ):
            raise AccessPolicyError(CAPABILITY_DENIED, "caller is not authorised")
        try:
            caller = self.caller_loader(employee_id)
        except (TypeError, ValueError):
            raise AccessPolicyError(CAPABILITY_DENIED, "caller is not authorised")
        if caller is None:
            raise AccessPolicyError("CAPABILITY_DENIED", "caller is not authorised")
        return self.access_resolver(caller)

    def similar_cases(self, payload):
        employee_id = payload.get("employee_id")
        case_id = int(payload["case_master_id"])
        context = self._context(employee_id)
        require_capability(context, "retrieve_similar_cases")
        if hasattr(self.case_loader, "load"):
            anchors, candidates = self.case_loader.load(anchor_case_id=case_id)
            source = anchors[0] if anchors else None
        else:
            source = self.case_loader(case_id)
            candidates = self.case_loader(case_id, candidates=True)
        if source is None:
            raise KeyError("case not found")
        matches = self.matcher.similar_cases(
            source, candidates, context,
            limit=min(max(int(payload.get("limit", 10)), 1), 10),
        )
        visible = []
        for match in matches:
            candidate = self.case_loader(match.matched_case_id)
            if candidate and can_read_case_pair(context, source, candidate, "retrieve_similar_cases"):
                visible.append(_value(match))
        return {"case_master_id": case_id, "matches": visible, "partial": False}

    def scan(self, payload):
        context = self._context(payload.get("employee_id"))
        trigger = payload.get("trigger_source", "batch")
        if trigger not in ("batch", "live"):
            raise ValueError("unsupported trigger source")
        require_capability(context, "run_live_scan" if trigger == "live" else "run_batch_scan")
        scanner = self.scanner_factory(context) if self.scanner_factory else self.scanner
        result = scanner.scan(
            date_window=payload.get("date_window"),
            anchor_case_id=payload.get("anchor_case_id"),
            trigger_source=trigger,
        )
        return _value(result)

    def index(self, payload):
        context = self._context(payload.get("employee_id"))
        require_capability(context, "run_batch_scan")
        if self.index_job_factory is None:
            raise ValueError("index job is not configured")
        version = str(payload.get("index_version") or "").strip()
        if not version or len(version) > 80 or not all(
            character.isalnum() or character in "._-" for character in version
        ):
            raise ValueError("a valid index version is required")
        job = self.index_job_factory(payload)
        result = job.run(version)
        return _value(result)

    def graph_projection(self, payload):
        context = self._context(payload.get("employee_id"))
        require_capability(context, "run_batch_scan")
        if self.graph_projection_job_factory is None:
            raise ValueError("graph projection job is not configured")
        version = str(payload.get("projection_version") or "").strip()
        if not version or len(version) > 80 or not all(
            character.isalnum() or character in "._-" for character in version
        ):
            raise ValueError("a valid projection version is required")
        job = self.graph_projection_job_factory(payload)
        return _value(job.run())

    def alert_detail(self, alert_id, payload):
        context = self._context(payload.get("employee_id"))
        require_capability(context, "view_cross_jurisdiction_alerts")
        alert = self.repository.get_alert(alert_id)
        if not alert:
            raise KeyError("alert not found")
        left = self.case_loader(alert["AnchorCaseID"])
        right = self.case_loader(alert["MatchedCaseID"])
        if left is None or right is None or not can_read_case_pair(
            context, left, right, "view_cross_jurisdiction_alerts"
        ):
            raise AccessPolicyError("SCOPE_DENIED", "alert cases are outside the caller's scope")
        recipients = getattr(self.repository, "recipients_for", lambda _alert_id: ())
        actions = getattr(self.repository, "actions_for", lambda _alert_id: ())
        return {
            "alert": _value(alert),
            "recipients": _value(recipients(alert_id) or ()),
            "actions": _value(actions(alert_id) or ()),
        }

    def list_alerts(self, payload):
        context = self._context(payload.get("employee_id"))
        require_capability(context, "view_cross_jurisdiction_alerts")
        status = payload.get("status")
        if status is not None and not isinstance(status, str):
            raise ValueError("unsupported alert status")
        if status is not None and status not in {"New", "Seen", "Reviewing", "Linked", "Dismissed"}:
            raise ValueError("unsupported alert status")
        rows = self.repository.list_alerts(status) if status is not None else self.repository.list_alerts()
        visible = []
        for alert in rows or ():
            left = self.case_loader(alert.get("AnchorCaseID"))
            right = self.case_loader(alert.get("MatchedCaseID"))
            if left is None or right is None:
                continue
            if can_read_case_pair(context, left, right, "view_cross_jurisdiction_alerts"):
                visible.append(_value(alert))
        return {"alerts": visible, "partial": False}

    def transition(self, alert_id, payload):
        context = self._context(payload.get("employee_id"))
        alert = self.repository.get_alert(alert_id)
        if not alert:
            raise KeyError("alert not found")
        left = self.case_loader(alert["AnchorCaseID"])
        right = self.case_loader(alert["MatchedCaseID"])
        requested_status = payload["to_status"]
        if not isinstance(requested_status, str):
            raise ValueError("unsupported alert transition")
        action = "review" if requested_status in ("review", "Reviewing") else requested_status
        current_status = alert.get("Status", "New")
        allowed_transitions = {
            "New": {"review", "Linked", "Dismissed"},
            "Reviewing": {"Linked", "Dismissed"},
        }
        if action not in allowed_transitions.get(current_status, set()):
            raise AccessPolicyError(ACTION_DENIED, "alert transition is not allowed")
        can_act_on_alert(context, {"anchor_case": left, "matched_case": right,
                                   "note": payload.get("note")}, action)
        updated = self.repository.append_action(
            alert_id, action, payload.get("note", ""), context.employee_id, payload.get("now", ""),
        )
        return {"alert": _value(updated), "action": {"action": action, "note": payload.get("note", "")}}
