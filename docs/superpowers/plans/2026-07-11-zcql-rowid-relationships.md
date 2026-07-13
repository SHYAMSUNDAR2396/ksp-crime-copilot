# ZCQL ROWID Relationships Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every JOIN the system emits (LLM-generated or hardcoded) execute correctly against Catalyst's ZCQL, which requires each relationship declared as a "Foreign Key" column pointing at the parent table's internal `ROWID` — not the business primary key `docs/schema-ddl.sql` and every table in this schema uses.

**Architecture:** Teach the whole system one consistent rule instead of a divergent join condition per relationship: every FK column, in both `SqliteDB` and `ZcqlDB`, always holds and is joined against the parent's `ROWID`. `tools/gen_data.py` remaps SQLite's data to match Catalyst's shape at generation time, so the exact SQL text the LLM produces runs correctly on both backends without special-casing.

**Tech Stack:** Python 3.9, sqlite3, sqlglot, Zoho Catalyst CLI (`catalyst`), the system `expect` tool for driving `catalyst`'s interactive prompts.

## Global Constraints

- **Every table in the ER-doc schema has an implicit `ROWID`.** SQLite exposes it natively; Catalyst's Data Store assigns one to every row automatically. Neither needs a declared column — `ROWID` is a pseudo-column, valid on any table, never listed in `catalog.TABLES`.
- **Catalyst Foreign Key columns can only reference a parent's `ROWID`**, confirmed against a live deployment (`docs/CATALYST_RUNBOOK.md`, "Open gap: ZCQL relationships"). This is not negotiable — SQLite's willingness to join on any `ON` condition regardless of a declared relationship does not carry over.
- **CSVs used for live Catalyst import (`build/csv/*.csv`) must keep business-key values.** The live import path (Task 4 below) remaps them separately, using Catalyst's own actual ROWIDs, which don't exist until after import — `tools/gen_data.py`'s CSV export must never see the SQLite-side remap.
- **Python 3.9 compatible.** No `match`, no `X | Y` annotations, no bare `dict[str, int]` without `from __future__ import annotations`.
- **`catalyst ds:import`/`ds:export` are interactive** (bucket selection, "download report?" prompts) and must be driven via the system `expect` tool, not piped stdin — piping does not work against this CLI's TUI prompts (confirmed this session).

---

## Already done (Task 1, committed in `148e930`)

The offline SQLite-side foundation is built and tested — 203 tests passing. Do not redo this work; it's context for Tasks 2-5:

