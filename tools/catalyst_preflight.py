"""Safe, offline preflight for the two Catalyst Advanced I/O functions.

The preflight never calls Catalyst or prints configuration values.  Without
``--require-live`` it validates repository artifacts and reports account-side
gates as warnings; with it, every live gate becomes a failure suitable for CI
or a deployment checklist.
"""

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

try:
    from functions.crime_query.catalog import TABLES
except ImportError:  # pragma: no cover - standalone Catalyst packaging
    TABLES = {}


CANONICAL_TABLE_NAMES = (
    "CaseMaster", "ComplainantDetails", "ActSectionAssociation", "Victim",
    "Accused", "ArrestSurrender", "Act", "Section", "CrimeHeadActSection",
    "CrimeHead", "CrimeSubHead", "CasteMaster", "ReligionMaster",
    "OccupationMaster", "CaseStatusMaster", "Court", "District", "State",
    "Unit", "UnitType", "Rank", "Designation", "Employee", "CaseCategory",
    "GravityOffence", "ChargesheetDetails",
)
if not TABLES:
    TABLES = {name: {} for name in CANONICAL_TABLE_NAMES}


INDEX_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
REQUIRED_OPERATIONAL_TABLES = (
    "SilentMatchAlert", "MoEmbeddingRecord", "MoEmbeddingJobState",
)
REQUIRED_GRAPH_TABLES = (
    "PersonNode", "PersonMember", "EdgePersonCase", "EdgeCaseEmployee",
    "EdgeCaseSection", "EdgeCaseNear", "GraphProjectionState",
)
LIVE_CONFIG_KEYS = {
    "crime_query": (
        "QUICKML_ENDPOINT", "QUICKML_MODEL", "QUICKML_ORG_ID",
        "SMARTBROWZ_ENDPOINT", "QUICKML_RAG_ENDPOINT", "KSP_AUTH_EMPLOYEE_MAP",
    ),
    "silent_match": (
        "QUICKML_ORG_ID", "QUICKML_EMBEDDINGS_ENDPOINT",
        "QUICKML_EMBEDDINGS_MODEL", "KSP_AUTH_EMPLOYEE_MAP",
    ),
}


def _item(name, ok, detail, live_gate=False):
    return {"name": name, "ok": bool(ok), "detail": detail, "live_gate": live_gate}


def _read_json(path):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError) as exc:
        return None, "invalid or unreadable JSON"


def _https_url(value):
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def _auth_mapping(value):
    try:
        mapping = json.loads(str(value))
    except (TypeError, ValueError):
        return False
    if not isinstance(mapping, dict) or not mapping:
        return False
    for employee_id in mapping.values():
        try:
            if int(employee_id) < 1:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _security_rule(rules, function_name, path, methods):
    entries = rules.get("advancedio", {}).get(function_name, [])
    for entry in entries:
        rule = entry.get(path)
        if isinstance(rule, dict):
            return (
                rule.get("authentication") == "required"
                and set(rule.get("methods", ())) >= set(methods)
            )
    return False


