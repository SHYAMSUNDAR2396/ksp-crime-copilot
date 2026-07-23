# Catalyst runbook — steps requiring a live account

Everything else in this branch (Tasks 1, 3–12) was built and tested offline
against `SqliteDB` and fakes. The steps below need a real Zoho Catalyst
account/CLI, against project `crime-copilot` (function URL
`https://crime-copilot-60075198995.development.catalystserverless.in/server/crime_query/`).

**Current workspace status (2026-07-23): live readiness is not verified.** The
Catalyst CLI is not available in this workspace, the principal mapping is a
placeholder, and the multilingual embedding/RAG endpoints are intentionally
blank in the checked-in configuration. The historical notes below record
earlier account observations and implementation decisions; they are not a
substitute for rerunning the checks against the current Catalyst project.
Run the safe local gate first:

```bash
python -m tools.catalyst_preflight
python -m tools.catalyst_preflight --require-live
```

The second command must return exit code 0, followed by the authenticated
deployment and smoke tests in this document, before production readiness is
claimed.

The repeatable smoke contract is available as an opt-in command. It prints
only step names, status codes, and fixed contract results; it never prints
tokens, URLs, response bodies, or CrimeNos:

```bash
export KSP_CRIME_QUERY_URL="https://..."
export KSP_SILENT_MATCH_URL="https://..."
export CATALYST_TOKEN="..."
python -m tools.catalyst_smoke --execute --include-views --include-export
```

Use `--include-scan` and `--include-projection` only with synthetic fixtures
because they create or update operational alert/graph state. `--include-views`
covers the voice, narrative, network, analytics, profile, demographic, and
audit contracts in addition to the base query/similar-case/inbox checks.
`--include-export` additionally requires a real SmartBrowz PDF response.

**Status: the implementation and deployment contract are complete locally,
but live readiness is still unverified.** The earlier account investigation
identified ZCQL Foreign Key/parent-`ROWID` behavior; the current code, catalog,
prompts, fixed projections, and remapping tools consistently implement that
rule. Re-run the authenticated smoke contract against the current Catalyst
project before closing the live gate. Steps 4–5 also require live credentials
and model/embedding endpoints.

Before the curls, apply [`CATALYST_SECURITY.md`](CATALYST_SECURITY.md), set
`KSP_AUTH_EMPLOYEE_MAP` in both function configurations, and authenticate the
request. Configure `KSP_AUTH_SERVICE_MAP` separately for Job Scheduling and
post-ingestion identities. The deployed handlers discard `employee_id` from
the request body; identity comes only from the Catalyst principal and its
server-side mapping. Service identities are limited to silent-match job
routes.

## QuickML RAG document contract

QuickML's Knowledge Base is account-managed: the operator uploads or imports
documents, and the RAG API exposes the endpoint, document selection, and OAuth
scope from its **View API** panel. This repository does not invent an upload
API. When the RAG endpoint is configured, the narrative adapter sends one
scope-filtered `BriefFacts` document per case. Each document is prefixed with
`CrimeNo`, `CaseMasterID`, district, station, crime-head IDs, and registered
date; the response is mapped back to the original `BriefFacts` text before it
is returned as a citation.

`QUICKML_RAG_MAX_DOCUMENTS` defaults to `500`. A request whose authorized
scope exceeds that limit fails closed, because silently truncating a police
scope would produce misleading results. For larger deployments, provision a
QuickML Knowledge Base/document-store partition and expose a corresponding
scoped retrieval contract before raising this limit. The local deterministic
retriever remains the explicit rehearsal fallback while the live endpoint is
blank.

For silent-match scans, keep `KSP_SILENT_MATCH_LOOKBACK_DAYS` explicitly set
in `silent_match/catalyst-config.json` (default `365`). Batch anchors scan the
requested date window while candidates are limited to that window plus the
historical lookback; live anchors scan the same lookback ending on the anchor
case date. This keeps retrieval bounded and makes batch/live scoring parity
replayable.

## Query-generation contract

The production query dialect is Zoho Catalyst ZCQL, not generic SQLite. The
prompt is built from the live catalog and lookup values and includes the
declared Catalyst Foreign Key map. Every such join targets the parent table's
internal `ROWID` (for example, `CaseMaster.PoliceStationID = Unit.ROWID`),
never the parent's business-key column. The validator enforces this contract
before the server applies the caller's RBAC predicate and executes the query.

Operational tables such as `AuditLog` are deliberately absent from the
NL-to-ZCQL catalog. Local SQLite remains a deterministic test adapter only;
the live smoke tests below are required to verify Catalyst relationship setup.

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

## 3. Deploy and smoke-test — live re-verification pending

```bash
catalyst deploy --only functions:crime_query
```

Confirmed working (see the four deployment bugs listed above, all fixed).

