"""Offline evaluation artifacts for the synthetic KSP contract suite.

The offline runner deliberately replays labelled SQL, so its result is a
deterministic execution/citation baseline.  It is not presented as a measure
of GLM-4.7 quality; live model metrics require the authenticated Catalyst
QuickML endpoint and are recorded separately when available.
"""
import argparse
import json
from pathlib import Path

from eval.run_eval import ACCURACY_TARGET, LATENCY_TARGET_S, QUESTIONS_PATH, TODAY, load_questions, run
from functions.crime_query import db as db_module
from functions.crime_query.llm import FakeLLM
from tools import gen_data


class OfflineGoldLLM(FakeLLM):
    """Return each labelled SQL query followed by a safe generic answer."""

    def __init__(self, questions):
        responses = []
        for question in questions:
            responses.extend([question["sql"], "Offline synthetic contract answer."])
        super().__init__(responses)


def run_offline(db, questions=None, today=TODAY):
    questions = list(questions or load_questions(QUESTIONS_PATH))
    report = run(db, OfflineGoldLLM(questions), questions, today)
    report.update({
        "evaluation_mode": "offline_synthetic_gold_sql",
        "question_count": len(questions),
        "targets": {
            "accuracy": ACCURACY_TARGET,
            "hallucination_rate": 0.0,
            "p95_latency_s": LATENCY_TARGET_S,
        },
        "target_status": {
            "accuracy": report["accuracy"] >= ACCURACY_TARGET,
            "hallucination_rate": report["hallucination_rate"] == 0,
            "p95_latency_s": report["p95_latency_s"] < LATENCY_TARGET_S,
        },
    })
    return report


def _slide(report, demo=None):
    demo = demo or {}
    summary = demo.get("summary", {})
    return """# KSP Crime Copilot — evaluation slide

## Offline synthetic contract baseline

This slide is generated from the labelled synthetic dataset and deterministic
local adapters. It verifies application execution and evidence contracts; it
does **not** claim live GLM-4.7 model quality. Live Catalyst values remain
pending an authenticated project run.

| Metric | Measured | Target | Status |
|---|---:|---:|---|
| SQL execution accuracy ({question_count} labelled questions) | {accuracy:.1%} | ≥ {accuracy_target:.0%} | {accuracy_status} |
| Unsupported CrimeNo hallucination rate | {hallucination_rate:.1%} | 0% | {hallucination_status} |
| Local p95 end-to-end latency | {p95_latency_s:.3f}s | < {latency_target:.0f}s | {latency_status} |
| Backup replay beats | {demo_passed}/{demo_total} | 9/9 | {demo_status} |

## Live measurement gate

- QuickML GLM-4.7 SQL/composition quality: pending authenticated Catalyst run.
- Kannada/English parity and real speech recognition: pending live voice test.
- Live p95 latency, specialist completion, and alert deduplication: pending
  Catalyst Job Scheduling and smoke execution.
- The checked-in deployment configuration intentionally leaves the RAG and
  multilingual embedding endpoints blank until the account-side endpoints
  are provisioned.
""".format(
        question_count=report["question_count"],
        accuracy=report["accuracy"],
        accuracy_target=report["targets"]["accuracy"],
        accuracy_status="PASS" if report["target_status"]["accuracy"] else "FAIL",
        hallucination_rate=report["hallucination_rate"],
        hallucination_status="PASS" if report["target_status"]["hallucination_rate"] else "FAIL",
        p95_latency_s=report["p95_latency_s"],
        latency_target=report["targets"]["p95_latency_s"],
        latency_status="PASS" if report["target_status"]["p95_latency_s"] else "FAIL",
        demo_passed=summary.get("passed", 0),
        demo_total=summary.get("passed", 0) + summary.get("failed", 0),
        demo_status="PASS" if summary.get("failed", 1) == 0 else "FAIL",
    )


def build_artifacts(sqlite_path, json_path, slide_path, demo_path=None):
    """Generate the synthetic database, machine-readable report, and slide."""
    sqlite_path = Path(sqlite_path)
    if sqlite_path.exists():
        sqlite_path.unlink()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    gen_data.build(str(sqlite_path))
    db = db_module.SqliteDB(str(sqlite_path))
    try:
        report = run_offline(db)
    finally:
        db.close()

    demo = {}
    if demo_path and Path(demo_path).exists():
        with Path(demo_path).open(encoding="utf-8") as handle:
            demo = json.load(handle)
    json_path = Path(json_path)
    slide_path = Path(slide_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    slide_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    slide_path.write_text(_slide(report, demo), encoding="utf-8")
    return report


def main_cli(argv=None):
    parser = argparse.ArgumentParser(description="Generate offline KSP evaluation artifacts")
    parser.add_argument("--sqlite", default="build/offline-eval-crime.db")
    parser.add_argument("--json", default="build/offline-evaluation.json")
    parser.add_argument("--slide", default="docs/evaluation-slide.md")
    parser.add_argument("--demo", default="docs/demo-replay.json")
    args = parser.parse_args(argv)
    report = build_artifacts(args.sqlite, args.json, args.slide, args.demo)
    print(json.dumps({
        "accuracy": report["accuracy"],
        "hallucination_rate": report["hallucination_rate"],
        "p95_latency_s": report["p95_latency_s"],
        "question_count": report["question_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
