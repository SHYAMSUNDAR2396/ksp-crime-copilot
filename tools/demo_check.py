"""One-command offline demo and Catalyst artifact readiness check."""

import argparse
import json
from pathlib import Path

from tools.catalyst_preflight import run_preflight
from tools.demo_replay import build_replay


def run_demo_check(root, sqlite_path, output_path=None, require_live=False):
    """Run the synthetic nine-beat demo and local Catalyst artifact gate.

    The result is deliberately redacted to status names and counts. Missing
    live account configuration is reported as ``live_ready: false`` but does
    not prevent a disconnected demo from passing. ``require_live=True`` turns
    those account-side warnings into failures for a production gate.
    """
    root = Path(root)
    replay = build_replay(sqlite_path)
    preflight = (
        run_preflight(root, require_live=True)
        if require_live else run_preflight(root)
    )
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(replay, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    demo_summary = dict(replay.get("summary", {}))
    catalyst = {
        "artifacts_ok": bool(preflight["ok"]),
        "live_ready": bool(preflight["live_ready"]),
        "warnings": [item["name"] for item in preflight["warnings"]],
        "failures": [item["name"] for item in preflight["failures"]],
    }
    return {
        "ok": demo_summary.get("failed") == 0 and catalyst["artifacts_ok"],
        "demo": demo_summary,
        "catalyst": catalyst,
    }


def main_cli(argv=None):
    parser = argparse.ArgumentParser(description="Run the KSP demo readiness check")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sqlite", default="build/demo-crime.db")
    parser.add_argument("--output", default="docs/demo-replay.json")
    parser.add_argument(
        "--require-live", action="store_true",
        help="fail unless Catalyst account-side live gates pass",
    )
    args = parser.parse_args(argv)
    report = run_demo_check(
        args.root, args.sqlite, args.output, require_live=args.require_live,
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main_cli())
