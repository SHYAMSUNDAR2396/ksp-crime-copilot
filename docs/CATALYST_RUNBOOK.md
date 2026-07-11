# Catalyst runbook — steps requiring a live account

Everything else in this branch (Tasks 1, 3–12) was built and tested offline
against `SqliteDB` and fakes. The steps below need a real Zoho Catalyst
account/CLI, against project `crime-copilot` (function URL
`https://crime-copilot-60075198995.development.catalystserverless.in/server/crime_query/`).

**Status: Steps 1–2 done, Step 3's deploy done but its smoke tests NOT
run, Steps 4–5 open.** Step 3's three smoke-test curls and Steps 4–5 all
need `QUICKML_ENDPOINT`/`QUICKML_API_KEY` set on the function (real
QuickML credentials) — nothing here has actually exercised the LLM yet, only
the deploy mechanics and the Data Store/audit SDK calls. Set the function's
environment variables in the console (Serverless → crime_query → Settings →
Environment Variables) or via `catalyst functions:config`, then run Step 3's
three curls before moving to Step 4.

## 1. Task 2 — confirm the ZCQL/Data Store call surface — DONE

`functions/crime_query/db.py`'s `ZcqlDB` class assumed specific SDK method
names (`app.zcql()`, `app.datastore()`, `.table(name).insert_row(dict)`,
`.execute_query(sql)`). Confirmed correct by deploying a temporary `/probe`
branch in `main.handler` that called both and reading the live response —
`app.zcql().execute_query()` returns rows keyed by table name as
`ZcqlDB._flatten()` assumed, and `app.datastore().table(...).insert_row()`
writes successfully. The probe branch was removed after confirming (see
`git log` for `functions/crime_query/main.py` around commit `e8060a6` if
you need to see exactly what it did).

**One real behavior difference found**: ZCQL returns every column value as
a string regardless of underlying column type (e.g. an `int` `StateID`
comes back as `"1"`, not `1`). Nothing in this codebase currently depends
on numeric typing of query results (RBAC and citation matching already
treat row values as strings), so no fix was needed — noted here in case a
future feature adds numeric comparisons on result rows.

**Three real deployment bugs found and fixed, none of which any local test
could have caught** (all fixed in commit `e8060a6`):

1. **`zcatalyst-sdk==1.4.0`** (what `catalyst init` scaffolds by default)
   **requires Python ≥3.10**, but the function's declared stack is
   `python_3_9` — `catalyst serve`/`catalyst deploy` fail outright installing
   it. Pinned to `zcatalyst-sdk==1.3.0` in `functions/crime_query/requirements.txt`.

2. **The real handler signature is `handler(request: Request) -> Response`**
   (Flask-based), not `handler(context, basic_io)` as originally guessed —
   this was already caught and fixed in an earlier commit (`7d9561b`), but
   is worth restating here since it's the reason this file needed
   confirming at all.

3. **Relative imports don't work in the deployed runtime.** Catalyst's
   Python Advanced I/O runtime loads `main.py` via
   `importlib.util.spec_from_file_location('', entrypoint)` with no parent
   package, and vendors every dependency (including our own sibling
   modules) flat into the same directory. `from . import agent` etc. raises
   `ImportError: attempted relative import with no known parent package`
   there, even though the identical code works fine locally (pytest imports
   `main.py` as `functions.crime_query.main`, a real package). Fixed with
   the standard try/except absolute-import fallback in every module that
   had relative imports (`main.py`, `agent.py`, `db.py`, `validate.py`,
   `prompt.py`, `rbac.py`).

4. **`AuditLog.Timestamp` is a reserved keyword** in Catalyst's Data
   Store — the console silently refuses to create a column with that name,
   so the manually-created `AuditLog` table was missing it entirely, and
   every audit write failed with a generic `Invalid input value for column
   name` error. Renamed `Timestamp` → `LoggedAt` everywhere (`catalog.py`,
   `db.py` callers, `docs/schema-ddl.sql`, tests). `AuditLog` isn't part of
   the frozen ER-doc schema (`PLAN.md` §1.5), so renaming its column was
   safe — this would **not** be an acceptable fix for any of the 26 real
   schema tables.

Two more manual-table-creation slips were found and fixed directly in the
console while working through Step 2 below, unrelated to the SDK itself:
`Act` was created with `Section`'s columns (crossed over during manual
entry, since they're adjacent in `docs/schema-ddl.sql`), and `Accused
.PersonID` / `ActSectionAssociation.ActID`+`SectionID` were typed `int`
when the real data is alphanumeric (`"A1"`, `"IPC"`) — the latter also
traces back to a genuine self-contradiction in `Police_FIR_ER_Diagram.md`
itself (an `INT` FK column pointing at a `VARCHAR` primary key). If you
ever recreate these tables from scratch, use `docs/schema-ddl.sql` as the
literal source and double check `Act`/`Section`/`Accused`/
`ActSectionAssociation` column-by-column rather than eyeballing it — this
class of typo is easy to make and the failure mode (all-rows-fail, cryptic
Catalyst error message) doesn't point at the cause directly.

## 2. Load the seeded data into the Data Store — DONE

All 27 tables created via the console's Schema Builder (no CLI path exists
for table creation — confirmed, see "table creation" note below) using
`docs/schema-ddl.sql` as the reference, and all 26 data tables loaded via
`catalyst ds:import --table <name> build/csv/<name>.csv` (needs a Stratus
bucket created first — Console → Cloud Scale → Storage → Stratus → Create
Bucket; `ds:import` prompts interactively to pick one). `AuditLog` stays
empty until the app writes to it. All row counts verified against
`build/csv/*.csv` via `catalyst ds:export --table <name>` — every table
matches exactly (`CaseMaster`/`ComplainantDetails`: 5000,
`Accused`: 9880, `ActSectionAssociation`: 5842, `Victim`: 4942, etc.)

Re-run the generator if you need to regenerate the CSVs:
```bash
source .venv/bin/activate
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
```

**Gotcha for `ds:import`**: if a previous import attempt uploaded a file to
the Stratus bucket before failing, re-running with the same filename 409s
(`key_already_exists`) — the bucket doesn't overwrite by default. Either
delete the stale object in the console's Stratus browser, or just copy the
CSV under a new filename before retrying (the `--table` flag controls the
target table independently of the uploaded filename).

## 3. Deploy and smoke-test — deploy done, smoke tests NOT run

```bash
catalyst deploy --only functions:crime_query
```

Confirmed working (see the four deployment bugs listed above, all fixed).
**The three curls below have not been run** — they need
`QUICKML_ENDPOINT`/`QUICKML_API_KEY` set on the function first.

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
