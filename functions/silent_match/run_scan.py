"""Stable job contract shared by Cron and post-ingestion triggers."""


def run_scan(scanner, payload):
    payload = payload or {}
    date_window = payload.get("date_window")
    anchor_case_id = payload.get("anchor_case_id")
    if (date_window is None) == (anchor_case_id is None):
        raise ValueError("provide exactly one scan selector")
    trigger_source = payload.get("trigger_source", "batch")
    return scanner.scan(
        date_window=date_window, anchor_case_id=anchor_case_id,
        trigger_source=trigger_source,
    )