- `tools/gen_data.py`: `_remap_foreign_keys_to_rowid(conn)` rewrites every FK column (per `catalog.FOREIGN_KEYS`, all 40 relationships) from its business-key value to the parent row's SQLite `rowid`, via one correlated-subquery `UPDATE` per relationship, called from `build()` after the main insert loop and before CSV export.
- `functions/crime_query/catalog.py`: `describe()`'s Foreign Keys section now renders `child.col -> parent.ROWID` for every relationship.
- `functions/crime_query/prompt.py`: new rule 10 tells the model to always join against `ROWID`, never the parent's own named primary-key column.
- `functions/crime_query/validate.py`: `_check_columns` allows `<table>.ROWID` (case-insensitive) on any table.
- `functions/crime_query/db.py`: both `SqliteDB.caller_for` and `ZcqlDB.caller_for` now join `Employee.RankID` against `Rank.rowid`/`Rank.ROWID` — no more backend divergence.
- Regression tests: `tests/test_validate.py::test_rowid_join_target_is_allowed_on_any_table`, `tests/test_gen_data.py::test_foreign_keys_are_remapped_to_parent_rowid` (structural, all 40 relationships), `tests/test_gen_data.py::test_foreign_key_remap_is_not_a_coincidental_no_op` (proves the remap actually runs, using a text-keyed relationship where SQLite's `rowid` can never coincidentally equal the business key the way small sequential-integer-keyed lookup tables do), `tests/test_prompt.py::test_prompt_teaches_rowid_joins`.

**Known, verified fact this plan depends on:** for lookup/master tables with a small sequential-integer business key inserted in matching order (`Unit`, `District`, `CrimeSubHead`, `CrimeHead`, `CaseStatusMaster`, `GravityOffence`, `CaseCategory`, `OccupationMaster`, `Employee`, `Rank`, ...), SQLite's `rowid` coincidentally equals the business key by construction — so pre-existing SQL using old-style business-key joins against these tables still produces correct results today. This coincidence does **not** hold for text-keyed tables (`Act.ActCode`, `Section.SectionCode`) or any table whose insertion order might ever change. Tasks 2-3 close the one place this coincidence already produced a wrong answer, and remove reliance on it everywhere else in the eval set.

---

### Task 2: Fix eval gold SQL to use ROWID joins

`eval/questions.yaml`'s 30 gold-SQL answers were written before this change and mostly still produce correct results by the coincidental-alignment property above — except question 20, which filters directly on a business-key literal against a text-keyed table and now silently returns the wrong answer. This task fixes that real bug and removes the fragile coincidence-dependency from every other question, so the eval set stays correct even if `gen_data.py`'s insertion order ever changes.

**Files:**
- Modify: `eval/questions.yaml`
- Modify: `tests/test_eval.py`

**Interfaces:**
- Consumes: `catalog.FOREIGN_KEYS` (already exists), `run_eval.load_questions()` (already exists), `run_eval.normalise()`/`score()` (already exist, unchanged).
- Produces: nothing new consumed by later tasks — this task is a data fix plus a stronger regression guard.

- [x] **Step 1: Write the failing test proving question 20 is currently broken**

In `tests/test_eval.py`, add:

```python
def test_ipc_302_count_is_not_silently_zero(db, questions):
    """Question 20 used to filter ActSectionAssociation.ActID = 'IPC'
    directly -- a business-key literal against a column that now holds
    Act's ROWID after the remap in tools/gen_data.py. Verified live: this
    silently returned 0 instead of the correct 67. A COUNT query always
    returns exactly one row even when the count itself is wrong, so
    test_every_gold_query_returns_at_least_one_row can't catch this class
    of bug -- this test checks the actual value."""
    q20 = next(q for q in questions if q["id"] == 20)
    rows = db.execute(q20["sql"])
    assert rows[0]["n"] == 67
```

- [x] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval.py::test_ipc_302_count_is_not_silently_zero -v`
Expected: FAIL — `assert 0 == 67`

- [ ] **Step 3: Replace `eval/questions.yaml` with the ROWID-join-corrected version**

Every `ON <child>.<col> = <parent>.<businesskey>` becomes `ON <child>.<col> = <parent>.rowid`. Question 20 changes from a broken direct-literal filter to a proper join-and-filter-by-name. Replace the entire file with:

```yaml
- id: 1
  question: How many cases are there in total?
  sql: SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
- id: 2
  question: How many burglary cases are there?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    WHERE CrimeSubHead.CrimeHeadName = 'Burglary'
- id: 3
  question: How many two-wheeler thefts were registered in Bengaluru East?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft' AND Unit.UnitName = 'Bengaluru East'
- id: 4
  question: Give me the crime numbers of five murder cases.
  sql: >
    SELECT CaseMaster.CrimeNo FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    WHERE CrimeSubHead.CrimeHeadName = 'Murder'
    ORDER BY CaseMaster.CrimeNo LIMIT 5
- id: 5
  question: Which police station has registered the most cases?
  sql: >
    SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    GROUP BY Unit.UnitName ORDER BY n DESC, Unit.UnitName LIMIT 1
- id: 6
  question: How many cases were registered in Mysuru district?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    LEFT JOIN District ON Unit.DistrictID = District.rowid
    WHERE District.DistrictName = 'Mysuru'
- id: 7
  question: How many cases have been charge sheeted?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseStatusMaster ON CaseMaster.CaseStatusID = CaseStatusMaster.rowid
    WHERE CaseStatusMaster.CaseStatusName = 'Charge Sheeted'
- id: 8
  question: How many heinous offences are there?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN GravityOffence ON CaseMaster.GravityOffenceID = GravityOffence.rowid
    WHERE GravityOffence.LookupValue = 'Heinous'
- id: 9
  question: How many cases were registered on or after 1 January 2026?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    WHERE CaseMaster.CrimeRegisteredDate >= '2026-01-01'
- id: 10
  question: How many cases were registered during 2025?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    WHERE CaseMaster.CrimeRegisteredDate >= '2025-01-01'
      AND CaseMaster.CrimeRegisteredDate <= '2025-12-31'
- id: 11
  question: Break down the number of cases by crime group.
  sql: >
    SELECT CrimeHead.CrimeGroupName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeHead ON CaseMaster.CrimeMajorHeadID = CrimeHead.rowid
    GROUP BY CrimeHead.CrimeGroupName
- id: 12
  question: How many complainants are farmers?
  sql: >
    SELECT COUNT(ComplainantDetails.ComplainantID) AS n FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.rowid
    LEFT JOIN OccupationMaster ON ComplainantDetails.OccupationID = OccupationMaster.rowid
    WHERE OccupationMaster.OccupationName = 'Farmer'
- id: 13
  question: What is the average age of complainants?
  sql: >
    SELECT AVG(ComplainantDetails.AgeYear) AS n FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.rowid
- id: 14
  question: How many female victims are recorded?
  sql: >
    SELECT COUNT(Victim.VictimMasterID) AS n FROM CaseMaster
    LEFT JOIN Victim ON CaseMaster.CaseMasterID = Victim.rowid
    WHERE Victim.GenderID = 2
- id: 15
  question: How many accused persons are recorded across all cases?
  sql: >
    SELECT COUNT(Accused.AccusedMasterID) AS n FROM CaseMaster
    LEFT JOIN Accused ON CaseMaster.CaseMasterID = Accused.rowid
- id: 16
  question: How many arrests have been made?
  sql: >
    SELECT COUNT(ArrestSurrender.ArrestSurrenderID) AS n FROM CaseMaster
    LEFT JOIN ArrestSurrender ON CaseMaster.CaseMasterID = ArrestSurrender.rowid
- id: 17
  question: What is the most common type of crime?
  sql: >
    SELECT CrimeSubHead.CrimeHeadName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    GROUP BY CrimeSubHead.CrimeHeadName ORDER BY n DESC, CrimeSubHead.CrimeHeadName LIMIT 1
- id: 18
  question: How many cases are registered at Belagavi City station?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    WHERE Unit.UnitName = 'Belagavi City'
- id: 19
  question: List the crime numbers of all dacoity cases.
  sql: >
    SELECT CaseMaster.CrimeNo FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    WHERE CrimeSubHead.CrimeHeadName = 'Dacoity' ORDER BY CaseMaster.CrimeNo LIMIT 200
- id: 20
  question: How many cases were charged under IPC section 302?
  sql: >
    SELECT COUNT(DISTINCT CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN ActSectionAssociation ON CaseMaster.CaseMasterID = ActSectionAssociation.rowid
    LEFT JOIN Act ON ActSectionAssociation.ActID = Act.rowid
    LEFT JOIN Section ON ActSectionAssociation.SectionID = Section.rowid
    WHERE Act.ActCode = 'IPC' AND Section.SectionCode = '302'
- id: 21
  question: How many cases are there in each case status?
  sql: >
    SELECT CaseStatusMaster.CaseStatusName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseStatusMaster ON CaseMaster.CaseStatusID = CaseStatusMaster.rowid
    GROUP BY CaseStatusMaster.CaseStatusName
- id: 22
  question: How many zero FIRs have been registered?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseCategory ON CaseMaster.CaseCategoryID = CaseCategory.rowid
    WHERE CaseCategory.LookupValue = 'Zero FIR'
- id: 23
  question: How many cases were registered by employee number 1?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    WHERE CaseMaster.PolicePersonID = 1
- id: 24
  question: How many chargesheets of final report type A have been filed?
  sql: >
    SELECT COUNT(ChargesheetDetails.CSID) AS n FROM CaseMaster
    LEFT JOIN ChargesheetDetails ON CaseMaster.CaseMasterID = ChargesheetDetails.rowid
    WHERE ChargesheetDetails.cstype = 'A'
- id: 25
  question: What is the earliest case registration date?
  sql: SELECT MIN(CaseMaster.CrimeRegisteredDate) AS n FROM CaseMaster
- id: 26
  question: What is the most recent case registration date?
  sql: SELECT MAX(CaseMaster.CrimeRegisteredDate) AS n FROM CaseMaster
- id: 27
  question: How many cases were registered in Bengaluru City district during 2026?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    LEFT JOIN District ON Unit.DistrictID = District.rowid
    WHERE District.DistrictName = 'Bengaluru City'
      AND CaseMaster.CrimeRegisteredDate >= '2026-01-01'
      AND CaseMaster.CrimeRegisteredDate <= '2026-12-31'
- id: 28
  question: Break down complainants by religion.
  sql: >
    SELECT ComplainantDetails.ReligionID, COUNT(ComplainantDetails.ComplainantID) AS n
    FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.rowid
    GROUP BY ComplainantDetails.ReligionID
- id: 29
  question: How many non-heinous cases were registered in Mysuru district?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    LEFT JOIN District ON Unit.DistrictID = District.rowid
    LEFT JOIN GravityOffence ON CaseMaster.GravityOffenceID = GravityOffence.rowid
    WHERE District.DistrictName = 'Mysuru' AND GravityOffence.LookupValue = 'Non-Heinous'
- id: 30
  question: How many two-wheeler thefts happened in Bengaluru East since April 2026?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.rowid
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.rowid
    WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft'
      AND Unit.UnitName = 'Bengaluru East'
      AND CaseMaster.CrimeRegisteredDate >= '2026-04-01'
```

Question 23 (`CaseMaster.PolicePersonID = 1`) is left as a direct literal filter on purpose: it's a WHERE-clause literal, not a JOIN, and there is no subquery-free way to resolve "employee number 1" to `Employee.rowid` without either a join (this question has none) or relying on the same coincidental alignment — verified live, `Employee.rowid` equals `EmployeeID` for all 100 rows, so this is currently correct and stays that way unless `gen_data.py`'s `EMPLOYEES` insertion order ever changes. Note this dependency with a comment above question 23 if you want it documented in-file; not required for this task's tests to pass.

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest tests/test_eval.py::test_ipc_302_count_is_not_silently_zero -v`
Expected: PASS

- [ ] **Step 5: Run the full eval test suite and the full suite**

Run: `pytest tests/test_eval.py -v`
Expected: all pass, including the pre-existing `test_every_gold_query_passes_the_validator` and `test_every_gold_query_returns_at_least_one_row`.

Run: `pytest -q`
Expected: 204 passed (203 + this task's new test).

- [ ] **Step 6: Commit**

```bash
git add eval/questions.yaml tests/test_eval.py
git commit -m "fix(eval): correct gold SQL for ROWID joins, closing a silent IPC-302 bug

Question 20 filtered ActSectionAssociation.ActID = 'IPC' directly -- a
business-key literal against a column that now holds Act's ROWID after
gen_data.py's remap. Verified live: silently returned 0 instead of 67.
Every other question's join happened to still be correct by the same
coincidental rowid-equals-business-key property lookup tables have by
construction, but that's fragile against future gen_data.py changes --
rewritten to explicit ROWID joins throughout."
```

---

### Task 3: Fix `eval/run_eval.py`'s broken `QuickMLLLM` constructor call

`functions/crime_query/llm.py`'s `QuickMLLLM.__init__` now takes `(endpoint, token, org_id, timeout=60)` (fixed during the live QuickML integration work, commit `7ad6b06`), but `eval/run_eval.py`'s `main()` still calls it with the old 2-argument form. This is dead code today (never exercised by tests, deliberately — Task 10 of the original plan left the live run unexercised), but it's a real bug blocking Step 5 of `docs/CATALYST_RUNBOOK.md` ("Live QuickML eval run"), which is the next milestone after this plan.

**Files:**
- Modify: `eval/run_eval.py`

**Interfaces:**
- Consumes: `QuickMLLLM(endpoint, token, org_id, timeout=60)` (already exists in `functions/crime_query/llm.py`).
- Produces: nothing new — `main()` stays a standalone CLI entrypoint, not imported elsewhere.

- [ ] **Step 1: Confirm the current signature mismatch**

Run: `python -c "from functions.crime_query.llm import QuickMLLLM; import inspect; print(inspect.signature(QuickMLLLM.__init__))"`
Expected: `(self, endpoint, token, org_id, timeout=60)` — three required positional args after `self`, confirming `main()`'s two-arg call (`QuickMLLLM(args.endpoint, args.api_key)`) would raise `TypeError: __init__() missing 1 required positional argument: 'org_id'` if ever run.

- [ ] **Step 2: Fix `main()`**

In `eval/run_eval.py`, change:

```python
def main():
    parser = argparse.ArgumentParser(description="Run the KSP NL->SQL eval.")
    parser.add_argument("--sqlite", default="build/crime.db")
    parser.add_argument("--endpoint", default=os.environ.get("QUICKML_ENDPOINT"))
    parser.add_argument("--api-key", default=os.environ.get("QUICKML_API_KEY"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.endpoint or not args.api_key:
        parser.error("set QUICKML_ENDPOINT and QUICKML_API_KEY, or pass them explicitly")

    db = db_module.SqliteDB(args.sqlite)
    llm = QuickMLLLM(args.endpoint, args.api_key)
```

to:

```python
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
```

`--api-key` becomes `--token` because a standalone script (unlike a deployed function) has no `app.credential.token()` to call — running this script requires manually obtaining a live OAuth access token (see `docs/CATALYST_RUNBOOK.md` Step 5 for exactly how) and passing it in, same as `--org-id` is the same value `functions/crime_query/catalyst-config.json`'s `QUICKML_ORG_ID` env var holds.

- [ ] **Step 3: Confirm the fix by constructing the CLI parser directly (no live call)**

```python
import sys
sys.argv = ["run_eval.py", "--endpoint", "https://x", "--token", "t", "--org-id", "o"]
from eval import run_eval
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--sqlite", default="build/crime.db")
parser.add_argument("--endpoint")
parser.add_argument("--token")
parser.add_argument("--org-id")
parser.add_argument("--verbose", action="store_true")
args = parser.parse_args(sys.argv[1:])
from functions.crime_query.llm import QuickMLLLM
QuickMLLLM(args.endpoint, args.token, args.org_id)  # must not raise
print("OK")
```

Run this as a one-off script or paste into a `python3 -c` invocation from the repo root.
Expected: prints `OK`, no `TypeError`.

- [ ] **Step 4: Run the full suite to confirm nothing else references the old signature**

Run: `pytest -q`
Expected: 204 passed (unchanged from Task 2 — `main()` is not covered by any test, by design, since it requires live credentials).

- [ ] **Step 5: Commit**

```bash
git add eval/run_eval.py
git commit -m "fix(eval): update run_eval.py's QuickMLLLM call to the 3-arg signature

main() still called QuickMLLLM(endpoint, api_key) after llm.py's
constructor grew a required org_id parameter during the live QuickML
integration work -- dead code until Step 5 of the Catalyst runbook is
actually run, but real and blocking. --api-key becomes --token: a
standalone script has no app.credential.token() to call, so it needs
a manually-obtained live OAuth token instead."
```

---

### Task 4: Reusable Catalyst FK-remap automation script

Converting `Employee.RankID -> Rank` from a business-key column to a proper Catalyst Foreign Key column required: export the parent table, build a `{business_key: ROWID}` map, remap the child's CSV, and re-import in `upsert` mode. That was done by hand once. This task turns it into a reusable script so the remaining ~39 relationships (Task 5) don't repeat the same manual Python one-off each time.

The pure data-transformation logic (`build_rowid_map`, `remap_csv`) is fully offline-testable with fixture CSVs. The live orchestration (calling `catalyst ds:export`/`ds:import`) is not unit-tested, consistent with how this project treats every other live-Catalyst-only code path (`main.handler`, `ZcqlDB`) — it's exercised for real in Task 5's runbook procedure.

**Files:**
- Create: `tools/catalyst_fk_remap.py`
- Create: `tools/catalyst_ds_import.exp` (companion `expect` script — `catalyst ds:import`/`ds:export` are interactive and piping stdin does not work against them, confirmed this session)
- Test: `tests/test_catalyst_fk_remap.py`

**Interfaces:**
- Consumes: nothing from earlier tasks in this plan.
- Produces: `build_rowid_map(export_csv_path, parent_col) -> dict`, `remap_csv(child_csv_in, child_csv_out, child_col, rowid_map) -> None` — pure functions, importable and testable without any live Catalyst call. `main()` is the CLI entrypoint used only in Task 5's runbook procedure.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_catalyst_fk_remap.py`:

```python
import csv

from tools.catalyst_fk_remap import build_rowid_map, remap_csv


def _write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def test_build_rowid_map_reads_a_catalyst_export_csv(tmp_path):
    export_path = tmp_path / "Table-Rank.csv"
    _write_csv(
        export_path,
        ["ROWID", "CREATORID", "CREATEDTIME", "MODIFIEDTIME", "RankID", "RankName", "Hierarchy", "Active"],
        [
            ["48091000000037038", "48091000000013007", "2026-07-11 10:09:49:077",
             "2026-07-11 10:09:49:077", "1", "DGP", "1", "1"],
            ["48091000000037041", "48091000000013007", "2026-07-11 10:09:49:077",
             "2026-07-11 10:09:49:077", "4", "Inspector", "4", "1"],
        ],
    )

    mapping = build_rowid_map(str(export_path), "RankID")

    assert mapping == {"1": "48091000000037038", "4": "48091000000037041"}


def test_remap_csv_rewrites_only_the_target_column(tmp_path):
    child_in = tmp_path / "Employee.csv"
    child_out = tmp_path / "Employee_remapped.csv"
    _write_csv(
        child_in,
        ["EmployeeID", "DistrictID", "UnitID", "RankID", "FirstName"],
        [
            ["1", "1", "1", "4", "Suresh"],
            ["2", "1", "1", "5", "Manjunath"],
        ],
    )
    rowid_map = {"4": "48091000000037041", "5": "48091000000037042"}

    remap_csv(str(child_in), str(child_out), "RankID", rowid_map)

    with open(child_out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["RankID"] == "48091000000037041"
    assert rows[1]["RankID"] == "48091000000037042"
    # Every other column is untouched.
    assert rows[0]["EmployeeID"] == "1"
    assert rows[0]["FirstName"] == "Suresh"


def test_remap_csv_leaves_unmapped_values_untouched(tmp_path):
    """A child value with no entry in rowid_map (e.g. a NULL FK, or a
    parent row that doesn't exist) is left as-is rather than silently
    dropped or blanked -- the caller decides how to handle gaps, this
    function's job is only the substitution it can do safely."""
    child_in = tmp_path / "Employee.csv"
    child_out = tmp_path / "Employee_remapped.csv"
    _write_csv(
        child_in,
        ["EmployeeID", "RankID"],
        [["1", ""], ["2", "999"]],
    )
    rowid_map = {"4": "48091000000037041"}

    remap_csv(str(child_in), str(child_out), "RankID", rowid_map)

    with open(child_out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["RankID"] == ""
    assert rows[1]["RankID"] == "999"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_catalyst_fk_remap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools.catalyst_fk_remap'`

- [ ] **Step 3: Write `tools/catalyst_fk_remap.py`**

```python
"""Automates the export -> remap -> upsert-reimport ETL for converting one
Catalyst foreign-key relationship's data from business-key values to the
parent table's real, platform-assigned ROWID.

Prerequisite (console, no CLI path exists for this): the child table's FK
column must already be converted to Catalyst's "Foreign Key" data type,
pointing at the parent table, before running this script -- see
docs/CATALYST_RUNBOOK.md, "Open gap: ZCQL relationships", worked example.

Usage (see docs/CATALYST_RUNBOOK.md's runbook procedure for the full
per-relationship sequence, including the console steps this script does
not automate):

    python -m tools.catalyst_fk_remap \\
        --parent Rank --parent-col RankID \\
        --child Employee --child-col RankID --child-pk EmployeeID
"""
import argparse
import csv
import glob
import os
import subprocess
import sys

_EXP_SCRIPT = os.path.join(os.path.dirname(__file__), "catalyst_ds_import.exp")


def build_rowid_map(export_csv_path, parent_col):
    """Read a `catalyst ds:export`-downloaded CSV (ROWID plus every
    business column) into a {business_key_value: ROWID} dict."""
    mapping = {}
    with open(export_csv_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mapping[row[parent_col]] = row["ROWID"]
    return mapping


def remap_csv(child_csv_in, child_csv_out, child_col, rowid_map):
    """Rewrite one column of a child table's CSV from business-key values
    to the parent's ROWID. Values with no entry in rowid_map (NULL FKs,
    or a parent row genuinely absent) are left untouched -- the caller is
    responsible for deciding whether that's expected."""
    with open(child_csv_in, newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        rows = list(reader)
        fieldnames = reader.fieldnames
    for row in rows:
        if row[child_col] in rowid_map:
            row[child_col] = rowid_map[row[child_col]]
    with open(child_csv_out, "w", newline="", encoding="utf-8") as dst:
        writer = csv.DictWriter(dst, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _run(cmd):
    print("+ {0}".format(" ".join(cmd)))
    subprocess.run(cmd, check=True)


def _latest_export_csv(unzip_dir, parent_table):
    matches = sorted(glob.glob(os.path.join(unzip_dir, "Table-{0}*.csv".format(parent_table))))
    if not matches:
        raise SystemExit("no exported CSV found for {0} in {1}".format(parent_table, unzip_dir))
    return matches[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", required=True, help="Parent table name, e.g. Rank")
    parser.add_argument("--parent-col", required=True, help="Parent business-key column, e.g. RankID")
    parser.add_argument("--child", required=True, help="Child table name, e.g. Employee")
    parser.add_argument("--child-col", required=True, help="Child FK column to remap, e.g. RankID")
    parser.add_argument("--child-pk", required=True,
                         help="Child table's unique column, for the upsert find_by -- "
                              "must already be marked 'Is Unique' in the console")
    parser.add_argument("--csv-dir", default="build/csv", help="Where the original child CSV lives")
    parser.add_argument("--work-dir", default="build/fk_remap", help="Scratch directory for this script")
    args = parser.parse_args()

    os.makedirs(args.work_dir, exist_ok=True)

    print("== Step 1: export {0} ==".format(args.parent))
    export_out = subprocess.run(
        ["catalyst", "ds:export", "--table", args.parent],
        check=True, capture_output=True, text=True,
    ).stdout
    print(export_out)
    jobid = next(
        tok.strip('"') for tok in export_out.split() if tok.strip('"').isdigit() and len(tok.strip('"')) > 10
    )

    print("== Step 2: wait for export and download ==")
    unzip_dir = os.path.join(args.work_dir, "{0}_export".format(args.parent))
    os.makedirs(unzip_dir, exist_ok=True)
    _run([_EXP_SCRIPT, "status-download", "export", jobid])
    for zip_path in glob.glob("Export_{0}_*.zip".format(jobid)):
        _run(["unzip", "-o", zip_path, "-d", unzip_dir])
        os.remove(zip_path)

    export_csv = _latest_export_csv(unzip_dir, args.parent)
    rowid_map = build_rowid_map(export_csv, args.parent_col)
    print("Built {0}.{1} -> ROWID map with {2} entries".format(
        args.parent, args.parent_col, len(rowid_map)))

    print("== Step 3: remap the child CSV ==")
    child_csv_in = os.path.join(args.csv_dir, "{0}.csv".format(args.child))
    child_csv_out = os.path.join(args.work_dir, "{0}_fk_remapped.csv".format(args.child))
    remap_csv(child_csv_in, child_csv_out, args.child_col, rowid_map)

    print("== Step 4: upsert-reimport {0} ==".format(args.child))
    config_path = os.path.join(args.work_dir, "{0}_upsert_config.json".format(args.child))
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write('{{"operation": "upsert", "find_by": "{0}"}}'.format(args.child_pk))
    _run([_EXP_SCRIPT, "import", child_csv_out, args.child, config_path])

    print("Done. Verify with: catalyst ds:export --table {0}".format(args.child))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the companion `expect` script**

Create `tools/catalyst_ds_import.exp`:

```expect
#!/usr/bin/expect -f
# Drives catalyst ds:import / ds:export's interactive prompts, which do not
# accept piped stdin (confirmed this session). Three modes:
#   catalyst_ds_import.exp import <csv> <table> <config.json>
#   catalyst_ds_import.exp status-download export <jobid>
#   catalyst_ds_import.exp status-download import <jobid>
set timeout 120
set mode [lindex $argv 0]

if {$mode == "import"} {
    set csv [lindex $argv 1]
    set table [lindex $argv 2]
    set config [lindex $argv 3]
    spawn catalyst ds:import $csv --table $table --config $config
    expect "Select a bucket"
    send "\r"
    expect eof
} elseif {$mode == "status-download"} {
    set op [lindex $argv 1]
    set jobid [lindex $argv 2]
    spawn catalyst ds:status $op $jobid
    expect "download the report"
    send "y\r"
    expect eof
} else {
    puts "unknown mode: $mode"
    exit 1
}
```

Make it executable:

```bash
chmod +x tools/catalyst_ds_import.exp
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_catalyst_fk_remap.py -v`
Expected: 3 passed

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: 207 passed (204 + this task's 3 new tests). `main()`/the live orchestration is not covered by any test — same treatment as `main.handler` and `ZcqlDB` elsewhere in this codebase.

- [ ] **Step 7: Commit**

```bash
git add tools/catalyst_fk_remap.py tools/catalyst_ds_import.exp tests/test_catalyst_fk_remap.py
git commit -m "feat: reusable automation script for the Catalyst FK-remap ETL

Generalizes the by-hand Employee->Rank export/remap/upsert-reimport
sequence into a script, so the remaining ~39 relationships (Task 5's
runbook procedure) don't repeat the same manual Python one-off each
time. build_rowid_map/remap_csv are pure and unit tested; the live
catalyst ds:export/ds:import orchestration is not, consistent with
how every other live-Catalyst-only code path in this project is
treated -- it's exercised for real in the runbook, not in CI."
```

---

### Task 5: Runbook — convert the remaining relationships and re-verify Step 3

This task is a **documented procedure for the human**, not implementer code — the FK-column-type conversion has no CLI path (console only, confirmed twice this session) and running live `catalyst` commands against a real account is exactly the class of step this project has consistently deferred to a runbook rather than automated end-to-end (see `docs/CATALYST_RUNBOOK.md`'s existing Steps 1-5).

**Files:**
- Modify: `docs/CATALYST_RUNBOOK.md`

**Interfaces:**
- Consumes: `tools/catalyst_fk_remap.py` (Task 4), `catalog.FOREIGN_KEYS` (existing, 40 relationships, 1 already done).
- Produces: nothing consumed by later tasks — this is the last task in the plan.

- [ ] **Step 1: Determine which relationships the demo actually needs**

Not all 40 relationships need converting for the three Step 3 smoke-test questions and the 30-question eval set to work. Cross-reference `catalog.FOREIGN_KEYS` against every table `eval/questions.yaml` (Task 2's corrected version) and `docs/CATALYST_RUNBOOK.md`'s three smoke-test questions actually join through. At minimum, based on the questions already reviewed in this plan and the runbook: `CaseMaster -> Unit`, `CaseMaster -> CrimeSubHead`, `CaseMaster -> CrimeHead`, `CaseMaster -> CaseStatusMaster`, `CaseMaster -> CaseCategory`, `CaseMaster -> GravityOffence`, `CaseMaster -> Court`, `Unit -> District`, `ComplainantDetails -> CaseMaster`, `ComplainantDetails -> OccupationMaster`, `Victim -> CaseMaster`, `Accused -> CaseMaster`, `ArrestSurrender -> CaseMaster`, `ActSectionAssociation -> CaseMaster`, `ActSectionAssociation -> Act`, `ActSectionAssociation -> Section`, `ChargesheetDetails -> CaseMaster`. `Employee -> Rank` is already done. This is close to the full 40 — expect to convert most of them, not a small subset.

- [ ] **Step 2: Append the runbook procedure**

Add a new section to `docs/CATALYST_RUNBOOK.md`, after the existing "Open gap: ZCQL relationships" section and before "## 4. Kannada parity spot-check":

```markdown
## Converting the remaining relationships (Task 5 of the 2026-07-11 ROWID plan)

For each relationship identified in Step 1 above, repeat this sequence
(the console step has no CLI path; everything else is `tools/catalyst_fk_remap.py`):

1. **Console:** open the child table, delete the FK column, re-add it with
   the same name, Data Type **Foreign Key**, Parent Table set to the
   relationship's parent, On Delete **Null**.
2. **Console:** if the child table's own primary-key-equivalent column
   (used as `--child-pk` below) isn't already marked **Is Unique**, mark
   it now — required for the automation script's `upsert` step.
3. **Run the automation script:**
   ```bash
   python -m tools.catalyst_fk_remap \
     --parent <ParentTable> --parent-col <ParentBusinessKeyColumn> \
     --child <ChildTable> --child-col <ChildFKColumn> \
     --child-pk <ChildUniqueColumn>
   ```
   Example, for `CaseMaster.PoliceStationID -> Unit`:
   ```bash
   python -m tools.catalyst_fk_remap \
     --parent Unit --parent-col UnitID \
     --child CaseMaster --child-col PoliceStationID \
     --child-pk CaseMasterID
   ```
4. **Verify:** `catalyst ds:export --table <ChildTable>` and spot-check a
   few rows' remapped column against the parent's actual ROWID.

`CaseMaster` is both a child (8 of its own columns are FKs) and a parent
(referenced by `ComplainantDetails`, `Victim`, `Accused`, `ArrestSurrender`,
`ActSectionAssociation`, `ChargesheetDetails`). Convert and remap all of
`CaseMaster`'s own FK columns first — the tables that reference
`CaseMaster.rowid` don't depend on `CaseMaster`'s own FK values, so order
between those two groups doesn't matter, but doing `CaseMaster` first keeps
the verification queries in Step 4 meaningful earlier.

After every relationship in Step 1's list is converted:

## 6. Re-verify Step 3's smoke tests

Re-run the three curls from Step 3 above. All three should now execute
past the `ZCQL QUERY ERROR: No relationship between tables ...` failures
seen earlier in this session. If a curl still fails with that exact error,
a relationship was missed in Step 1's list — check which table pair the
error names and add it to the conversion sequence above.

Then run the Kannada parity spot-check (Step 4) and the live QuickML eval
(Step 5) as originally documented.
```

- [ ] **Step 3: Update the runbook's status header**

At the top of `docs/CATALYST_RUNBOOK.md`, find:

```markdown
**Status: Steps 1–2 done, Step 3 partially working (blocked on a real
architectural gap, see below), Steps 4–5 open.** QuickML is live and wired
up (auth, response parsing, thinking-trace stripping all fixed and
confirmed against real calls — see the QuickML section below). The basic
Q&A smoke test now gets as far as generating and validating correct SQL,
but **fails at execution** because ZCQL JOINs need each relationship
explicitly declared as a "Foreign Key" column type pointing at the parent
table's internal `ROWID` — not at the parent's business primary key the
way `docs/schema-ddl.sql` and every generated query assumes. This is a
real architecture question, not a quick fix — see "Open gap: ZCQL
relationships" below before doing anything else with Step 3.
```

Replace with:

```markdown
**Status: Steps 1–2 done. Step 3 was blocked on a real architectural
gap (ZCQL relationships needing Foreign Key columns pointing at a
parent's ROWID, not its business key) — resolved offline by teaching
the whole system one consistent rule (every join targets ROWID; see
"Open gap: ZCQL relationships" and the "Converting the remaining
relationships" procedure below), with the live Catalyst side converted
relationship-by-relationship using `tools/catalyst_fk_remap.py`.**
Confirm Step 3's three smoke-test curls actually pass before treating
this as fully closed — see "Re-verify Step 3's smoke tests" below.
Steps 4–5 remain open pending that confirmation.
```

- [ ] **Step 4: Commit the runbook update**

```bash
git add docs/CATALYST_RUNBOOK.md
git commit -m "docs: runbook procedure for converting the remaining ZCQL relationships

Documents the per-relationship console + tools/catalyst_fk_remap.py
sequence for the ~39 relationships beyond Employee->Rank, which table
pairs the demo actually needs converted, and how to re-verify Step 3's
smoke tests once done."
```

This task's actual execution (running the script against the live
Catalyst account, ~15-20 relationships) is deferred to the human — no
CLI path exists for the console step, matching every other live-account
step in this project.

---

## Self-Review Notes

**Spec coverage:** Task 1 (done) covers the offline foundation. Task 2 closes the one real gold-SQL bug the ROWID change exposed and removes reliance on coincidental alignment elsewhere. Task 3 fixes a real, verified dead-code bug blocking the eventual live eval run. Task 4 builds reusable tooling instead of repeating by-hand ETL 39 more times. Task 5 is the documented human procedure to actually close the live Catalyst gap and re-verify Step 3, consistent with this project's established pattern of deferring live-account steps.

**Placeholder scan:** No TBD/TODO. Task 5's script invocation examples use real table/column names already verified against `catalog.FOREIGN_KEYS` and the live schema.

**Type consistency:** `build_rowid_map`/`remap_csv` signatures in Task 4 match their use in Task 4's own tests and Task 5's script; no other task calls them directly.