def run_preflight(root, require_live=False, catalyst_available=None):
    """Return a value-only readiness report for ``root``.

    ``catalyst_available`` is injectable so tests do not depend on a developer
    machine's PATH.  The returned report contains no endpoint, org ID, mapping,
    token, or other configuration value.
    """
    root = Path(root)
    checks, warnings, failures = [], [], []

    def check(name, ok, detail, live_gate=False):
        result = _item(name, ok, detail, live_gate)
        if ok:
            checks.append(result)
        elif live_gate and not require_live:
            warnings.append(result)
        else:
            failures.append(result)

    config_paths = {
        "crime_query": root / "functions/crime_query/catalyst-config.json",
        "silent_match": root / "functions/silent_match/catalyst-config.json",
    }
    configs = {}
    for name, path in config_paths.items():
        config, error = _read_json(path)
        check("{}_config".format(name), error is None, "valid JSON" if error is None else error)
        configs[name] = config or {}
        deployment = (config or {}).get("deployment", {})
        execution = (config or {}).get("execution", {})
        check("{}_deployment".format(name), (
            deployment.get("name") == name
            and deployment.get("stack") == "python_3_9"
            and deployment.get("type") == "advancedio"
            and execution.get("main") == "main.py"
        ), "Python 3.9 Advanced I/O entrypoint")

    crime_env = configs["crime_query"].get("deployment", {}).get("env_variables", {})
    silent_env = configs["silent_match"].get("deployment", {}).get("env_variables", {})
    for name, env in (("crime_query", crime_env), ("silent_match", silent_env)):
        check("{}_env_shape".format(name), isinstance(env, dict), "environment map")
        for key in LIVE_CONFIG_KEYS[name]:
            value = env.get(key) if isinstance(env, dict) else None
            if key.endswith("ENDPOINT"):
                valid = _https_url(value) if value else False
                detail = "HTTPS endpoint configured" if valid else "HTTPS endpoint is required"
            elif key == "KSP_AUTH_EMPLOYEE_MAP":
                valid = _auth_mapping(value)
                detail = "non-empty principal mapping" if valid else "non-empty valid principal mapping is required"
            else:
                valid = bool(str(value or "").strip())
                detail = "configured" if valid else "value is required"
            check("{}: {}".format(name, key), valid, detail, live_gate=True)

    check(
        "glm_model",
        str(crime_env.get("QUICKML_MODEL", "")).strip() == "crm-di-glm47b_30b_it",
        "GLM-4.7 deployment selected",
    )
    index_version = str(silent_env.get("QUICKML_EMBEDDINGS_INDEX_VERSION", "")).strip()
    check("embedding_index_version", bool(INDEX_VERSION_RE.fullmatch(index_version)),
          "safe version identifier")
    try:
        lookback = int(silent_env.get("KSP_SILENT_MATCH_LOOKBACK_DAYS", ""))
    except (TypeError, ValueError):
        lookback = 0
    check("silent_match_lookback", lookback > 0, "positive historical lookback")

    for key, env in (("crime_query", crime_env), ("silent_match", silent_env)):
        embedded_secret = any(
            marker in str(name).upper() and bool(str(value).strip())
            for name, value in (env.items() if isinstance(env, dict) else ())
            for marker in ("TOKEN", "API_KEY", "PASSWORD", "SECRET")
        )
        check("{}_no_embedded_secrets".format(key), not embedded_secret,
              "no token or secret value in deployment config")

    schema_path = root / "docs/schema-ddl.sql"
    schema_text = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    check("schema_ddl", bool(schema_text), "schema DDL present")
    for table in TABLES:
        check("schema_table_{}".format(table), '"{}"'.format(table) in schema_text,
              "authoritative schema table present")
    check("schema_table_AuditLog", '"AuditLog"' in schema_text,
          "audit table present")

    operational_path = root / "docs/silent-match-alerts-ddl.sql"
    operational_text = operational_path.read_text(encoding="utf-8") if operational_path.exists() else ""
    check("operational_ddl", bool(operational_text), "operational DDL present")
    for table in REQUIRED_OPERATIONAL_TABLES:
        check("operational_table_{}".format(table), table in operational_text,
              "operational table present")

    graph_path = root / "docs/derived-graph-ddl.sql"
    graph_text = graph_path.read_text(encoding="utf-8") if graph_path.exists() else ""
    check("derived_graph_ddl", bool(graph_text), "derived graph DDL present")
    for table in REQUIRED_GRAPH_TABLES:
        check("derived_graph_table_{}".format(table), table in graph_text,
              "derived graph table present")

    rules, error = _read_json(root / "docs/catalyst-security-rules.json")
    check("security_rules_json", error is None, "valid security rules" if error is None else error)
    rules = rules or {}
    check("crime_query_auth_rule", _security_rule(rules, "crime_query", ".*", ("POST",)),
          "all crime_query POST requests authenticated")
    for path, methods in (
        ("/similar-cases", ("POST",)), ("/alerts", ("GET",)),
        ("/alerts/.*", ("GET", "POST")), ("/scan", ("POST",)),
        ("/index", ("POST",)), ("/graph-projection", ("POST",)),
    ):
        check("silent_match_rule_{}".format(path.strip("/")),
              _security_rule(rules, "silent_match", path, methods),
              "authenticated route")

    if catalyst_available is None:
        catalyst_available = shutil.which("catalyst") is not None
    check("catalyst_cli", catalyst_available, "Catalyst CLI available", live_gate=True)

    live_gate_missing = [
        item for item in warnings + failures if item["live_gate"]
    ]
    return {
        "ok": not failures,
        "live_ready": not failures and not live_gate_missing,
        "checks": checks,
        "warnings": warnings,
        "failures": failures,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate KSP Catalyst deployment readiness")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--require-live", action="store_true")
    args = parser.parse_args(argv)
    report = run_preflight(args.root, require_live=args.require_live)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
