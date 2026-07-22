"""Thin request/response contracts for semantic search and alert actions."""
from dataclasses import asdict, is_dataclass

try:
    from .access import AccessPolicyError, can_act_on_alert, can_read_case_pair, require_capability
except ImportError:  # pragma: no cover
    from access import AccessPolicyError, can_act_on_alert, can_read_case_pair, require_capability


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
                 matcher, scanner, repository):
        self.caller_loader = caller_loader
        self.access_resolver = access_resolver
        self.case_loader = case_loader
        self.matcher = matcher
        self.scanner = scanner
        self.repository = repository

    def handle(self, method, path, payload=None):
        payload = payload or {}
        try:
            if method == "POST" and path == "/similar-cases":
                return 200, self.similar_cases(payload)
            if method == "POST" and path == "/scan":
                return 200, self.scan(payload)
            if method == "GET" and path.startswith("/alerts/"):
                return 200, self.alert_detail(int(path.rsplit("/", 1)[1]), payload)
            if method == "POST" and path.startswith("/alerts/") and path.endswith("/transition"):
                alert_id = int(path.split("/")[2])
                return 200, self.transition(alert_id, payload)
        except (AccessPolicyError, ValueError, KeyError) as exc:
            return 403 if isinstance(exc, AccessPolicyError) else 400, {"error": str(exc)}
        return 404, {"error": "route not found"}

    def _context(self, employee_id):
        caller = self.caller_loader(employee_id)
        if caller is None:
            raise AccessPolicyError("CAPABILITY_DENIED", "caller is not authorised")
        return self.access_resolver(caller)

    def similar_cases(self, payload):
        employee_id = payload["employee_id"]
        case_id = int(payload["case_master_id"])
        context = self._context(employee_id)
        require_capability(context, "retrieve_similar_cases")
        source = self.case_loader(case_id)
        if source is None:
            raise KeyError("case not found")
        matches = self.matcher.similar_cases(
            source, self.case_loader(case_id, candidates=True), context,
            limit=min(max(int(payload.get("limit", 10)), 1), 10),
        )
        visible = []
        for match in matches:
            candidate = self.case_loader(match.matched_case_id)
            if candidate and can_read_case_pair(context, source, candidate, "retrieve_similar_cases"):
                visible.append(_value(match))
        return {"case_master_id": case_id, "matches": visible, "partial": False}

    def scan(self, payload):
        context = self._context(payload["employee_id"])
        trigger = payload.get("trigger_source", "batch")
        require_capability(context, "run_live_scan" if trigger == "live" else "run_batch_scan")
        result = self.scanner.scan(
            date_window=payload.get("date_window"),
            anchor_case_id=payload.get("anchor_case_id"),
            trigger_source=trigger,
        )
        return _value(result)

    def alert_detail(self, alert_id, payload):
        context = self._context(payload["employee_id"])
        require_capability(context, "view_cross_jurisdiction_alerts")
        alert = self.repository.get_alert(alert_id)
        if not alert:
            raise KeyError("alert not found")
        left = self.case_loader(alert["AnchorCaseID"])
        right = self.case_loader(alert["MatchedCaseID"])
        if not can_read_case_pair(context, left, right, "view_cross_jurisdiction_alerts"):
            raise AccessPolicyError("SCOPE_DENIED", "alert cases are outside the caller's scope")
        return {"alert": _value(alert), "recipients": [], "actions": []}

    def transition(self, alert_id, payload):
        context = self._context(payload["employee_id"])
        alert = self.repository.get_alert(alert_id)
        if not alert:
            raise KeyError("alert not found")
        left = self.case_loader(alert["AnchorCaseID"])
        right = self.case_loader(alert["MatchedCaseID"])
        action = payload["to_status"]
        can_act_on_alert(context, {"anchor_case": left, "matched_case": right,
                                   "note": payload.get("note")}, action)
        updated = self.repository.append_action(
            alert_id, action, payload["note"], context.employee_id, payload.get("now", ""),
        )
        return {"alert": _value(updated), "action": {"action": action, "note": payload["note"]}}