### QuickML LLM Serving — confirmed working, three real bugs fixed

`QUICKML_ENDPOINT` and `QUICKML_ORG_ID` live in
`functions/crime_query/catalyst-config.json`'s `env_variables` (get the
endpoint from the console: **QuickML → GLM-4.7-Flash → Model Details →
API Details → Endpoint URL**; the org ID is the numeric ID shown next to
`"CATALYST-ORG"` in that same panel's sample headers). Setting env vars
through the console's function Configuration tab does **not** persist —
`catalyst deploy` overwrites them from `catalyst-config.json` on every
deploy, so they must live in that file, not just the console.

No `QUICKML_API_KEY` is needed — `main._quickml_token(app)` pulls a live,
auto-refreshed OAuth token from `app.credential.token()` at request time.

`QUICKML_MODEL` is pinned to Catalyst's `crm-di-glm47b_30b_it` deployment so
the deprecated model cannot be selected accidentally. Conversation
export uses `SMARTBROWZ_ENDPOINT`, the Catalyst SmartBrowz
`/browser360/v1/project/{project_id}/convert` endpoint, and requests a PDF
from a verified, scope-filtered HTML document. Enable the
`ZohoCatalyst.pdfshot.EXECUTE` scope for the function. If the endpoint is not
configured, the handler returns the safe HTML fallback for local tests; the
deployed configuration should keep the endpoint enabled for the PLAN.md PDF
export requirement.

### Analytics forecast provider — optional live enhancement

The analytics view uses a deterministic station-by-crime-type moving average
by default. When the account provisions a QuickML aggregate forecasting
endpoint, set `QUICKML_ANALYTICS_ENDPOINT`, `QUICKML_ANALYTICS_MODEL`, and
`QUICKML_ANALYTICS_TIMEOUT` in `functions/crime_query/catalyst-config.json`.
The adapter sends only period/count aggregates and validates finite,
non-negative baseline and forecast values. Provider failures fall back to the
deterministic result and mark the provider fallback; they never expose the
provider response to the browser. This is a separate analytics contract;
Catalyst Pipelines' SDK is for CI/CD pipeline execution, not crime forecast
output.

Three things only a live call revealed, all fixed in `functions/crime_query/llm.py`:
1. The real response shape is `{"response": "...", "usage": {...}}`, not
   the OpenAI-style `{"choices": [...]}` the console's own sample documents.
2. This deployment has a large baked-in system prompt and will refuse
   (misreading it as an override attempt) if you supply your own
   `system`-role message — send user-role messages only.
3. It's a "thinking" model: the response text contains a visible
   reasoning trace ending in `</think>` (no opening tag) before the real
   answer, and needs `max_tokens` well above the default 512 to reach the
   answer at all — `llm.py` now strips the trace and requests 2048 tokens.

Confirmed via a real end-to-end LLM call (through a temporary `/probe`
branch, since removed): given the actual `prompt.build_prompt()` output for
"How many burglaries in Bengaluru East since April 2026?", QuickML
returned syntactically correct SQL that `validate.validate()` accepts as-is
— generation and validation both work. The blocker below is purely at
execution time.

### Basic Q&A smoke test — local contract verified, live execution pending

Basic Q&A (constable, employee id 9 — scoped to one station):

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H "Authorization: Zoho-oauthtoken $CATALYST_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many two-wheeler thefts in Bengaluru East since April 2026?"}'
```

Expected: HTTP 200, `sql` contains `PoliceStationID IN (1)`, `filter_citation` names the crime sub-head and date filter.

The local SQLite path executes this contract successfully. The earlier live
account failure (`No relationship between tables CrimeSubHead and CaseMaster`)
was caused by undeclared Catalyst relationships and is retained below as a
historical diagnostic. Re-run this request against the current project after
applying the FK/ROWID import procedure; do not treat local success as proof of
live ZCQL readiness.

Kannada round-trip:

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H "Authorization: Zoho-oauthtoken $CATALYST_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question": "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"}'
```

Expected: `"language": "kn"`, Kannada `answer`, every string in `citations` appears verbatim (Latin digits) inside the Kannada answer text.

