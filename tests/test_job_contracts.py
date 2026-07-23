import json
from pathlib import Path

import pytest

from functions.silent_match.job_contracts import (
    JobContractError,
    validate_graph_projection_payload,
    validate_index_payload,
    validate_scan_payload,
)
from tools.catalyst_job_contracts import validate_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_batch_scan_requires_a_valid_ordered_date_window():
    assert validate_scan_payload({
        "date_window": ["2026-06-01", "2026-06-30"],
        "trigger_source": "batch",
    })["date_window"] == ("2026-06-01", "2026-06-30")

    with pytest.raises(JobContractError, match="ordered date window"):
        validate_scan_payload({
            "date_window": ["2026-06-30", "2026-06-01"],
            "trigger_source": "batch",
        })


def test_live_scan_requires_only_a_positive_anchor_case():
    result = validate_scan_payload({
        "anchor_case_id": 123,
        "trigger_source": "live",
    })
    assert result["anchor_case_id"] == 123
    with pytest.raises(JobContractError, match="exactly one scan selector"):
        validate_scan_payload({
            "anchor_case_id": 123,
            "date_window": ["2026-06-01", "2026-06-30"],
            "trigger_source": "live",
        })


def test_job_payloads_reject_client_identity_and_unbounded_case_lists():
    with pytest.raises(JobContractError, match="employee_id"):
        validate_index_payload({"index_version": "mo-v2", "employee_id": 9})
    with pytest.raises(JobContractError, match="changed_case_ids"):
        validate_index_payload({
            "index_version": "mo-v2",
            "changed_case_ids": list(range(1, 1002)),
        })
    with pytest.raises(JobContractError, match="employee_id"):
        validate_graph_projection_payload({
            "projection_version": "graph-v2", "employee_id": 9,
        })


def test_job_manifest_is_structurally_valid_and_has_no_identity_field():
    report = validate_manifest(ROOT / "docs/catalyst-job-contracts.json")
    assert report["ok"] is True
    assert report["errors"] == []
    assert len(report["contracts"]) == 4
    assert all("employee_id" not in item["fields"] for item in report["contracts"])


def test_job_manifest_rejects_unprotected_or_retrying_malformed_contract(tmp_path):
    manifest = {
        "version": "v1",
        "function": "silent_match",
        "contracts": [{
            "name": "bad",
            "method": "GET",
            "route": "/alerts",
            "trigger": "scheduled",
            "fields": ["employee_id"],
            "retry": {"max_attempts": 0, "malformed_payload": "retry"},
        }],
    }
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = validate_manifest(path)
    assert report["ok"] is False
    assert any("protected job route" in error for error in report["errors"])
    assert any("employee_id" in error for error in report["errors"])
    assert any("max_attempts" in error for error in report["errors"])
    assert any("malformed_payload" in error for error in report["errors"])
