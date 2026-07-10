# Catalyst runbook — steps requiring a live account

Everything else in this branch (Tasks 1, 3–12) was built and tested offline
against `SqliteDB` and fakes. The steps below need a real Zoho Catalyst
account/CLI and were deliberately left for you to run. Do them in order —
each depends on the one before it.

## 1. Task 2 — confirm the ZCQL/Data Store call surface

`functions/crime_query/db.py`'s `ZcqlDB` class assumes specific SDK method
names (`app.zcql()`, `app.datastore()`, `.table(name).insert_row(dict)`,
`.execute_query(sql)`). These were never confirmed against a real SDK.

```bash
catalyst init                     # if the project isn't scaffolded yet
catalyst function:add crime_query --type advancedio
```

In the generated function, write a one-off script that:
1. Calls `app.zcql().execute_query("SELECT State.StateID FROM State")` against an empty/seeded Data Store table and confirms the row shape matches `ZcqlDB._flatten`'s assumption (rows keyed by table name, e.g. `{"State": {"StateID": 1}}`).
2. Calls `app.datastore().table("AuditLog").insert_row({...})` with a dummy row and confirms it lands.

If either call's real name or shape differs, fix `functions/crime_query/db.py`'s `ZcqlDB` class to match — that file's tests (`tests/test_db.py`) mock the SDK, so they won't catch a real mismatch; only this step will.

## 2. Load the seeded data into the Data Store

```bash
source .venv/bin/activate
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
ls build/csv     # 26 files, one per schema table
```

Create all 27 tables (26 schema tables + `AuditLog`) in the Catalyst console using the DDL in `functions/crime_query/catalog.py` (`catalog.describe()` prints the schema; `AuditLog`'s columns are `catalog.AUDIT_COLUMNS`).

Import order matters — parents before children:

```
State, District, UnitType, Unit, Rank, Designation, Employee,
CrimeHead, CrimeSubHead, CaseStatusMaster, CaseCategory, GravityOffence, Court,
CasteMaster, ReligionMaster, OccupationMaster, Act, Section, CrimeHeadActSection,
CaseMaster, ComplainantDetails, Victim, Accused, ArrestSurrender,
ActSectionAssociation, ChargesheetDetails
```

Verify in the console's ZCQL editor:

```sql
SELECT COUNT(CaseMaster.CaseMasterID) FROM CaseMaster
```

Expected: `5000`.

## 3. Deploy and smoke-test

```bash
catalyst deploy --only functions
```

Basic Q&A (constable, employee id 9 — scoped to one station):

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H 'Content-Type: application/json' \
  -d '{"employee_id": 9, "question": "How many two-wheeler thefts in Bengaluru East since April 2026?"}'
```

Expected: HTTP 200, `sql` contains `PoliceStationID IN (1)`, `filter_citation` names the crime sub-head and date filter.

Kannada round-trip:

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H 'Content-Type: application/json' \
  -d '{"employee_id": 9, "question": "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"}'
```

Expected: `"language": "kn"`, Kannada `answer`, every string in `citations` appears verbatim (Latin digits) inside the Kannada answer text.

RBAC scope widening (SP, employee id 97 — district-wide):

```bash
curl -s -X POST "$FUNCTION_URL" -H 'Content-Type: application/json' \
  -d '{"employee_id": 97, "question": "How many cases are open?"}' | grep -o 'IN ([0-9, ]*)'
```

Expected: `IN (1, 2, 3, 4)` — all four of the district's stations, not one.

Audit trail is real, not a no-op:

```sql
SELECT AuditLog.Question, AuditLog.EmployeeID, AuditLog.CrimeNos FROM AuditLog
```

Expected: one row per curl above, including any refused ones.

## 4. Kannada parity spot-check (10 paired questions)

The `sql` field is language-independent by construction (translation happens
before/after `agent.answer`, never inside it) — a Kannada question and its
English equivalent should generate identical SQL.

```bash
for pair in \
  "How many burglaries in Bengaluru East?|ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಎಷ್ಟು ಕಳ್ಳತನ ಪ್ರಕರಣಗಳಿವೆ?" \
  "How many murder cases are there?|ಎಷ್ಟು ಕೊಲೆ ಪ್ರಕರಣಗಳಿವೆ?" ; do
  en="${pair%%|*}"; kn="${pair##*|}"
  for q in "$en" "$kn"; do
    curl -s -X POST "$FUNCTION_URL" -H 'Content-Type: application/json' \
      -d "$(python -c 'import json,sys; print(json.dumps({"employee_id":9,"question":sys.argv[1]}))' "$q")" \
      | python -c 'import json,sys; print(json.load(sys.stdin)["sql"])'
  done
done
```

Extend to all 10 pairs of your choosing (mix of aggregate/filter questions across crime types and districts). Record the pass count out of 10 for the metrics slide — expected: 10/10 identical `sql` per pair. A mismatch here means the translate-pivot-translate step altered something load-bearing (a crime type name, a district name) and needs debugging in `functions/crime_query/translate.py` or `prompt.py`'s lookup-value matching, not in `agent.py`.

## 5. Live QuickML eval run (Task 10, deferred step)

`eval/run_eval.py` has a `main()` that wires a real `QuickMLLLM` against the
30-question labelled set — it was written and tested with `FakeLLM` but never
invoked live.

```bash
export QUICKML_ENDPOINT=... QUICKML_API_KEY=...
python -m eval.run_eval
```

Expected output: accuracy, hallucination_rate, p95_latency_s over the 30
questions. Record these numbers for the metrics slide — they're the real
headline evaluation numbers, everything before this point used `FakeLLM`.

## What "done" looks like

- Data Store has 5000 `CaseMaster` rows and all 26 other tables populated.
- All three smoke-test curls (Step 3) return expected shapes.
- `AuditLog` has one row per request, including refusals.
- 10/10 (or documented fewer) Kannada/English pairs produce identical SQL.
- `eval/run_eval.py`'s live run produces real accuracy/hallucination/latency numbers.

If any step fails, the fix almost always belongs in the same module that
step is testing (`db.py` for Step 1/3, `translate.py`/`prompt.py` for Step
4, `llm.py` for Step 5) — not in a new workaround file. Every module here
was built with a unit-test seam precisely so a live-environment mismatch is
a small, targeted fix.
