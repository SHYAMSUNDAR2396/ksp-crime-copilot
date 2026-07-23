"""Opt-in, redacted smoke checks for deployed Catalyst functions.

Configuration inspection is offline. Network execution requires ``--execute``
and is deliberately kept outside the application runtime so a smoke test can
never become an implicit production side effect.
"""

import argparse
import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SmokeConfig:
    crime_query_url: str
    silent_match_url: str
    token: str
    case_id: int = 1
    include_scan: bool = False
    scan_date_window: tuple = ("2026-06-01", "2026-06-30")
    include_projection: bool = False
    projection_version: str = "graph-smoke-v1"
    include_views: bool = False
    include_export: bool = False


def _https(value):
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def _url(base, suffix):
    return str(base).rstrip("/") + "/" + suffix.lstrip("/")


def config_from_env(environ=None):
    values = environ or os.environ
    required = ("KSP_CRIME_QUERY_URL", "KSP_SILENT_MATCH_URL", "CATALYST_TOKEN")
    missing = [name for name in required if not str(values.get(name, "")).strip()]
    if missing:
        return None, tuple(missing)
    if not _https(values["KSP_CRIME_QUERY_URL"]):
        return None, ("KSP_CRIME_QUERY_URL must use HTTPS",)
    if not _https(values["KSP_SILENT_MATCH_URL"]):
        return None, ("KSP_SILENT_MATCH_URL must use HTTPS",)
    try:
        case_id = int(values.get("KSP_SMOKE_CASE_ID", "1"))
    except (TypeError, ValueError):
        return None, ("KSP_SMOKE_CASE_ID must be an integer",)
    if case_id < 1:
        return None, ("KSP_SMOKE_CASE_ID must be positive",)
    return SmokeConfig(
        crime_query_url=values["KSP_CRIME_QUERY_URL"],
        silent_match_url=values["KSP_SILENT_MATCH_URL"],
        token=values["CATALYST_TOKEN"],
        case_id=case_id,
    ), ()


def _response(response):
    try:
        body = response.json()
    except Exception:
        body = None
    return int(getattr(response, "status_code", 0)), body