RBAC scope widening (SP, employee id 97 — district-wide):

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H "Authorization: Zoho-oauthtoken $CATALYST_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question": "How many cases are open?"}' | grep -o 'IN ([0-9, ]*)'
```

Expected: `IN (1, 2, 3, 4)` — all four of the district's stations, not one.

Audit trail is real, not a no-op:

```sql
SELECT AuditLog.Question, AuditLog.EmployeeID, AuditLog.CrimeNos FROM AuditLog
```

Expected: one row per curl above, including any refused ones.

## Historical ZCQL relationship investigation and current remediation

**This section records the original live-account failure and remediation. It is
not current evidence that the present deployment is broken; authenticated
smoke execution is still required to verify the current Catalyst project.**

### What's wrong

`docs/schema-ddl.sql` (and every table created from it) declares foreign
keys as plain `INTEGER`/`TEXT` columns — e.g. `Employee.RankID INTEGER`,
matching `Police_FIR_ER_Diagram.md` exactly. SQLite joins on any `ON`
condition regardless of whether a formal relationship was declared, so
this worked fine in every local test. ZCQL does not: **a JOIN between two
tables is only allowed if one side is a column explicitly typed "Foreign
Key" in the console**, pointing at the other table. Confirmed via:

```
ZCQL QUERY ERROR: No relationship between tables Rank and Employee
```

on the very first real query (`db.caller_for`, which runs before every
single request).

### It gets worse: Foreign Key columns reference ROWID, not the business key

Converting `Employee.RankID` to a Foreign Key column (console: delete the
column, re-add it as type **Foreign Key** with Parent Table `Rank`, On
Delete `Null`) fixed the "no relationship" error, but the very next
attempt failed differently:

```
Invalid Foreign key value for column RankID. ROWID of table Rank is expected
```

Catalyst's Foreign Key columns store and compare against the **parent
table's internal, platform-generated `ROWID`** — not `Rank.RankID`, the
business primary key from `Police_FIR_ER_Diagram.md` that every table in
this schema uses as its declared PK. This is fixable per-relationship (see
the worked example below), but it means:

- The JOIN condition itself must change (`ON Employee.RankID = Rank.ROWID`,
  not `Rank.RankID`) everywhere that relationship is used.
- For relationships **we hardcode** (like `db.caller_for`'s join, fixed
  in commit `7ad6b06`), this is a one-line change.
- For relationships the **LLM generates from natural language** (e.g.
  `CaseMaster → CrimeSubHead` for "how many burglaries"), the model has no
  way to know it must join against `ROWID` — it only sees our schema
  description, which (correctly, per the ER doc) names `CrimeSubHeadID`
  as the business key. Converting `CaseMaster.CrimeMinorHeadID` to a
  Foreign Key column the same way would make the model's own naturally
  correct SQL wrong every time.

This is the real blocker: fixing individual relationships one at a time
doesn't generalize to arbitrary LLM-generated JOINs across the 40
relationships in `catalog.FOREIGN_KEYS`. It needs one of:

1. **Teach the model about ROWID indirection** — extend
   `prompt.py`'s schema description to tell the model which columns are
   Catalyst Foreign Keys and that those specific joins must use `ROWID`,
   and remap every touched table's foreign-key column values from
   business keys to the parent's actual `ROWID` (export the parent table,
   build a mapping, remap the CSV, re-import via `upsert` — see the
   worked example below). Scales to however many relationships the demo
   actually needs, but every new relationship is real, careful, easy-to-
   get-wrong ETL work, and the model must get the ROWID-vs-business-key
   distinction right for every JOIN it writes.
2. **Redesign around application-side joins** — `agent.py`/`db.py` fetch
   from one table at a time and merge in Python, never emitting a ZCQL
   `JOIN`. Avoids the ROWID problem entirely, but is a real architecture
   change touching `validate.py`, `rbac.py`, and `prompt.py`'s core
   assumption that every answer is one validated SQL statement.
3. **Live with SQLite-only correctness** for the datathon submission,
   documenting ZCQL relationship support as a known gap, and demo against
   `SqliteDB` (fully working under the current deterministic suite) rather
   than the live Catalyst deployment.

### Worked example: `Employee.RankID → Rank` (the one relationship fixed so far)

This relationship is hardcoded in `db.py` (not LLM-generated), so it was
safe to fix directly — use this as the template for any other relationship
you decide to convert:

```bash
# 1. Console: Employee table -> delete RankID column -> + New Column:
#    Name RankID, Data Type "Foreign Key", Parent Table "Rank", On Delete "Null"

# 2. Export the parent table to get its ROWID mapping
catalyst ds:export --table Rank
catalyst ds:status export <jobid>   # answer y to download the report zip
unzip Export_*.zip                  # -> Table-Rank.csv with ROWID + RankID columns

# 3. Console: mark the child table's primary key column "Is Unique" if not
#    already (needed for upsert's find_by) -- e.g. Employee.EmployeeID

# 4. Remap the child CSV's FK column from business key -> parent ROWID
#    (see the Python snippet used for Employee.csv in the commit history
#    around 7ad6b06 -- reads Table-Rank.csv into a RankID->ROWID dict,
#    rewrites Employee.csv's RankID column, writes a new file)

# 5. Re-import in upsert mode so existing rows get the column filled in
#    rather than duplicated
cat > upsert_config.json <<'JSON'
{"operation": "upsert", "find_by": "EmployeeID"}
JSON
catalyst ds:import build/csv/Employee_fk_remapped.csv --table Employee --config upsert_config.json

