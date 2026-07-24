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
import sqlite3
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

try:
    from functions.crime_query.catalog import TABLES, sqlite_ddl
except ImportError:  # pragma: no cover - standalone Catalyst packaging
    TABLES = {}
    sqlite_ddl = None

try:
    from .catalyst_job_contracts import validate_manifest
except ImportError:  # pragma: no cover - direct script execution
    from catalyst_job_contracts import validate_manifest


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
        "SMARTBROWZ_ENDPOINT", "QUICKML_RAG_ENDPOINT", "QUICKML_ANALYTICS_ENDPOINT",
        "KSP_AUTH_EMPLOYEE_MAP",
        "KSP_AUTH_SERVICE_MAP",
    ),
    "silent_match": (
        "QUICKML_ORG_ID", "QUICKML_EMBEDDINGS_ENDPOINT",
        "QUICKML_EMBEDDINGS_MODEL", "KSP_AUTH_EMPLOYEE_MAP",
        "KSP_AUTH_SERVICE_MAP",
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


def _catalyst_authenticated():
    """Check the local CLI session without printing account information."""
    try:
        result = subprocess.run(
            ["catalyst", "whoami", "--non-interactive"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = str(result.stdout or "").lower()
    unauthenticated_markers = (
        "not logged in",
        "haven't logged in",
        "login failure",
        "please use catalyst login",
    )
    return result.returncode == 0 and not any(
        marker in output for marker in unauthenticated_markers
    )


def _project_config(root):
    """Validate the root manifest used by whole-project Catalyst deploys."""
    path = root / "catalyst.json"
    manifest, error = _read_json(path)
    if error is not None:
        return False, "root catalyst.json is missing or invalid"
    functions = manifest.get("functions")
    client = manifest.get("client")
    if not isinstance(functions, dict) or not isinstance(client, dict):
        return False, "functions and client sections are required"
    if functions.get("source") != "functions":
        return False, "functions source must be functions"
    targets = functions.get("targets")
    if targets != ["crime_query", "silent_match"]:
        return False, "function targets must match the two deployed functions"
    client_source = root / str(client.get("source", ""))
    if not client_source.is_dir():
        return False, "client source directory is missing"
    required_client_assets = ("index.html", "app.js", "styles.css")
    missing_assets = tuple(
        name for name in required_client_assets
        if not (client_source / name).is_file()
    )
    if missing_assets:
        return False, "client assets are missing: {}".format(", ".join(missing_assets))
    return True, "functions and web client targets configured"


def _schema_snapshot(sql):
    """Return table-to-column names for the SQLite-compatible checked-in DDL."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(sql)
        tables = {}
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ):
            if str(name).startswith("sqlite_"):
                continue
            columns = tuple(
                row[1] for row in connection.execute(
                    'PRAGMA table_info("{}")'.format(str(name).replace('"', '""'))
                )
            )
            tables[str(name)] = columns
        return tables, None
    except sqlite3.Error:
        return {}, "DDL is not executable as a schema contract"
    finally:
        connection.close()


def _schema_contract(root):
    """Ensure checked-in deployment DDL matches the application catalog."""
    if not callable(sqlite_ddl):
        return False, "application schema catalog is unavailable"
    paths = (
        root / "docs/schema-ddl.sql",
        root / "docs/silent-match-alerts-ddl.sql",
        root / "docs/derived-graph-ddl.sql",
    )
    if any(not path.is_file() for path in paths):
        return False, "one or more schema DDL files are missing"
    actual, error = _schema_snapshot(
        "\n".join(path.read_text(encoding="utf-8") for path in paths)
    )
    if error:
        return False, error
    expected, error = _schema_snapshot(sqlite_ddl())
    if error:
        return False, "application schema catalog is invalid"
    missing_tables = sorted(set(expected) - set(actual))
    extra_tables = sorted(set(actual) - set(expected))
    if missing_tables or extra_tables:
        detail = []
        if missing_tables:
            detail.append("missing tables: " + ", ".join(missing_tables))
        if extra_tables:
            detail.append("unexpected tables: " + ", ".join(extra_tables))
        return False, "; ".join(detail)
    for table in sorted(expected):
        missing_columns = sorted(set(expected[table]) - set(actual[table]))
        extra_columns = sorted(set(actual[table]) - set(expected[table]))
        if missing_columns or extra_columns:
            detail = []
            if missing_columns:
                detail.append("missing columns: " + ", ".join(missing_columns))
            if extra_columns:
                detail.append("unexpected columns: " + ", ".join(extra_columns))
            return False, "{} schema drift; {}".format(table, "; ".join(detail))
    return True, "checked-in DDL matches application schema catalog"


def run_preflight(
    root,
    require_live=False,
    catalyst_available=None,
    catalyst_authenticated=None,
):
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
    project_ok, project_detail = _project_config(root)
    check("catalyst_project_config", project_ok, project_detail)
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
        requirements_path = root / "functions" / name / "requirements.txt"
        requirements = requirements_path.read_text(encoding="utf-8") if requirements_path.exists() else ""
        check("{}_requirements".format(name), "zcatalyst-sdk" in requirements,
              "Catalyst Python SDK dependency declared")

    crime_env = configs["crime_query"].get("deployment", {}).get("env_variables", {})
    silent_env = configs["silent_match"].get("deployment", {}).get("env_variables", {})
    for name, env in (("crime_query", crime_env), ("silent_match", silent_env)):
        check("{}_env_shape".format(name), isinstance(env, dict), "environment map")
        for key in LIVE_CONFIG_KEYS[name]:
            value = env.get(key) if isinstance(env, dict) else None
            if key.endswith("ENDPOINT"):
                valid = _https_url(value) if value else False
                detail = "HTTPS endpoint configured" if valid else "HTTPS endpoint is required"
            elif key in ("KSP_AUTH_EMPLOYEE_MAP", "KSP_AUTH_SERVICE_MAP"):
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

    schema_ok, schema_detail = _schema_contract(root)
    check("schema_contract", schema_ok, schema_detail)

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

    job_manifest = validate_manifest(root / "docs/catalyst-job-contracts.json")
    check(
        "job_contract_manifest",
        job_manifest["ok"],
        "validated scheduled and post-ingestion payload contracts",
    )

    if catalyst_available is None:
        catalyst_available = shutil.which("catalyst") is not None
    check("catalyst_cli", catalyst_available, "Catalyst CLI available", live_gate=True)
    if catalyst_authenticated is None:
        catalyst_authenticated = (
            _catalyst_authenticated() if catalyst_available else False
        )
    check(
        "catalyst_authentication",
        catalyst_authenticated,
        "authenticated Catalyst CLI session",
        live_gate=True,
    )

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