def _step(client, method, url, token, payload, name, contract):
    try:
        response = client.request(
            method, url,
            headers={
                "Authorization": "Zoho-oauthtoken " + token,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        status, body = _response(response)
    except Exception:
        return {"name": name, "ok": False, "status": 0, "detail": "request failed"}
    if status != 200 or not isinstance(body, dict):
        return {"name": name, "ok": False, "status": status,
                "detail": "HTTP status or JSON contract failed"}
    if not contract(body):
        return {"name": name, "ok": False, "status": status,
                "detail": "response contract failed"}
    return {"name": name, "ok": True, "status": status, "detail": "contract passed"}


def _binary_step(client, method, url, token, payload, name):
    try:
        response = client.request(
            method, url,
            headers={
                "Authorization": "Zoho-oauthtoken " + token,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        status = int(getattr(response, "status_code", 0))
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("Content-Type", "")).lower()
        body = getattr(response, "content", b"")
    except Exception:
        return {"name": name, "ok": False, "status": 0, "detail": "request failed"}
    is_pdf = content_type.startswith("application/pdf") or body.startswith(b"%PDF")
    return {
        "name": name,
        "ok": status == 200 and is_pdf,
        "status": status,
        "detail": "PDF contract passed" if status == 200 and is_pdf else "PDF contract failed",
    }


def run_smoke(client, config):
    """Run safe contract checks and return only redacted step metadata."""
    if not _https(config.crime_query_url) or not _https(config.silent_match_url):
        return {"ok": False, "steps": [], "error": "HTTPS endpoint required"}
    if not config.token:
        return {"ok": False, "steps": [], "error": "authentication token required"}
    if int(config.case_id) < 1:
        return {"ok": False, "steps": [], "error": "case ID must be positive"}

    steps = []
    steps.append(_step(
        client, "POST", config.crime_query_url, config.token,
        {"question": "How many cases are there in total?"}, "crime_query",
        lambda body: {"refused", "answer", "citations", "evidence"} <= set(body),
    ))
    steps.append(_step(
        client, "POST", _url(config.silent_match_url, "/similar-cases"), config.token,
        {"case_master_id": int(config.case_id)}, "similar_cases",
        lambda body: {"case_master_id", "matches", "partial"} <= set(body),
    ))
    steps.append(_step(
        client, "GET", _url(config.silent_match_url, "/alerts"), config.token,
        {}, "alerts", lambda body: {"alerts", "partial"} <= set(body),
    ))
    if config.include_views:
        for name, payload, contract in (
            (
                "voice_query",
                {
                    "session_id": "smoke-session",
                    "turn_id": 1,
                    "input_mode": "voice",
                    "transcript": "How many cases are there?",
                    "response_language": "en",
                },
                lambda body: {"turn_id", "voice", "citations"} <= set(body),
            ),
            (
                "narrative",
                {"operation": "narrative", "question": "What happened in this case?"},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
            (
                "network",
                {"operation": "network", "case_master_id": int(config.case_id)},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
            (
                "analytics",
                {"operation": "analytics"},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
            (
                "profile",
                {"operation": "profile", "case_master_id": int(config.case_id)},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
            (
                "demographics",
                {"operation": "demographics", "dimension": "AgeYear"},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
            (
                "audit",
                {"operation": "audit"},
                lambda body: {"refused", "data", "citations", "evidence"} <= set(body),
            ),
        ):
            steps.append(_step(
                client, "POST", config.crime_query_url, config.token,
                payload, name, contract,
            ))
    if config.include_scan:
        start, end = config.scan_date_window
        steps.append(_step(
            client, "POST", _url(config.silent_match_url, "/scan"), config.token,
            {"date_window": [start, end], "trigger_source": "batch"},
            "batch_scan",
            lambda body: {"run_id", "alerts", "failures"} <= set(body),
        ))
    if config.include_projection:
        steps.append(_step(
            client, "POST", _url(config.silent_match_url, "/graph-projection"),
            config.token,
            {"projection_version": config.projection_version},
            "graph_projection",
            lambda body: {
                "projection_version", "nodes_written", "members_written",
                "edges_written",
            } <= set(body),
        ))
    if config.include_export:
        steps.append(_binary_step(
            client, "POST", config.crime_query_url, config.token,
            {"operation": "export", "session_id": "smoke-session"},
            "conversation_export",
        ))
    return {"ok": all(step["ok"] for step in steps), "steps": steps}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run redacted Catalyst smoke checks")
    parser.add_argument("--execute", action="store_true",
                        help="perform authenticated network checks")
    parser.add_argument("--include-scan", action="store_true",
                        help="also run the batch scan contract")
    parser.add_argument("--include-projection", action="store_true",
                        help="also run the versioned graph projection contract")
    parser.add_argument("--include-views", action="store_true",
                        help="also run voice, narrative, intelligence, and audit contracts")
    parser.add_argument("--include-export", action="store_true",
                        help="also require the deployed SmartBrowz PDF export contract")
    args = parser.parse_args(argv)
    config, missing = config_from_env()
    if config is None:
        print(json.dumps({"ok": False, "missing": list(missing)}, sort_keys=True))
        return 1
    if not args.execute:
        print(json.dumps({"ok": True, "ready_to_execute": True,
                          "network_calls": 0}, sort_keys=True))
        return 0
    config = SmokeConfig(
        config.crime_query_url, config.silent_match_url, config.token,
        config.case_id, include_scan=args.include_scan,
        scan_date_window=config.scan_date_window,
        include_projection=args.include_projection,
        projection_version=config.projection_version,
        include_views=args.include_views,
        include_export=args.include_export,
    )
    try:
        import requests
    except ImportError:
        print(json.dumps({"ok": False, "error": "requests is unavailable"}))
        return 1
    report = run_smoke(requests, config)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