# 6. Fix the JOIN condition in code (db.py's ZcqlDB.caller_for, already done)
#    to compare against Rank.ROWID, not Rank.RankID
```

Two other console gotchas hit along the way, both already documented
above under Step 1: `ds:import` 409s on a filename already uploaded to the
Stratus bucket (copy the CSV under a new name to retry), and a table's
primary-key-like column needs `"Is Unique"` toggled on before it can be
used as an `upsert` `find_by` target.

## Converting the remaining relationships (Task 5 of the 2026-07-11 ROWID plan)

### Which relationships the demo actually needs

Cross-referencing `catalog.FOREIGN_KEYS` (40 relationships) against every
table `eval/questions.yaml` and the three Step 3 smoke-test queries join
through, the following 17 relationships are exercised by the existing eval
set + hardcoded paths. `Employee → Rank` (#37) is already converted; the
remaining 16 need conversion:

| # | Child → Parent | Used by |
|---|---|---|
| 2 | CaseMaster → Unit | eval Q3,5,6,18,27,29,30; smoke test |
| 3 | CaseMaster → CaseCategory | eval Q22 |
| 4 | CaseMaster → GravityOffence | eval Q8,29 |
| 5 | CaseMaster → CrimeHead | eval Q11 |
| 6 | CaseMaster → CrimeSubHead | eval Q2,3,4,17,19,30; smoke test |
| 7 | CaseMaster → CaseStatusMaster | eval Q7,21; RBAC smoke test |
| 8 | CaseMaster → Court | LLM can generate (not in eval set) |
| 9 | ComplainantDetails → CaseMaster | eval Q12,13,28 |
| 10 | ComplainantDetails → OccupationMaster | eval Q12 |
| 13 | ActSectionAssociation → CaseMaster | eval Q20 |
| 14 | ActSectionAssociation → Act | eval Q20 |
| 15 | ActSectionAssociation → Section | eval Q20 |
| 16 | Victim → CaseMaster | eval Q14 |
| 17 | Accused → CaseMaster | eval Q15 |
| 18 | ArrestSurrender → CaseMaster | eval Q16 |
| 34 | Unit → District | eval Q6,27,29 |

The remaining 23 relationships (e.g. ArrestSurrender → State/District/Unit/
Employee/Court/Accused, Section → Act, CrimeHeadActSection, CrimeSubHead →
CrimeHead, Court → District/State, District → State, Unit → UnitType/State,
Employee → District/Unit/Designation, ChargesheetDetails → Employee,
ComplainantDetails → ReligionMaster/CasteMaster) are not exercised by the
current eval set, but the LLM could generate queries that use them. Convert
them too if time permits — the automation script makes it mechanical; the
risk is the console step taking longer than expected for some tables.

### Per-relationship conversion procedure

For each relationship identified above, repeat this sequence
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
   Example, for `CaseMaster.PoliceStationID → Unit`:
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

### Re-verify Step 3's smoke tests

After every relationship in the list above is converted, re-run the three
curls from Step 3. All three should now execute past the
`ZCQL QUERY ERROR: No relationship between tables ...` failures seen
earlier in this session. If a curl still fails with that exact error,
a relationship was missed in the list above — check which table pair the
error names and add it to the conversion sequence.

Then run the Kannada parity spot-check (Step 4) and the live QuickML eval
(Step 5) as originally documented.

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
      -d "$(python -c 'import json,sys; print(json.dumps({"question":sys.argv[1]}))' "$q")" \
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
export QUICKML_ENDPOINT=... QUICKML_TOKEN=... QUICKML_ORG_ID=...
python -m eval.run_eval
```

Expected output: accuracy, hallucination_rate, p95_latency_s over the 30
questions. Record these numbers for the metrics slide — they're the real
headline evaluation numbers, everything before this point used `FakeLLM`.

## What "done" looks like

- Local implementation: the complete deterministic suite, static checks, and
  integrated module workflow pass; the exact count is reported by the latest
  `python -m pytest -q` run rather than this historical account note.
- Live Data Store row counts, FK/ROWID relationships, principal mapping, and
  authenticated smoke contracts: **pending current Catalyst verification**.
- Live 10-pair Kannada/English parity and the 30-question QuickML evaluation:
  **pending authenticated QuickML execution**.
- Audit, graph projection, MO index, scan, alert, and export contracts have
  deterministic local coverage; their Catalyst persistence and provider
  behavior still require the live smoke/runbook steps.

If any live step fails, fix the smallest affected adapter (`db.py` for ZCQL,
`translate.py`/`prompt.py` for language parity, `llm.py` for QuickML, or the
operational repositories for Data Store persistence), then rerun the complete
smoke contract. Do not substitute localhost results for a live gate.
