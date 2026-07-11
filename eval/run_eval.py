"""Eval harness for PLAN.md section 4's metrics.

Execution accuracy, not string match: generated and gold SQL are both run and
their result sets compared as order-insensitive multisets.
"""
import argparse
import datetime as dt
import os
import time

import yaml

from functions.crime_query import agent
from functions.crime_query import db as db_module
from functions.crime_query.llm import QuickMLLLM
from functions.crime_query.rbac import Caller

QUESTIONS_PATH = os.path.join(os.path.dirname(__file__), "questions.yaml")
TODAY = dt.date(2026, 7, 9)

# Statewide caller: no scope predicate, so generated SQL is comparable to gold SQL.
EVAL_CALLER = Caller(employee_id=100, unit_id=1, district_id=1, rank_hierarchy=1)

ACCURACY_TARGET = 0.85
LATENCY_TARGET_S = 8.0


def load_questions(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def normalise(rows):
    """Order-insensitive, column-name-insensitive comparable form."""
    return sorted(tuple(sorted(str(value) for value in row.values())) for row in rows)


def score(generated_rows, gold_rows):
    return normalise(generated_rows) == normalise(gold_rows)


def _percentile(values, fraction):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def run(db, llm, questions, today):
    results, latencies = [], []
    correct = hallucinating = 0

    for question in questions:
        start = time.time()
        answer = agent.answer(question["question"], EVAL_CALLER, db, llm, today)
        elapsed = time.time() - start
        latencies.append(elapsed)

        gold_rows = db.execute(question["sql"])
        is_correct = (not answer.refused) and score(answer.rows, gold_rows)
        has_hallucination = bool(answer.hallucinated_crimenos)

        correct += int(is_correct)
        hallucinating += int(has_hallucination)
        results.append({
            "id": question["id"],
            "question": question["question"],
            "correct": is_correct,
            "refused": answer.refused,
            "refusal_reason": answer.refusal_reason,
            "hallucinated": answer.hallucinated_crimenos,
            "sql": answer.sql,
            "gold_sql": question["sql"].strip(),
            "latency_s": round(elapsed, 3),
        })

    total = len(questions)
    return {
        "accuracy": correct / total if total else 0.0,
        "hallucination_rate": hallucinating / total if total else 0.0,
        "p95_latency_s": round(_percentile(latencies, 0.95), 3),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Run the KSP NL->SQL eval.")
    parser.add_argument("--sqlite", default="build/crime.db")
    parser.add_argument("--endpoint", default=os.environ.get("QUICKML_ENDPOINT"))
    parser.add_argument("--token", default=os.environ.get("QUICKML_TOKEN"))
    parser.add_argument("--org-id", default=os.environ.get("QUICKML_ORG_ID"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.endpoint or not args.token or not args.org_id:
        parser.error("set QUICKML_ENDPOINT, QUICKML_TOKEN, and QUICKML_ORG_ID, or pass them explicitly")

    db = db_module.SqliteDB(args.sqlite)
    llm = QuickMLLLM(args.endpoint, args.token, args.org_id)
    report = run(db, llm, load_questions(QUESTIONS_PATH), TODAY)
    db.close()

    print("SQL correctness   {0:.1%}  (target >= {1:.0%})".format(
        report["accuracy"], ACCURACY_TARGET))
    print("Hallucination rate {0:.1%}  (target ~0%)".format(report["hallucination_rate"]))
    print("p95 latency        {0:.2f}s (target < {1:.0f}s)".format(
        report["p95_latency_s"], LATENCY_TARGET_S))

    if args.verbose:
        print()
        for result in report["results"]:
            mark = "PASS" if result["correct"] else "FAIL"
            print("[{0}] {1:>2}  {2}".format(mark, result["id"], result["question"]))
            if not result["correct"]:
                print("      generated: {0}".format(result["sql"] or "(refused)"))
                print("      gold:      {0}".format(result["gold_sql"]))

    failed = report["accuracy"] < ACCURACY_TARGET or report["hallucination_rate"] > 0
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
