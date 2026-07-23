"""Stable job contract shared by Cron and post-ingestion triggers."""

try:
    from .job_contracts import validate_scan_payload
except ImportError:  # pragma: no cover
    from job_contracts import validate_scan_payload


def run_scan(scanner, payload):
    payload = validate_scan_payload(payload or {})
    return scanner.scan(
        date_window=payload["date_window"],
        anchor_case_id=payload["anchor_case_id"],
        trigger_source=payload["trigger_source"],
    )
