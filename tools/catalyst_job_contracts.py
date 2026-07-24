"""Offline validator for Catalyst Job Scheduling and event contracts."""
import json
from pathlib import Path


EXPECTED = {
    ("POST", "/index", "scheduled"),
    ("POST", "/graph-projection", "scheduled"),
    ("POST", "/scan", "scheduled"),
    ("POST", "/scan", "completed_fir"),
}
PROTECTED_ROUTES = {("POST", "/index"), ("POST", "/graph-projection"), ("POST", "/scan")}
REQUIRED_ROOT = {"version", "function", "service_principal_map_env", "client_identity_field", "contracts"}


def _read(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError):
        return None, "manifest is invalid or unreadable JSON"


def validate_manifest(path):
    """Return a value-only report suitable for deployment preflight output."""
    manifest, error = _read(path)
    errors = []
    contracts = []
    if error:
        return {"ok": False, "errors": [error], "contracts": []}
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest must be an object"], "contracts": []}
    missing = REQUIRED_ROOT - set(manifest)
    if missing:
        errors.append("manifest is missing: {0}".format(sorted(missing)[0]))
    if manifest.get("function") != "silent_match":
        errors.append("manifest function must be silent_match")
    if manifest.get("client_identity_field") != "employee_id":
        errors.append("client identity field must be employee_id")
    raw_contracts = manifest.get("contracts")
    if not isinstance(raw_contracts, list) or not raw_contracts:
        errors.append("manifest contracts must be a non-empty list")
        raw_contracts = []
    seen = set()
    for index, contract in enumerate(raw_contracts):
        prefix = "contract {0}".format(index + 1)
        if not isinstance(contract, dict):
            errors.append(prefix + " must be an object")
            continue
        name = contract.get("name")
        method = contract.get("method")
        route = contract.get("route")
        trigger = contract.get("trigger")
        key = (method, route, trigger)
        if not isinstance(name, str) or not name.strip():
            errors.append(prefix + " needs a name")
        if name in seen:
            errors.append(prefix + " duplicates a contract name")
        seen.add(name)
        if key not in EXPECTED:
            errors.append(prefix + " is not an approved Catalyst job contract")
        if (method, route) not in PROTECTED_ROUTES:
            errors.append(prefix + " must use a protected job route")
        fields = contract.get("fields")
        if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
            errors.append(prefix + " fields must be a list of names")
            fields = []
        if "employee_id" in fields:
            errors.append(prefix + " must not expose employee_id in job fields")
        required = contract.get("required_fields")
        if not isinstance(required, list) or not set(required).issubset(set(fields)):
            errors.append(prefix + " required_fields must be contained in fields")
        retry = contract.get("retry")
        if not isinstance(retry, dict):
            errors.append(prefix + " needs a retry policy")
            retry = {}
        attempts = retry.get("max_attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 5:
            errors.append(prefix + " max_attempts must be between 1 and 5")
        if retry.get("malformed_payload") != "no_retry":
            errors.append(prefix + " malformed_payload must be no_retry")
        if contract.get("principal") != "service_or_command_user":
            errors.append(prefix + " principal must be service_or_command_user")
        contracts.append({"name": name, "method": method, "route": route,
                          "trigger": trigger, "fields": tuple(fields)})
    actual = {(item["method"], item["route"], item["trigger"]) for item in contracts}
    for expected in sorted(EXPECTED - actual):
        errors.append("missing approved contract: {0} {1} ({2})".format(*expected))
    return {"ok": not errors, "errors": errors, "contracts": contracts}


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="Validate Catalyst job contracts")
    parser.add_argument("path", nargs="?", default="docs/catalyst-job-contracts.json")
    args = parser.parse_args()
    report = validate_manifest(args.path)
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["ok"] else 1)
