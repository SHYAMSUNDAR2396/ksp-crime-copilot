"""Guarded Catalyst release command for the demo environment.

The command keeps deployment explicit and fail-closed: the live preflight must
pass before the vendor bundle is prepared or the Catalyst CLI is invoked.
"""

import argparse
import json
import subprocess
from pathlib import Path

from tools.catalyst_preflight import run_preflight
from tools.prepare_catalyst_deploy import prepare


def _failure_names(report):
    return [item["name"] for item in report.get("failures", ())]


def run_release(root, project=None, deploy=False, runner=subprocess.run):
    """Run live preflight, package functions, and optionally deploy them."""
    root = Path(root)
    preflight = run_preflight(root, require_live=True)
    if not preflight["ok"]:
        return {
            "ok": False,
            "live_ready": False,
            "prepared": False,
            "deployed": False,
            "deploy_status": "not_started",
            "failures": _failure_names(preflight),
        }

    try:
        prepare(root)
    except Exception:
        return {
            "ok": False,
            "live_ready": True,
            "prepared": False,
            "deployed": False,
            "deploy_status": "package_failed",
            "failures": ["catalyst_package"],
        }

    if not deploy:
        return {
            "ok": True,
            "live_ready": True,
            "prepared": True,
            "deployed": False,
            "deploy_status": "not_requested",
            "failures": [],
        }

    command = ["catalyst", "--non-interactive"]
    if project:
        command.extend(["--project", str(project)])
    command.append("deploy")
    try:
        result = runner(
            command,
            cwd=str(root),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return {
            "ok": False,
            "live_ready": True,
            "prepared": True,
            "deployed": False,
            "deploy_status": "failed",
            "failures": ["catalyst_deploy"],
        }

    passed = result.returncode == 0
    return {
        "ok": passed,
        "live_ready": True,
        "prepared": True,
        "deployed": passed,
        "deploy_status": "passed" if passed else "failed",
        "failures": [] if passed else ["catalyst_deploy"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guarded Catalyst release")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--project", help="Catalyst project name or ID")
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="invoke catalyst deploy after the live gate and packaging pass",
    )
    args = parser.parse_args(argv)
    report = run_release(args.root, project=args.project, deploy=args.deploy)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
