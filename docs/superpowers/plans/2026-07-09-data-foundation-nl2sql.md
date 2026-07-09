# Data Foundation + NL→SQL + Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the queryable substrate for the KSP Crime Copilot — the schema catalog, synthetic data, and a natural-language→SQL agent that returns role-scoped, DPDP-masked answers where every claim traces back to a `CrimeNo`.

**Architecture:** A schema catalog module is the single source of truth, mechanically checked against `Police_FIR_ER_Diagram.md` so no invented table or column can survive a test run. A user's question is turned into SQL by an LLM, then that SQL is *parsed* (not string-matched) and rejected unless it stays inside a deliberately narrow, ZCQL-portable subset: SELECT-only, allowlisted tables/columns/functions, no subqueries, anchored on `CaseMaster`. Only after the SQL passes validation does the RBAC layer rewrite it — injecting a `PoliceStationID IN (...)` scope derived from the caller's rank — and only then does it execute. Answers are composed by the LLM from the returned rows, and any `CrimeNo` in the answer text that is not present in those rows is treated as a hallucination and stripped.

**Tech Stack:** Python 3.9 (Zoho Catalyst function runtime), `sqlglot` for SQL parsing/rewriting, SQLite for local development and tests, Catalyst Data Store + ZCQL in production, QuickML LLM Serving (Qwen 2.5-14B) for SQL generation and answer composition, Zia for Kannada translation, `pytest` for tests.

## Global Constraints

These apply to every task. A task's requirements implicitly include this section.

- **Platform is Zoho Catalyst.** No third-party service may be introduced where a Catalyst service exists. `sqlglot` and `pytest` are libraries, not services — they are fine. A standalone vector DB, a non-Catalyst LLM host, or a hosted Postgres is not.
- **Schema is frozen.** Every table and column referenced in code must exist in `Police_FIR_ER_Diagram.md`. Task 1 enforces this with a test that reads that file. Do not add columns to make a query easier.
- **The ER document defines 26 tables**, not the 23 that `PLAN.md` §1 claims. It also names two tables in the Relationship Matrix — `Inv_OccuranceTime` and `inv_arrestsurrenderaccused` — that have **no column definitions anywhere in the document**. These two are excluded from the catalog and from all code. Do not invent columns for them.
- **`AuditLog` is the one table not in the ER document.** `PLAN.md` §1.5 mandates it. It is created by the DDL but deliberately kept **out of the query allowlist**, so the LLM can never read or write it.
- **SQL is SELECT-only, always.** Any generated statement that is not a single `SELECT` is rejected before execution, never sanitised or repaired.
- **The SQL subset is ZCQL-portable.** No subqueries, no CTEs, no window functions, no `UNION`. Allowed functions are exactly `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` and nothing else. This is not a style preference: Catalyst's ZCQL cannot express the rest, and code that works on SQLite but not on Catalyst fails `PLAN.md` §5's definition of done.
- **No date functions.** The prompt injects today's date as a literal and instructs the model to emit literal date strings (`'2026-01-09'`). This sidesteps every SQLite-vs-ZCQL date-function incompatibility.
- **All column references must be table-qualified** (`CaseMaster.CrimeNo`, never bare `CrimeNo`). Unqualified columns are a validation error. This removes ambiguity for both the validator and ZCQL.
- **Every non-aggregate query must project `CaseMaster.CrimeNo`.** Enforced by the validator. An answer path that cannot cite is not a valid answer path.
- **`CrimeNo` is exactly 18 digits**: 1-digit case category + 4-digit district + 4-digit unit + 4-digit year + 5-digit serial. The citation regex depends on this.
- **DPDP-sensitive columns** are `ComplainantDetails.CasteID`, `ComplainantDetails.ReligionID`, `CasteMaster.caste_master_name`, `ReligionMaster.ReligionName`. Master-table primary keys stay unrestricted so joins still work.
- **Rank hierarchy: lower number = higher authority** (per `Rank.Hierarchy` in the ER doc). Scope tiers: `<= 2` statewide, `3–4` own district, `>= 5` own unit. Sensitive columns require `<= 3` **and** a `GROUP BY`.
- **Python 3.9.** Catalyst's Python runtime. No `match` statements, no `X | Y` union syntax in annotations, no `dict[str, int]` at runtime without `from __future__ import annotations`.
- **All randomness is seeded.** Seed value `20260709`. The generator must be byte-for-byte reproducible; a test asserts this.

## File Structure

```
requirements.txt                      # sqlglot, pytest, requests
functions/crime_query/
  __init__.py
  catalog.py      # schema truth: tables, columns, FKs, sensitive cols, DDL emitter
  validate.py     # sqlglot allowlist validator → returns parsed AST
  rbac.py         # Caller, scope injection, sensitive-column policy, row redaction
  db.py           # SqliteDB + ZcqlDB: execute(), append_audit(), units_in_district()
  prompt.py       # schema description + live lookup values + today's date → prompt
  llm.py          # LLM protocol, FakeLLM (tests), QuickMLLLM (prod)
  agent.py        # orchestration: generate → validate → scope → execute → cite → audit
  translate.py    # Kannada detection + English pivot, IDs passed through verbatim
  main.py         # Catalyst function entrypoint
tools/
  gen_data.py     # seeded synthetic generator → SQLite + CSVs for Data Store import
eval/
  questions.yaml  # 30 labelled questions with gold SQL
  run_eval.py     # execution accuracy + hallucination rate + p95 latency
tests/
  test_catalog.py test_validate.py test_rbac.py test_db.py
  test_prompt.py test_agent.py test_translate.py test_gen_data.py
docs/catalyst-zcql-findings.md        # produced by Task 2
```

Each module has one responsibility and no upward dependencies: `catalog` depends on nothing; `validate` and `rbac` depend on `catalog`; `db` depends on `catalog`; `agent` depends on all of them. Tests mirror the module names.

---

### Task 1: Schema catalog, mechanically checked against the ER document

The catalog is the single source of truth every other module imports. Its test parses `Police_FIR_ER_Diagram.md` and fails if the catalog and the document ever disagree — that is the mechanism that enforces the "no invented schema" rule from `CLAUDE.md`.

**Files:**
- Create: `requirements.txt`
- Create: `functions/crime_query/__init__.py`
- Create: `functions/crime_query/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TABLES: Dict[str, Dict[str, str]]` — table name → {column name → SQL type as written in the ER doc}
  - `FOREIGN_KEYS: List[Tuple[str, str, str, str]]` — `(child_table, child_col, parent_table, parent_col)`
  - `SENSITIVE_COLUMNS: FrozenSet[str]` — dotted `"Table.Column"` strings
  - `CASE_SCOPED_TABLES: FrozenSet[str]` — tables whose rows belong to a case and therefore must be RBAC-scoped
  - `ALLOWED_FUNCTIONS: FrozenSet[str]`
  - `AUDIT_TABLE: str` (`"AuditLog"`), `AUDIT_COLUMNS: Dict[str, str]`
  - `def sqlite_ddl() -> str`
  - `def describe() -> str` — compact schema text for the LLM prompt

- [ ] **Step 1: Create `requirements.txt`**

```
sqlglot>=25,<27
pytest>=8,<9
requests>=2.31,<3
PyYAML>=6,<7
```

Install: `pip install -r requirements.txt`

- [ ] **Step 2: Write the failing conformance test**

This test is the whole point of the task. It reads the ER document, extracts every `## TableName` heading between `## Table Definitions` and `## Relationship Matrix`, merges the column tables underneath each heading (several tables are split across two markdown tables — `CaseMaster`, `Accused`, `UnitType`, `CaseCategory`, `CrimeHeadActSection`), and compares the result to `catalog.TABLES`.

Create `tests/test_catalog.py`:

```python
import re
from pathlib import Path

import pytest

from functions.crime_query import catalog

ER_DOC = Path(__file__).resolve().parents[1] / "Police_FIR_ER_Diagram.md"

# Named in the Relationship Matrix but never given column definitions.
UNDEFINED_IN_DOC = {"Inv_OccuranceTime", "inv_arrestsurrenderaccused"}


def parse_er_document(text):
    """Return {table_name: {column_name: type}} as literally written in the doc."""
    start = text.index("## Table Definitions")
    end = text.index("## Relationship Matrix")
    body = text[start:end]

    tables = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"^## (\w+)\s*$", line)
        if heading:
            name = heading.group(1)
            if name == "Table" or name == "Definitions":
                continue
            current = name
            tables.setdefault(current, {})
            continue
        if current is None or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        col, col_type = cells[0], cells[1]
        if not col or not col_type:
            continue
        if col == "Column Name" or set(col_type) <= {"-"}:
            continue
        tables[current][col] = col_type
    tables.pop("Table Definitions", None)
    return tables


@pytest.fixture(scope="module")
def doc_tables():
    return parse_er_document(ER_DOC.read_text(encoding="utf-8"))


def test_catalog_table_names_match_document(doc_tables):
    assert set(catalog.TABLES) == set(doc_tables)


def test_catalog_columns_match_document(doc_tables):
    for table, columns in doc_tables.items():
        assert catalog.TABLES[table] == columns, table


def test_undefined_tables_are_absent(doc_tables):
    assert UNDEFINED_IN_DOC.isdisjoint(catalog.TABLES)
    assert UNDEFINED_IN_DOC.isdisjoint(doc_tables)


def test_audit_table_is_not_queryable():
    assert catalog.AUDIT_TABLE not in catalog.TABLES


def test_sensitive_columns_exist_and_exclude_master_keys():
    for dotted in catalog.SENSITIVE_COLUMNS:
        table, column = dotted.split(".")
        assert column in catalog.TABLES[table], dotted
    assert "CasteMaster.caste_master_id" not in catalog.SENSITIVE_COLUMNS
    assert "ReligionMaster.ReligionID" not in catalog.SENSITIVE_COLUMNS


def test_foreign_keys_reference_real_columns():
    for child_t, child_c, parent_t, parent_c in catalog.FOREIGN_KEYS:
        assert child_c in catalog.TABLES[child_t], (child_t, child_c)
        assert parent_c in catalog.TABLES[parent_t], (parent_t, parent_c)


def test_case_scoped_tables_all_have_casemasterid():
    for table in catalog.CASE_SCOPED_TABLES:
        if table == "CaseMaster":
            assert "CaseMasterID" in catalog.TABLES[table]
        else:
            assert "CaseMasterID" in catalog.TABLES[table], table


def test_sqlite_ddl_creates_every_table_plus_audit():
    ddl = catalog.sqlite_ddl()
    for table in catalog.TABLES:
        assert f'CREATE TABLE IF NOT EXISTS "{table}"' in ddl
    assert f'CREATE TABLE IF NOT EXISTS "{catalog.AUDIT_TABLE}"' in ddl


def test_describe_mentions_every_table(doc_tables):
    described = catalog.describe()
    for table in doc_tables:
        assert table in described
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions'` (or `ImportError` on `catalog`).

- [ ] **Step 4: Create the package marker**

Create `functions/crime_query/__init__.py` as an empty file (zero bytes).

Also create `functions/__init__.py` as an empty file so `from functions.crime_query import catalog` resolves when pytest runs from the repo root.

- [ ] **Step 5: Write `catalog.py`**

Transcribe the ER document exactly — column names and types verbatim, including the lowercase oddities (`latitude`, `longitude`, `csdate`, `cstype`, `caste_master_id`, `caste_master_name`) and the misleading `CrimeSubHead.CrimeHeadName`, which holds the *sub*-head name such as `Murder`.

Create `functions/crime_query/catalog.py`:

```python
"""Single source of truth for the KSP crime schema.

Every table and column here is transcribed verbatim from
Police_FIR_ER_Diagram.md. tests/test_catalog.py re-reads that document and
fails if the two ever diverge. Never add a column to make a query easier.
"""

TABLES = {
    "CaseMaster": {
        "CaseMasterID": "INT",
        "CrimeNo": "VARCHAR",
        "CaseNo": "VARCHAR",
        "CrimeRegisteredDate": "DATE",
        "PolicePersonID": "INT",
        "PoliceStationID": "INT",
        "CaseCategoryID": "INT",
        "GravityOffenceID": "INT",
        "CrimeMajorHeadID": "INT",
        "CrimeMinorHeadID": "INT",
        "CaseStatusID": "INT",
        "CourtID": "INT",
        "IncidentFromDate": "DATETIME",
        "IncidentToDate": "DATETIME",
        "InfoReceivedPSDate": "DATETIME",
        "latitude": "DECIMAL",
        "longitude": "DECIMAL",
        "BriefFacts": "Nvarchar(Max)",
    },
    "ComplainantDetails": {
        "ComplainantID": "INT",
        "CaseMasterID": "INT",
        "ComplainantName": "VARCHAR",
        "AgeYear": "INT",
        "OccupationID": "INT",
        "ReligionID": "INT",
        "CasteID": "INT",
        "GenderID": "INT",
    },
    "ActSectionAssociation": {
        "CaseMasterID": "INT",
        "ActID": "INT",
        "SectionID": "INT",
        "ActOrderID": "INT",
        "SectionOrderID": "INT",
    },
    "Victim": {
        "VictimMasterID": "INT",
        "CaseMasterID": "INT",
        "VictimName": "VARCHAR",
        "AgeYear": "INT",
        "GenderID": "INT",
        "VictimPolice": "VARCHAR",
    },
    "Accused": {
        "AccusedMasterID": "INT",
        "CaseMasterID": "INT",
        "AccusedName": "VARCHAR",
        "AgeYear": "INT",
        "GenderID": "INT",
        "PersonID": "VARCHAR",
    },
    "ArrestSurrender": {
        "ArrestSurrenderID": "INT",
        "CaseMasterID": "INT",
        "ArrestSurrenderTypeID": "INT",
        "ArrestSurrenderDate": "DATE",
        "ArrestSurrenderStateId": "INT",
        "ArrestSurrenderDistrictId": "INT",
        "PoliceStationID": "INT",
        "IOID": "INT",
        "CourtID": "INT",
        "AccusedMasterID": "INT",
        "IsAccused": "BIT",
        "IsComplainantAccused": "BIT",
    },
    "Act": {
        "ActCode": "VARCHAR",
        "ActDescription": "VARCHAR",
        "ShortName": "VARCHAR",
        "Active": "BIT",
    },
    "Section": {
        "ActCode": "VARCHAR",
        "SectionCode": "VARCHAR",
        "SectionDescription": "VARCHAR",
        "Active": "BIT",
    },
    "CrimeHeadActSection": {
        "CrimeHeadID": "INT",
        "ActCode": "VARCHAR",
        "SectionCode": "VARCHAR",
    },
    "CrimeHead": {
        "CrimeHeadID": "INT",
        "CrimeGroupName": "VARCHAR",
        "Active": "BIT",
    },
    "CrimeSubHead": {
        "CrimeSubHeadID": "INT",
        "CrimeHeadID": "INT",
        "CrimeHeadName": "VARCHAR",
        "SeqID": "INT",
    },
    "CasteMaster": {
        "caste_master_id": "INT",
        "caste_master_name": "VARCHAR",
    },
    "ReligionMaster": {
        "ReligionID": "INT",
        "ReligionName": "VARCHAR",
    },
    "OccupationMaster": {
        "OccupationID": "INT",
        "OccupationName": "VARCHAR",
    },
    "CaseStatusMaster": {
        "CaseStatusID": "INT",
        "CaseStatusName": "VARCHAR",
    },
    "Court": {
        "CourtID": "INT",
        "CourtName": "VARCHAR",
        "DistrictID": "INT",
        "StateID": "INT",
        "Active": "BIT",
    },
    "District": {
        "DistrictID": "INT",
        "DistrictName": "VARCHAR",
        "StateID": "INT",
        "Active": "BIT",
    },
    "State": {
        "StateID": "INT",
        "StateName": "VARCHAR",
        "NationalityID": "INT",
        "Active": "BIT",
    },
    "Unit": {
        "UnitID": "INT",
        "UnitName": "VARCHAR",
        "TypeID": "INT",
        "ParentUnit": "INT",
        "NationalityID": "INT",
        "StateID": "INT",
        "DistrictID": "INT",
        "Active": "BIT",
    },
    "UnitType": {
        "UnitTypeID": "INT",
        "UnitTypeName": "VARCHAR",
        "CityDistState": "VARCHAR",
        "Hierarchy": "INT",
        "Active": "BIT",
    },
    "Rank": {
        "RankID": "INT",
        "RankName": "VARCHAR",
        "Hierarchy": "INT",
        "Active": "BIT",
    },
    "Designation": {
        "DesignationID": "INT",
        "DesignationName": "VARCHAR",
        "Active": "BIT",
        "SortOrder": "INT",
    },
    "Employee": {
        "EmployeeID": "INT",
        "DistrictID": "INT",
        "UnitID": "INT",
        "RankID": "INT",
        "DesignationID": "INT",
        "KGID": "VARCHAR",
        "FirstName": "VARCHAR",
        "EmployeeDOB": "DATE",
        "GenderID": "INT",
        "BloodGroupID": "INT",
        "PhysicallyChallenged": "BIT",
        "AppointmentDate": "DATE",
    },
    "CaseCategory": {
        "CaseCategoryID": "INT",
        "LookupValue": "VARCHAR",
    },
    "GravityOffence": {
        "GravityOffenceID": "INT",
        "LookupValue": "VARCHAR",
    },
    "ChargesheetDetails": {
        "CSID": "INT",
        "CaseMasterID": "INT",
        "csdate": "DATETIME",
        "cstype": "CHAR",
        "PolicePersonID": "INT",
    },
}

# (child_table, child_column, parent_table, parent_column)
FOREIGN_KEYS = [
    ("CaseMaster", "PolicePersonID", "Employee", "EmployeeID"),
    ("CaseMaster", "PoliceStationID", "Unit", "UnitID"),
    ("CaseMaster", "CaseCategoryID", "CaseCategory", "CaseCategoryID"),
    ("CaseMaster", "GravityOffenceID", "GravityOffence", "GravityOffenceID"),
    ("CaseMaster", "CrimeMajorHeadID", "CrimeHead", "CrimeHeadID"),
    ("CaseMaster", "CrimeMinorHeadID", "CrimeSubHead", "CrimeSubHeadID"),
    ("CaseMaster", "CaseStatusID", "CaseStatusMaster", "CaseStatusID"),
    ("CaseMaster", "CourtID", "Court", "CourtID"),
    ("ComplainantDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ComplainantDetails", "OccupationID", "OccupationMaster", "OccupationID"),
    ("ComplainantDetails", "ReligionID", "ReligionMaster", "ReligionID"),
    ("ComplainantDetails", "CasteID", "CasteMaster", "caste_master_id"),
    ("ActSectionAssociation", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ActSectionAssociation", "ActID", "Act", "ActCode"),
    ("ActSectionAssociation", "SectionID", "Section", "SectionCode"),
    ("Victim", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("Accused", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ArrestSurrender", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ArrestSurrender", "ArrestSurrenderStateId", "State", "StateID"),
    ("ArrestSurrender", "ArrestSurrenderDistrictId", "District", "DistrictID"),
    ("ArrestSurrender", "PoliceStationID", "Unit", "UnitID"),
    ("ArrestSurrender", "IOID", "Employee", "EmployeeID"),
    ("ArrestSurrender", "CourtID", "Court", "CourtID"),
    ("ArrestSurrender", "AccusedMasterID", "Accused", "AccusedMasterID"),
    ("Section", "ActCode", "Act", "ActCode"),
    ("CrimeHeadActSection", "CrimeHeadID", "CrimeHead", "CrimeHeadID"),
    ("CrimeHeadActSection", "ActCode", "Act", "ActCode"),
    ("CrimeSubHead", "CrimeHeadID", "CrimeHead", "CrimeHeadID"),
    ("Court", "DistrictID", "District", "DistrictID"),
    ("Court", "StateID", "State", "StateID"),
    ("District", "StateID", "State", "StateID"),
    ("Unit", "TypeID", "UnitType", "UnitTypeID"),
    ("Unit", "StateID", "State", "StateID"),
    ("Unit", "DistrictID", "District", "DistrictID"),
    ("Employee", "DistrictID", "District", "DistrictID"),
    ("Employee", "UnitID", "Unit", "UnitID"),
    ("Employee", "RankID", "Rank", "RankID"),
    ("Employee", "DesignationID", "Designation", "DesignationID"),
    ("ChargesheetDetails", "CaseMasterID", "CaseMaster", "CaseMasterID"),
    ("ChargesheetDetails", "PolicePersonID", "Employee", "EmployeeID"),
]

# DPDP-sensitive. Master-table primary keys are deliberately absent so joins work.
SENSITIVE_COLUMNS = frozenset({
    "ComplainantDetails.CasteID",
    "ComplainantDetails.ReligionID",
    "CasteMaster.caste_master_name",
    "ReligionMaster.ReligionName",
})

# Tables whose rows belong to a specific case, and therefore must be RBAC-scoped.
CASE_SCOPED_TABLES = frozenset({
    "CaseMaster",
    "ComplainantDetails",
    "ActSectionAssociation",
    "Victim",
    "Accused",
    "ArrestSurrender",
    "ChargesheetDetails",
})

ALLOWED_FUNCTIONS = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})

# Mandated by PLAN.md 1.5. Absent from TABLES on purpose: the LLM must never see it.
AUDIT_TABLE = "AuditLog"
AUDIT_COLUMNS = {
    "AuditID": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "EmployeeID": "INTEGER",
    "RankHierarchy": "INTEGER",
    "Question": "TEXT",
    "GeneratedSQL": "TEXT",
    "ExecutedSQL": "TEXT",
    "CrimeNos": "TEXT",
    "RowCount": "INTEGER",
    "Timestamp": "TEXT",
}

_SQLITE_TYPES = {
    "INT": "INTEGER",
    "BIT": "INTEGER",
    "DECIMAL": "REAL",
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "DATE": "TEXT",
    "DATETIME": "TEXT",
    "Nvarchar(Max)": "TEXT",
}


def sqlite_ddl():
    """CREATE TABLE statements for every schema table plus the audit log."""
    statements = []
    for table, columns in TABLES.items():
        cols = ",\n  ".join(
            '"{0}" {1}'.format(name, _SQLITE_TYPES[typ])
            for name, typ in columns.items()
        )
        statements.append(
            'CREATE TABLE IF NOT EXISTS "{0}" (\n  {1}\n);'.format(table, cols)
        )
    audit_cols = ",\n  ".join(
        '"{0}" {1}'.format(name, typ) for name, typ in AUDIT_COLUMNS.items()
    )
    statements.append(
        'CREATE TABLE IF NOT EXISTS "{0}" (\n  {1}\n);'.format(AUDIT_TABLE, audit_cols)
    )
    return "\n\n".join(statements)


def describe():
    """Compact schema text for the NL->SQL prompt."""
    lines = []
    for table, columns in TABLES.items():
        lines.append("{0}({1})".format(table, ", ".join(columns)))
    lines.append("")
    lines.append("Foreign keys:")
    for child_t, child_c, parent_t, parent_c in FOREIGN_KEYS:
        lines.append(
            "  {0}.{1} -> {2}.{3}".format(child_t, child_c, parent_t, parent_c)
        )
    return "\n".join(lines)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python -m pytest tests/test_catalog.py -v`
Expected: PASS — 9 passed.

If `test_catalog_columns_match_document` fails, the parser and the transcription disagree. Trust the document: read the failing table's rows in `Police_FIR_ER_Diagram.md` and fix `catalog.py`, never the other way round.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt functions/__init__.py functions/crime_query/__init__.py \
        functions/crime_query/catalog.py tests/test_catalog.py
git commit -m "feat: schema catalog checked against the ER document"
```

---

### Task 2: Catalyst / ZCQL capability spike

This is a spike, not a TDD task: it produces a findings document and one decision, not code. It is placed second because `PLAN.md` §3 lists "ZCQL can't express needed joins/aggregates" as the highest-impact early risk — if ZCQL cannot join four tables, the whole NL→SQL design changes to precomputed denormalised views, and finding that out after Task 9 wastes a week.

Nothing in Tasks 3–11 depends on the outcome, because the SQL subset in the Global Constraints is already conservative enough to run on either backend. The spike either confirms that choice or forces Task 12 to add denormalised views.

**Files:**
- Create: `docs/catalyst-zcql-findings.md`
- Create: `functions/crime_query/` Catalyst scaffolding (generated by the CLI — do not hand-write `catalyst-config.json`)

**Interfaces:**
- Consumes: `catalog.TABLES` from Task 1 (to know what to create in the Data Store).
- Produces: a written answer to each question below, and a `Decision:` line at the top of the findings doc reading either `SQL subset as specified is ZCQL-portable` or `Denormalised views required — see Task 12`.

- [ ] **Step 1: Scaffold a Catalyst project with the CLI**

Do not hand-write the Catalyst config files; the CLI owns their schema and it changes between versions.

```bash
npm install -g zcatalyst-cli
catalyst login
catalyst init            # choose: Functions; runtime Python; name: crime_query
catalyst functions:add   # confirm crime_query, type: Advanced I/O
```

Record the exact Python version the CLI offers. The Global Constraints assume 3.9 — if the CLI offers something newer, update the Global Constraints line and note it in the findings doc.

- [ ] **Step 2: Create three tables in the Data Store by hand**

In the Catalyst console, create `CaseMaster`, `Unit`, and `District` with the columns from `catalog.TABLES`. Insert about twenty rows by hand — enough to make a join return something.

- [ ] **Step 3: Run each probe query in the console's ZCQL editor and record the result**

Run each of these verbatim and write down whether it succeeded, and the exact error text if not.

```sql
-- P1 three-table join (the everyday case: "burglaries in Bengaluru East")
SELECT CaseMaster.CrimeNo FROM CaseMaster
  LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
  LEFT JOIN District ON Unit.DistrictID = District.DistrictID
  WHERE District.DistrictName = 'Bengaluru City'

-- P2 aggregate with GROUP BY and ORDER BY
SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster
  LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
  GROUP BY Unit.UnitName ORDER BY COUNT(CaseMaster.CaseMasterID) DESC

-- P3 IN with a literal list (this is how RBAC scoping is injected)
SELECT CaseMaster.CrimeNo FROM CaseMaster
  WHERE CaseMaster.PoliceStationID IN (1, 2, 3)

-- P4 date range on a literal string (no date functions anywhere)
SELECT CaseMaster.CrimeNo FROM CaseMaster
  WHERE CaseMaster.CrimeRegisteredDate >= '2026-01-09'
    AND CaseMaster.CrimeRegisteredDate <= '2026-07-09'

-- P5 four-table join (the worst realistic case)
SELECT CaseMaster.CrimeNo FROM CaseMaster
  LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
  LEFT JOIN District ON Unit.DistrictID = District.DistrictID
  LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
  WHERE CrimeSubHead.CrimeHeadName = 'Burglary'

-- P6 LIMIT
SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 5
```

- [ ] **Step 4: Record how the Python SDK executes ZCQL and returns rows**

Write a throwaway Advanced I/O function that runs P1 and prints the result, then read the response shape. Note in the findings doc:

- the exact import and call (expected to be `zcatalyst_sdk.initialize()` then `app.zcql().execute_query(sql)`, but **verify** — do not trust this plan)
- whether rows come back as `[{"CaseMaster": {"CrimeNo": "1..."}}]` (table-nested) or flat `[{"CrimeNo": "1..."}]`. This determines the row-flattening code in Task 6's `ZcqlDB`.
- how `NULL` and `DECIMAL` values are typed in the returned dicts
- what error type is raised on a malformed query

- [ ] **Step 5: Write `docs/catalyst-zcql-findings.md`**

Use exactly this structure:

```markdown
# Catalyst / ZCQL capability findings

**Date:**
**Catalyst CLI version:**
**Python runtime offered:**

**Decision:** <"SQL subset as specified is ZCQL-portable" | "Denormalised views required — see Task 12">

## Probe results

| Probe | Query | Result | Error text if failed |
|---|---|---|---|
| P1 | 3-table join | | |
| P2 | GROUP BY + ORDER BY aggregate | | |
| P3 | IN with literal list | | |
| P4 | date range on string literal | | |
| P5 | 4-table join | | |
| P6 | LIMIT | | |

## SDK behaviour

- ZCQL call signature:
- Row shape returned:
- NULL / DECIMAL typing:
- Error type on malformed query:

## Consequences

- Max join depth supported:
- Constraints to add to validate.py beyond the Global Constraints:
- If P3 failed, RBAC scoping must change from `IN (...)` to: <write the alternative>
```

- [ ] **Step 6: If P3 or P5 failed, stop and escalate**

P3 failing breaks RBAC scoping. P5 failing breaks the everyday query. Either one means the architecture in `PLAN.md` §1.1 needs revisiting before more code is written — raise it rather than working around it silently. `PLAN.md` §3's mitigation (precomputed denormalised views at ingestion) is the pre-agreed fallback; adopting it means Task 3 also emits a `CaseFlat` view and Task 4's allowlist targets that view.

- [ ] **Step 7: Commit**

```bash
git add docs/catalyst-zcql-findings.md
git commit -m "docs: record Catalyst ZCQL capability findings"
```

---

### Task 3: Seeded synthetic data generator

Builds a SQLite database and a directory of CSVs (the import format for Catalyst Data Store) from `catalog.sqlite_ddl()`. Determinism matters more than realism: the eval set in Task 10 has gold SQL whose expected row counts only hold if the generator is reproducible.

Three signals are deliberately seeded, because later plans depend on them and because `PLAN.md` §3 warns that forecasts and clusters are meaningless on uniformly random data:

1. **A trend** — Two-Wheeler Theft in Bengaluru East roughly triples over the final 90 days (feeds trend detection and forecasting).
2. **A spatial cluster** — 60 burglaries inside a ~200 m radius in Bengaluru East (feeds DBSCAN hotspots).
3. **A name-variant person** — one accused appears in 4 cases across 3 stations under 4 spellings (feeds entity resolution and the hidden-link demo beat).

> **Amended during execution (2026-07-09).** Code review found two of these three signals were not actually delivered by the code written below, and the shipped implementation in `tools/gen_data.py` differs from it. Read the committed file, not these snippets, if the two disagree.
>
> - **Signal 3 was broken.** `variant_targets = sorted({...})[:4]` picks the four lowest `CaseMasterID`s, which land in only **two** stations. Worse, `test_name_variants_span_three_stations` filtered on `AccusedName`, and because `"Ravi"` is in `FIRST_NAMES` and `"Kumar"` is in `LAST_NAMES`, the generator independently produces ~47 unrelated "Ravi Kumar" rows across all 12 stations — they satisfied the `>= 3 stations` assertion on their own, so the test could not detect the defect. The shipped code selects via a `_pick_variant_cases()` helper that takes one case per station, and the test filters on `Accused.PersonID = 'A9'` (the seeded rows' marker). A companion test asserts that matching by name alone returns strictly more than 4 rows, proving the first test is not a tautology.
> - **Signal 2 was weaker than advertised.** `rng.gauss(0, 0.0015)` is a ~165 m sigma, so only 23 of 60 "clustered" burglaries fell within a true 200 m radius; the loose 0.005° bounding box in the test hid it. The shipped code rejection-samples against a hard `CLUSTER_RADIUS_DEG = 0.0018` (~200 m), making the radius a guarantee rather than a three-sigma hope, and the test measures Euclidean degree distance.
>
> The lesson generalises: **a test that filters on a value the generator also produces by chance asserts nothing.** Seeded fixtures need a marker column (`PersonID = 'A9'`), not a recognisable value.

**Files:**
- Create: `tools/gen_data.py`
- Test: `tests/test_gen_data.py`

**Interfaces:**
- Consumes: `catalog.TABLES`, `catalog.sqlite_ddl()` (Task 1).
- Produces:
  - `def build(sqlite_path, csv_dir=None, seed=20260709) -> Dict[str, int]` — writes the DB, optionally the CSVs, returns `{table_name: row_count}`
  - `SEED = 20260709`, `TOTAL_CASES = 5000`
  - `RAVI_SPELLINGS: List[str]` — the four name variants, so Task 10's eval and later entity-resolution work can assert on them

- [ ] **Step 1: Write the failing test**

Create `tests/test_gen_data.py`:

```python
import hashlib
import sqlite3

import pytest

from tools import gen_data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("db")
    counts = gen_data.build(str(out / "crime.db"), csv_dir=str(out / "csv"))
    conn = sqlite3.connect(str(out / "crime.db"))
    conn.row_factory = sqlite3.Row
    yield conn, counts, out
    conn.close()


def test_case_count_is_exact(built):
    _, counts, _ = built
    assert counts["CaseMaster"] == gen_data.TOTAL_CASES


def test_every_catalog_table_is_populated(built):
    _, counts, _ = built
    from functions.crime_query import catalog
    for table in catalog.TABLES:
        assert counts[table] > 0, table


def test_crimeno_is_eighteen_digits(built):
    conn, _, _ = built
    rows = conn.execute('SELECT CrimeNo FROM "CaseMaster" LIMIT 50').fetchall()
    for row in rows:
        assert len(row["CrimeNo"]) == 18, row["CrimeNo"]
        assert row["CrimeNo"].isdigit()


def test_caseno_is_last_nine_digits_of_crimeno(built):
    conn, _, _ = built
    rows = conn.execute('SELECT CrimeNo, CaseNo FROM "CaseMaster" LIMIT 50').fetchall()
    for row in rows:
        assert row["CaseNo"] == row["CrimeNo"][-9:]


def test_no_orphan_child_rows(built):
    conn, _, _ = built
    from functions.crime_query import catalog
    case_ids = {r[0] for r in conn.execute('SELECT CaseMasterID FROM "CaseMaster"')}
    for table in sorted(catalog.CASE_SCOPED_TABLES - {"CaseMaster"}):
        orphans = [
            r[0]
            for r in conn.execute('SELECT CaseMasterID FROM "{0}"'.format(table))
            if r[0] not in case_ids
        ]
        assert orphans == [], table


def test_two_wheeler_theft_trend_is_seeded(built):
    conn, _, _ = built
    sql = """
        SELECT COUNT(*) FROM "CaseMaster"
        JOIN "CrimeSubHead" ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
        WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft'
          AND CaseMaster.PoliceStationID = 1
          AND CaseMaster.CrimeRegisteredDate >= ?
    """
    recent = conn.execute(sql, ("2026-04-01",)).fetchone()[0]
    earlier = conn.execute(
        sql.replace(">= ?", "< ?"), ("2026-04-01",)
    ).fetchone()[0]
    # 90 days of uplift must outweigh the preceding 640 days of background rate.
    assert recent > earlier


def test_burglary_cluster_is_tight(built):
    conn, _, _ = built
    rows = conn.execute(
        """
        SELECT latitude, longitude FROM "CaseMaster"
        JOIN "CrimeSubHead" ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
        WHERE CrimeSubHead.CrimeHeadName = 'Burglary'
          AND CaseMaster.PoliceStationID = 1
        """
    ).fetchall()
    lat0, lon0 = gen_data.CLUSTER_CENTRE
    tight = [
        r for r in rows
        if abs(r["latitude"] - lat0) < 0.005 and abs(r["longitude"] - lon0) < 0.005
    ]
    assert len(tight) >= 60


def test_name_variants_span_three_stations(built):
    conn, _, _ = built
    placeholders = ",".join("?" for _ in gen_data.RAVI_SPELLINGS)
    rows = conn.execute(
        """
        SELECT Accused.AccusedName, CaseMaster.PoliceStationID
        FROM "Accused"
        JOIN "CaseMaster" ON Accused.CaseMasterID = CaseMaster.CaseMasterID
        WHERE Accused.AccusedName IN ({0})
        """.format(placeholders),
        gen_data.RAVI_SPELLINGS,
    ).fetchall()
    assert {r["AccusedName"] for r in rows} == set(gen_data.RAVI_SPELLINGS)
    assert len({r["PoliceStationID"] for r in rows}) >= 3


def test_sensitive_columns_are_populated_not_null(built):
    conn, _, _ = built
    null_castes = conn.execute(
        'SELECT COUNT(*) FROM "ComplainantDetails" WHERE CasteID IS NULL'
    ).fetchone()[0]
    assert null_castes == 0


def test_generation_is_byte_for_byte_reproducible(tmp_path):
    def digest(path):
        counts = gen_data.build(str(path / "crime.db"), csv_dir=str(path / "csv"))
        assert counts
        parts = []
        for csv_file in sorted((path / "csv").iterdir()):
            parts.append(hashlib.sha256(csv_file.read_bytes()).hexdigest())
        return parts

    first = digest(tmp_path / "a")
    second = digest(tmp_path / "b")
    assert first == second
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_gen_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'`.

- [ ] **Step 3: Write `tools/gen_data.py`**

Create `tools/__init__.py` as an empty file, then `tools/gen_data.py`:

```python
"""Seeded synthetic data generator for the KSP crime schema.

Deterministic by construction: every random draw comes from one seeded
random.Random instance, and rows are inserted in a fixed order. The eval
suite's gold SQL depends on this.
"""
import argparse
import csv
import datetime as dt
import os
import random
import sqlite3

from functions.crime_query import catalog

SEED = 20260709
TOTAL_CASES = 5000
BASE_CASES = 4820
TREND_CASES = 120       # Two-Wheeler Theft uplift, Bengaluru East, last 90 days
CLUSTER_CASES = 60      # tight burglary cluster for DBSCAN

START_DATE = dt.date(2024, 7, 1)
END_DATE = dt.date(2026, 6, 30)
TREND_START = dt.date(2026, 4, 1)

CLUSTER_CENTRE = (12.9850, 77.6600)
RAVI_SPELLINGS = ["Ravi Kumar", "Ravi K", "R. Kumar", "Ravikumar"]

STATES = [(1, "Karnataka", 1, 1)]
DISTRICTS = [(1, "Bengaluru City", 1, 1), (2, "Mysuru", 1, 1), (3, "Belagavi", 1, 1)]
DISTRICT_CENTRES = {1: (12.9716, 77.5946), 2: (12.2958, 76.6394), 3: (15.8497, 74.4977)}

UNIT_TYPES = [(1, "Police Station", "City", 3, 1), (2, "Circle Office", "District", 2, 1),
              (3, "District HQ", "District", 1, 1)]
UNIT_NAMES = [
    (1, "Bengaluru East", 1), (2, "Bengaluru West", 1),
    (3, "Bengaluru South", 1), (4, "Bengaluru North", 1),
    (5, "Mysuru North", 2), (6, "Mysuru South", 2),
    (7, "Nazarbad", 2), (8, "Krishnaraja", 2),
    (9, "Belagavi City", 3), (10, "Belagavi Rural", 3),
    (11, "Tilakwadi", 3), (12, "Camp", 3),
]

RANKS = [(1, "DGP", 1, 1), (2, "IGP", 2, 1), (3, "SP", 3, 1),
         (4, "Inspector", 4, 1), (5, "Sub-Inspector", 5, 1), (6, "Constable", 6, 1)]
DESIGNATIONS = [(1, "SHO", 1, 1), (2, "Investigating Officer", 1, 2),
                (3, "Beat Constable", 1, 3), (4, "Superintendent of Police", 1, 4)]

CRIME_HEADS = [(1, "Crimes Against Body", 1), (2, "Crimes Against Property", 1),
               (3, "Crimes Against Women", 1), (4, "Economic Offences", 1)]
CRIME_SUBHEADS = [
    (1, 1, "Murder", 1), (2, 1, "Attempt to Murder", 2), (3, 1, "Hurt", 3),
    (4, 2, "Burglary", 4), (5, 2, "Theft", 5), (6, 2, "Two-Wheeler Theft", 6),
    (7, 2, "Robbery", 7), (8, 2, "Dacoity", 8),
    (9, 3, "Assault on Woman", 9), (10, 3, "Dowry Harassment", 10),
    (11, 4, "Cheating", 11), (12, 4, "Criminal Breach of Trust", 12),
]

ACTS = [("IPC", "Indian Penal Code, 1860", "IPC", 1),
        ("NDPS", "Narcotic Drugs and Psychotropic Substances Act, 1985", "NDPS", 1),
        ("POCSO", "Protection of Children from Sexual Offences Act, 2012", "POCSO", 1),
        ("MVA", "Motor Vehicles Act, 1988", "MVA", 1)]
SECTIONS = [
    ("IPC", "302", "Punishment for murder", 1),
    ("IPC", "307", "Attempt to murder", 1),
    ("IPC", "323", "Punishment for voluntarily causing hurt", 1),
    ("IPC", "354", "Assault on woman with intent to outrage her modesty", 1),
    ("IPC", "379", "Punishment for theft", 1),
    ("IPC", "380", "Theft in dwelling house", 1),
    ("IPC", "392", "Punishment for robbery", 1),
    ("IPC", "395", "Punishment for dacoity", 1),
    ("IPC", "406", "Punishment for criminal breach of trust", 1),
    ("IPC", "420", "Cheating and dishonestly inducing delivery of property", 1),
    ("IPC", "457", "Lurking house-trespass by night", 1),
    ("IPC", "498A", "Husband or relative subjecting woman to cruelty", 1),
    ("NDPS", "20", "Contravention in relation to cannabis plant", 1),
    ("POCSO", "4", "Punishment for penetrative sexual assault", 1),
    ("MVA", "184", "Driving dangerously", 1),
]
SUBHEAD_SECTIONS = {
    1: [("IPC", "302")], 2: [("IPC", "307")], 3: [("IPC", "323")],
    4: [("IPC", "457"), ("IPC", "380")], 5: [("IPC", "379")],
    6: [("IPC", "379")], 7: [("IPC", "392")], 8: [("IPC", "395")],
    9: [("IPC", "354")], 10: [("IPC", "498A")],
    11: [("IPC", "420")], 12: [("IPC", "406")],
}

CASE_STATUSES = [(1, "Under Investigation"), (2, "Charge Sheeted"), (3, "Closed")]
CASE_CATEGORIES = [(1, "FIR"), (3, "UDR"), (4, "PAR"), (8, "Zero FIR")]
GRAVITY = [(1, "Heinous"), (2, "Non-Heinous")]
HEINOUS_SUBHEADS = {1, 2, 7, 8, 9}  # Murder, Attempt, Robbery, Dacoity, Assault on Woman

CASTES = [(1, "General"), (2, "Scheduled Caste"), (3, "Scheduled Tribe"),
          (4, "Other Backward Class"), (5, "Not Recorded")]
RELIGIONS = [(1, "Hindu"), (2, "Muslim"), (3, "Christian"), (4, "Jain"), (5, "Other")]
OCCUPATIONS = [(1, "Farmer"), (2, "Government Employee"), (3, "Private Employee"),
               (4, "Business"), (5, "Student"), (6, "Daily Wage Labourer"),
               (7, "Homemaker"), (8, "Unemployed")]

FIRST_NAMES = ["Ravi", "Suresh", "Manjunath", "Lakshmi", "Girish", "Anitha", "Prakash",
               "Shobha", "Nagaraj", "Vinod", "Kavitha", "Basavaraj", "Deepa", "Mahesh",
               "Sunitha", "Harish", "Roopa", "Chandru", "Geetha", "Srinivas"]
LAST_NAMES = ["Kumar", "Gowda", "Reddy", "Shetty", "Patil", "Hegde", "Rao", "Naik",
              "Murthy", "Bhat", "Desai", "Kulkarni"]

BRIEF_FACTS = {
    1: "Deceased found with stab injuries near {place}. Motive suspected to be a prior dispute.",
    2: "Accused attacked complainant with a sharp weapon near {place}; victim hospitalised.",
    3: "Quarrel over parking near {place} escalated; complainant sustained blunt injuries.",
    4: "House lock broken between {t1} and {t2} at {place}; gold ornaments and cash taken.",
    5: "Mobile phone and wallet stolen from complainant at {place} in a crowded market.",
    6: "Two-wheeler parked outside {place} found missing; no CCTV coverage at the spot.",
    7: "Two persons on a motorcycle snatched a chain from complainant near {place}.",
    8: "Armed group entered premises at {place} and decamped with valuables.",
    9: "Accused outraged the modesty of the complainant near {place}; witnesses present.",
    10: "Complainant harassed by in-laws for additional dowry at her residence in {place}.",
    11: "Accused induced complainant to transfer funds on a false investment promise.",
    12: "Entrusted goods at {place} were misappropriated by the accused.",
}
PLACES = ["the main market", "a residential layout", "the bus terminus", "an industrial estate",
          "the temple street", "a commercial complex", "the ring road junction", "a park"]


def _iso(date):
    return date.isoformat()


def _dt(date, hour, minute):
    return "{0} {1:02d}:{2:02d}:00".format(date.isoformat(), hour, minute)


def _crime_no(category_id, district_id, unit_id, year, serial):
    return "{0}{1:04d}{2:04d}{3:04d}{4:05d}".format(
        category_id, district_id, unit_id, year, serial
    )


def _employees():
    rows = []
    emp_id = 1
    for unit_id, _name, district_id in UNIT_NAMES:
        plan = [(4, 1)] + [(5, 2)] * 2 + [(6, 3)] * 5
        for rank_id, desig_id in plan:
            rows.append((emp_id, district_id, unit_id, rank_id, desig_id,
                         "KGID{0:05d}".format(emp_id), FIRST_NAMES[emp_id % len(FIRST_NAMES)],
                         "1985-01-01", 1, 1, 0, "2010-06-01"))
            emp_id += 1
    for district_id, _name, _s, _a in DISTRICTS:
        first_unit = district_id * 4 - 3
        rows.append((emp_id, district_id, first_unit, 3, 4, "KGID{0:05d}".format(emp_id),
                     "SP", "1975-01-01", 1, 1, 0, "2000-06-01"))
        emp_id += 1
    rows.append((emp_id, 1, 1, 1, 4, "KGID{0:05d}".format(emp_id), "DGP",
                 "1968-01-01", 1, 1, 0, "1992-06-01"))
    return rows


def _make_case(rng, case_id, unit_id, district_id, subhead_id, reg_date, lat, lon, serials):
    category_id = 1 if rng.random() < 0.92 else rng.choice([3, 4, 8])
    year = reg_date.year
    key = (unit_id, category_id, year)
    serials[key] = serials.get(key, 0) + 1
    crime_no = _crime_no(category_id, district_id, unit_id, year, serials[key])

    officers = [e for e in EMPLOYEES if e[2] == unit_id and e[3] in (4, 5)]
    officer = officers[case_id % len(officers)][0]

    head_id = next(s[1] for s in CRIME_SUBHEADS if s[0] == subhead_id)
    gravity = 1 if subhead_id in HEINOUS_SUBHEADS else 2
    status = rng.choices([1, 2, 3], weights=[5, 3, 2])[0]
    court_id = district_id

    incident = reg_date - dt.timedelta(days=rng.randint(0, 2))
    hour = rng.choices(range(24), weights=[3] * 6 + [1] * 12 + [3] * 6)[0]
    minute = rng.choice([0, 15, 30, 45])
    from_dt = _dt(incident, hour, minute)
    to_dt = _dt(incident, min(hour + 1, 23), minute)
    info_dt = _dt(reg_date, min(hour + 2, 23), minute)

    facts = BRIEF_FACTS[subhead_id].format(
        place=rng.choice(PLACES), t1="{0:02d}:00".format(hour), t2="{0:02d}:00".format(min(hour + 4, 23))
    )
    return (case_id, crime_no, crime_no[-9:], _iso(reg_date), officer, unit_id,
            category_id, gravity, head_id, subhead_id, status, court_id,
            from_dt, to_dt, info_dt, round(lat, 6), round(lon, 6), facts)


EMPLOYEES = _employees()


def build(sqlite_path, csv_dir=None, seed=SEED):
    rng = random.Random(seed)
    if os.path.exists(sqlite_path):
        os.remove(sqlite_path)
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.executescript(catalog.sqlite_ddl())

    data = {
        "State": STATES,
        "District": DISTRICTS,
        "UnitType": UNIT_TYPES,
        "Unit": [(uid, name, 1, None, 1, 1, did, 1) for uid, name, did in UNIT_NAMES],
        "Rank": RANKS,
        "Designation": DESIGNATIONS,
        "Employee": EMPLOYEES,
        "CrimeHead": CRIME_HEADS,
        "CrimeSubHead": CRIME_SUBHEADS,
        "CaseStatusMaster": CASE_STATUSES,
        "CaseCategory": CASE_CATEGORIES,
        "GravityOffence": GRAVITY,
        "Court": [(d[0], "{0} District Court".format(d[1]), d[0], 1, 1) for d in DISTRICTS],
        "CasteMaster": CASTES,
        "ReligionMaster": RELIGIONS,
        "OccupationMaster": OCCUPATIONS,
        "Act": ACTS,
        "Section": SECTIONS,
        "CrimeHeadActSection": sorted({
            (head, act, sec)
            for sub_id, head, _n, _q in CRIME_SUBHEADS
            for act, sec in SUBHEAD_SECTIONS[sub_id]
        }),
    }

    span = (END_DATE - START_DATE).days
    serials = {}
    cases, complainants, victims, accused_rows, arrests, act_secs, chargesheets = \
        [], [], [], [], [], [], []

    plan = []
    for _ in range(BASE_CASES):
        unit_id = rng.randint(1, 12)
        subhead_id = rng.choices(
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            weights=[1, 2, 12, 14, 18, 10, 6, 1, 6, 5, 8, 4],
        )[0]
        reg = START_DATE + dt.timedelta(days=rng.randint(0, span))
        plan.append((unit_id, subhead_id, reg, None))
    for _ in range(TREND_CASES):
        offset = rng.randint(0, (END_DATE - TREND_START).days)
        plan.append((1, 6, TREND_START + dt.timedelta(days=offset), None))
    for _ in range(CLUSTER_CASES):
        reg = START_DATE + dt.timedelta(days=rng.randint(0, span))
        plan.append((1, 4, reg, CLUSTER_CENTRE))

    plan.sort(key=lambda p: (p[2], p[0], p[1]))

    comp_id = victim_id = accused_id = arrest_id = cs_id = 1
    for index, (unit_id, subhead_id, reg, forced_centre) in enumerate(plan, start=1):
        district_id = next(d for u, _n, d in UNIT_NAMES if u == unit_id)
        if forced_centre:
            lat = forced_centre[0] + rng.gauss(0, 0.0015)
            lon = forced_centre[1] + rng.gauss(0, 0.0015)
        else:
            clat, clon = DISTRICT_CENTRES[district_id]
            lat, lon = clat + rng.gauss(0, 0.05), clon + rng.gauss(0, 0.05)
        case = _make_case(rng, index, unit_id, district_id, subhead_id, reg, lat, lon, serials)
        cases.append(case)

        name = "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES))
        complainants.append((comp_id, index, name, rng.randint(18, 70),
                             rng.randint(1, 8), rng.randint(1, 5), rng.randint(1, 5),
                             rng.choice([1, 2])))
        comp_id += 1

        for _ in range(rng.randint(0, 2)):
            victims.append((victim_id, index,
                            "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)),
                            rng.randint(5, 80), rng.choice([1, 2]), "0"))
            victim_id += 1

        n_accused = rng.randint(1, 3)
        case_accused = []
        for slot in range(n_accused):
            accused_rows.append((accused_id, index,
                                 "{0} {1}".format(rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)),
                                 rng.randint(18, 60), rng.choice([1, 2]),
                                 "A{0}".format(slot + 1)))
            case_accused.append(accused_id)
            accused_id += 1

        if rng.random() < 0.4:
            io = [e for e in EMPLOYEES if e[2] == unit_id and e[3] == 5][0][0]
            arrests.append((arrest_id, index, 1,
                            _iso(reg + dt.timedelta(days=rng.randint(1, 30))),
                            1, district_id, unit_id, io, district_id,
                            case_accused[0], 1, 0))
            arrest_id += 1

        for order, (act, sec) in enumerate(SUBHEAD_SECTIONS[subhead_id], start=1):
            act_secs.append((index, act, sec, 1, order))

        status = case[10]
        if status == 2:
            chargesheets.append((cs_id, index,
                                 _dt(reg + dt.timedelta(days=rng.randint(30, 90)), 10, 0),
                                 "A", case[4]))
            cs_id += 1

    # Seeded name variants: one person, four spellings, at least three stations.
    variant_targets = sorted(
        {c[0] for c in cases if c[5] in (1, 2, 5)}
    )[:: max(1, len(cases) // 400)][:4]
    assert len(variant_targets) == 4, "not enough candidate cases for name variants"
    for spelling, case_id in zip(RAVI_SPELLINGS, variant_targets):
        accused_rows.append((accused_id, case_id, spelling, 31, 1, "A9"))
        accused_id += 1

    data["CaseMaster"] = cases
    data["ComplainantDetails"] = complainants
    data["Victim"] = victims
    data["Accused"] = accused_rows
    data["ArrestSurrender"] = arrests
    data["ActSectionAssociation"] = act_secs
    data["ChargesheetDetails"] = chargesheets

    counts = {}
    for table in catalog.TABLES:
        rows = data[table]
        columns = list(catalog.TABLES[table])
        placeholders = ",".join("?" for _ in columns)
        quoted = ",".join('"{0}"'.format(c) for c in columns)
        conn.executemany(
            'INSERT INTO "{0}" ({1}) VALUES ({2})'.format(table, quoted, placeholders),
            rows,
        )
        counts[table] = len(rows)
    conn.commit()

    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
        for table in sorted(catalog.TABLES):
            path = os.path.join(csv_dir, "{0}.csv".format(table))
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle, lineterminator="\n")
                writer.writerow(list(catalog.TABLES[table]))
                writer.writerows(data[table])

    conn.close()
    return counts


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic KSP crime data.")
    parser.add_argument("--sqlite", default="build/crime.db")
    parser.add_argument("--csv", default="build/csv")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    counts = build(args.sqlite, args.csv, args.seed)
    for table, count in sorted(counts.items()):
        print("{0:24s} {1:>6d}".format(table, count))


if __name__ == "__main__":
    main()
```

Two details that will bite if changed: `plan.sort(...)` before the insert loop is what makes `CaseMasterID` deterministic regardless of the order the three case groups were appended, and `EMPLOYEES` is computed at import time from a pure function so it never consumes the seeded RNG.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_gen_data.py -v`
Expected: PASS — 10 passed. The reproducibility test takes ~10 s because it builds the dataset twice.

If `test_name_variants_span_three_stations` fails with the assertion in `build`, the stride expression picked fewer than four candidates — replace the slice with `variant_targets = sorted({c[0] for c in cases if c[5] in (1, 2, 5)})[:4]` and re-check that those four cases span three stations.

- [ ] **Step 5: Generate the working dataset and eyeball it**

```bash
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
sqlite3 build/crime.db "SELECT CrimeNo, CrimeRegisteredDate, BriefFacts FROM CaseMaster LIMIT 3;"
```

Expected: three rows, 18-digit crime numbers, readable narratives.

- [ ] **Step 6: Commit**

```bash
echo "build/" >> .gitignore
git add .gitignore tools/__init__.py tools/gen_data.py tests/test_gen_data.py
git commit -m "feat: seeded synthetic data generator with trend, cluster and name variants"
```

---

### Task 4: SQL validator (the hallucination guard)

`PLAN.md` §3 rates "NL→SQL hallucinates columns/values" as the highest-likelihood risk. This module is the mitigation. It parses the LLM's SQL into an AST and rejects anything outside the allowlist — it never rewrites, repairs, or string-matches. Rejection produces a message specific enough to feed back into a re-prompt.

The rules, in order of what they defend against:

| Rule | Defends against |
|---|---|
| exactly one statement, and it is a `SELECT` | stacked statements, any write |
| no `Subquery`, `With`, `Union`, `Window` | ZCQL incompatibility |
| every table in `catalog.TABLES` | invented tables; reading `AuditLog` |
| every column qualified, and resolves in its table | invented columns |
| every function in `catalog.ALLOWED_FUNCTIONS` | `load_extension`, date-function drift |
| if any case-scoped table is present, `CaseMaster` is present | RBAC having nothing to anchor to |
| non-aggregate queries project `CaseMaster.CrimeNo` | uncitable answers |
| `LIMIT` present and `<= 200` | runaway result sets |

The `CaseMaster`-anchor rule is what makes RBAC tractable: every case-scoped table joins back to `CaseMaster`, so scoping `CaseMaster.PoliceStationID` scopes the whole query. Queries touching only lookup tables (`SELECT District.DistrictName FROM District`) need no anchor and get none.

**Files:**
- Create: `functions/crime_query/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `catalog.TABLES`, `catalog.ALLOWED_FUNCTIONS`, `catalog.CASE_SCOPED_TABLES` (Task 1).
- Produces:
  - `class ValidationError(Exception)` — `str(err)` is the re-prompt hint
  - `MAX_LIMIT = 200`
  - `def validate(sql: str) -> sqlglot.exp.Select` — returns the parsed AST with `LIMIT` enforced, or raises
  - `def table_aliases(select: sqlglot.exp.Select) -> Dict[str, str]` — alias-or-name → real table name; reused by `rbac.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_validate.py`:

```python
import pytest
import sqlglot

from functions.crime_query import validate
from functions.crime_query.validate import ValidationError

GOOD = (
    'SELECT CaseMaster.CrimeNo FROM CaseMaster '
    "WHERE CaseMaster.CrimeRegisteredDate >= '2026-01-01' LIMIT 50"
)


def test_valid_query_returns_a_select_ast():
    ast = validate.validate(GOOD)
    assert isinstance(ast, sqlglot.exp.Select)


def test_limit_is_added_when_missing():
    ast = validate.validate('SELECT CaseMaster.CrimeNo FROM CaseMaster')
    assert 'LIMIT {0}'.format(validate.MAX_LIMIT) in ast.sql()


def test_limit_above_cap_is_clamped():
    ast = validate.validate('SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 5000')
    assert 'LIMIT {0}'.format(validate.MAX_LIMIT) in ast.sql()


def test_aggregate_query_needs_no_crimeno():
    ast = validate.validate('SELECT COUNT(*) FROM CaseMaster')
    assert isinstance(ast, sqlglot.exp.Select)


def test_join_and_group_by_are_allowed():
    sql = (
        'SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster '
        'LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID '
        'GROUP BY Unit.UnitName ORDER BY n DESC LIMIT 10'
    )
    assert validate.validate(sql) is not None


def test_lookup_only_query_needs_no_casemaster_anchor():
    assert validate.validate('SELECT District.DistrictName FROM District') is not None


def test_table_aliases_resolves_aliases_and_bare_names():
    ast = validate.validate(
        'SELECT cm.CrimeNo FROM CaseMaster cm '
        'LEFT JOIN Unit ON cm.PoliceStationID = Unit.UnitID LIMIT 5'
    )
    assert validate.table_aliases(ast) == {"cm": "CaseMaster", "Unit": "Unit"}


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ('DELETE FROM CaseMaster', 'SELECT'),
        ('UPDATE CaseMaster SET CrimeNo = 1', 'SELECT'),
        ('DROP TABLE CaseMaster', 'SELECT'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster; DROP TABLE Unit', 'one statement'),
        ('SELECT AuditLog.Question FROM AuditLog', 'unknown table'),
        ('SELECT CaseMaster.PhoneNumber FROM CaseMaster', 'unknown column'),
        ('SELECT Vehicle.PlateNo FROM Vehicle', 'unknown table'),
        ('SELECT CrimeNo FROM CaseMaster', 'must be qualified'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster WHERE CaseMasterID IN '
         '(SELECT Victim.CaseMasterID FROM Victim)', 'subquer'),
        ('WITH x AS (SELECT CaseMaster.CrimeNo FROM CaseMaster) SELECT x.CrimeNo FROM x',
         'not allowed'),
        ('SELECT CaseMaster.CrimeNo FROM CaseMaster UNION SELECT Unit.UnitName FROM Unit',
         'not allowed'),
        ("SELECT UPPER(CaseMaster.CrimeNo) FROM CaseMaster", 'function'),
        ("SELECT DATE(CaseMaster.CrimeRegisteredDate) FROM CaseMaster", 'function'),
        ('SELECT Victim.VictimName FROM Victim LIMIT 5', 'CaseMaster'),
        ('SELECT CaseMaster.BriefFacts FROM CaseMaster LIMIT 5', 'CrimeNo'),
    ],
)
def test_rejections(sql, fragment):
    with pytest.raises(ValidationError) as excinfo:
        validate.validate(sql)
    assert fragment.lower() in str(excinfo.value).lower()


def test_error_message_names_the_offending_identifier():
    with pytest.raises(ValidationError) as excinfo:
        validate.validate('SELECT CaseMaster.PhoneNumber FROM CaseMaster')
    assert 'PhoneNumber' in str(excinfo.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.validate'`.

- [ ] **Step 3: Write `validate.py`**

Create `functions/crime_query/validate.py`:

```python
"""Parse-and-reject validator for LLM-generated SQL.

Never repairs, never rewrites for correctness, never string-matches. Anything
outside the allowlist raises ValidationError whose message is designed to be
fed straight back to the model as a re-prompt hint.
"""
import sqlglot
from sqlglot import exp

from . import catalog

MAX_LIMIT = 200

_BANNED_NODES = (
    (exp.Subquery, "subqueries are not allowed"),
    (exp.With, "common table expressions are not allowed"),
    (exp.Union, "UNION is not allowed"),
    (exp.Except, "EXCEPT is not allowed"),
    (exp.Intersect, "INTERSECT is not allowed"),
    (exp.Window, "window functions are not allowed"),
)

_ALLOWED_FUNC_TYPES = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)


class ValidationError(Exception):
    """Raised when generated SQL leaves the allowlist. Message is a re-prompt hint."""


def _parse(sql):
    try:
        statements = sqlglot.parse(sql)
    except Exception as err:  # sqlglot raises several unrelated types
        raise ValidationError("could not parse SQL: {0}".format(err))
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise ValidationError(
            "exactly one statement is allowed; got {0}".format(len(statements))
        )
    root = statements[0]
    if not isinstance(root, exp.Select):
        raise ValidationError(
            "only SELECT statements are allowed; got {0}".format(type(root).__name__.upper())
        )
    return root


def table_aliases(select):
    """Map every alias-or-name used in the query to its real catalog table name."""
    mapping = {}
    for table in select.find_all(exp.Table):
        name = table.name
        alias = table.alias_or_name
        mapping[alias] = name
    return mapping


def _check_banned(select):
    for node_type, message in _BANNED_NODES:
        if select.find(node_type) is not None:
            raise ValidationError(message)


def _check_tables(select):
    for table in select.find_all(exp.Table):
        if table.name not in catalog.TABLES:
            raise ValidationError("unknown table: {0}".format(table.name))


def _check_columns(select, aliases):
    for column in select.find_all(exp.Column):
        if not column.table:
            raise ValidationError(
                "column {0} must be qualified with its table name".format(column.name)
            )
        if column.table not in aliases:
            raise ValidationError(
                "unknown table alias: {0}".format(column.table)
            )
        table = aliases[column.table]
        if column.name not in catalog.TABLES[table]:
            raise ValidationError(
                "unknown column: {0}.{1}".format(table, column.name)
            )


def _check_functions(select):
    for node in select.find_all(exp.Func):
        if isinstance(node, _ALLOWED_FUNC_TYPES):
            continue
        name = getattr(node, "sql_name", lambda: type(node).__name__)()
        raise ValidationError(
            "function not allowed: {0}; permitted functions are {1}".format(
                name, ", ".join(sorted(catalog.ALLOWED_FUNCTIONS))
            )
        )


def _check_anchor(select, aliases):
    used = set(aliases.values())
    if used & catalog.CASE_SCOPED_TABLES and "CaseMaster" not in used:
        raise ValidationError(
            "queries touching case data must include CaseMaster so the result "
            "can be role-scoped; join back to CaseMaster on CaseMasterID"
        )


def _is_aggregate(select):
    if select.args.get("group"):
        return True
    return any(isinstance(node, _ALLOWED_FUNC_TYPES) for node in select.find_all(exp.Func))


def _check_citation(select, aliases):
    if _is_aggregate(select):
        return
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            if column.table in aliases and aliases[column.table] == "CaseMaster" \
                    and column.name == "CrimeNo":
                return
    raise ValidationError(
        "every row-level query must select CaseMaster.CrimeNo so the answer can be cited"
    )


def _enforce_limit(select):
    limit = select.args.get("limit")
    if limit is None:
        return select.limit(MAX_LIMIT)
    try:
        value = int(limit.expression.name)
    except (AttributeError, ValueError):
        raise ValidationError("LIMIT must be an integer literal")
    if value < 1 or value > MAX_LIMIT:
        return select.limit(MAX_LIMIT)
    return select


def validate(sql):
    """Return the parsed SELECT with LIMIT enforced, or raise ValidationError."""
    select = _parse(sql)
    _check_banned(select)
    _check_tables(select)
    aliases = table_aliases(select)
    _check_columns(select, aliases)
    _check_functions(select)
    _check_anchor(select, aliases)
    _check_citation(select, aliases)
    return _enforce_limit(select)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_validate.py -v`
Expected: PASS — 22 passed (7 named tests + 15 parametrised rejections + the message test).

Two failures are likely on first run and both are sqlglot-version behaviour, not logic errors:

- `WITH ... SELECT` may parse with `exp.Select` at the root and the `With` in `args["with"]`, so `find(exp.With)` must search the whole tree — it does, because `find` walks `args`. If it still slips through, assert on `select.args.get("with")` explicitly.
- `DROP TABLE` may raise inside `sqlglot.parse` rather than returning a non-`Select`. Both paths raise `ValidationError`, but the message differs; the test asserts on `'SELECT'` appearing in the message, so widen `_parse`'s parse-failure message to `"could not parse SQL (only SELECT statements are allowed): ..."` if needed.

- [ ] **Step 5: Commit**

```bash
git add functions/crime_query/validate.py tests/test_validate.py
git commit -m "feat: allowlist SQL validator rejecting invented schema and non-ZCQL syntax"
```

---

### Task 5: RBAC scoping and DPDP masking

Takes the validated AST and rewrites it for the caller. Two independent concerns:

**Scope.** The caller's rank hierarchy decides which stations they may see. The predicate is always `CaseMaster.PoliceStationID IN (...)`, ANDed onto the existing `WHERE`. Because `CaseMaster` has no `DistrictID` column, district scoping is done by resolving the district's units up front and emitting them as a literal list — no extra join, and ZCQL-portable (probe P3 in Task 2).

**Sensitive columns.** `PLAN.md` §1.7's socio-demographic diagram says caste and religion are aggregate-only, for authorised roles. Concretely:

- A sensitive column anywhere outside the `SELECT` projection (a `WHERE`, a `JOIN ... ON`, an `ORDER BY`) is **rejected** — filtering on caste leaks it even when it is not displayed. The one exception is `GROUP BY` for an authorised caller.
- A sensitive column in the projection is **allowed but redacted** to `[MASKED]` in the returned rows — unless the caller is authorised (`Hierarchy <= 3`) *and* the query has a `GROUP BY`, in which case the real values pass through. Redaction happens in the serving function, per `PLAN.md` §1.5, never in the UI.

Precedence matters: `WHERE a OR b` plus a scope predicate must become `WHERE (a OR b) AND scope`, not `WHERE a OR (b AND scope)`. There is a test for exactly that, because getting it wrong is a silent authorisation bypass.

**Files:**
- Create: `functions/crime_query/rbac.py`
- Test: `tests/test_rbac.py`

**Interfaces:**
- Consumes: `catalog.SENSITIVE_COLUMNS`, `validate.table_aliases`, `validate.ValidationError`.
- Produces:
  - `class Caller` — frozen dataclass: `employee_id: int`, `unit_id: int`, `district_id: int`, `rank_hierarchy: int`
  - `class RbacError(Exception)`
  - `STATEWIDE_MAX_HIERARCHY = 2`, `DISTRICT_MAX_HIERARCHY = 4`, `SENSITIVE_MAX_HIERARCHY = 3`
  - `def allowed_units(caller: Caller, db) -> Optional[List[int]]` — `None` means statewide
  - `def apply(select, caller: Caller, units: Optional[List[int]]) -> Tuple[str, List[str]]` — returns `(sql_text, redact_keys)`
  - `def redact_rows(rows: List[dict], redact_keys: List[str]) -> List[dict]`
  - `MASK = "[MASKED]"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rbac.py`:

```python
import pytest

from functions.crime_query import rbac, validate
from functions.crime_query.rbac import Caller, RbacError

CONSTABLE = Caller(employee_id=9, unit_id=3, district_id=1, rank_hierarchy=6)
INSPECTOR = Caller(employee_id=1, unit_id=1, district_id=1, rank_hierarchy=4)
SP = Caller(employee_id=97, unit_id=1, district_id=1, rank_hierarchy=3)
DGP = Caller(employee_id=100, unit_id=1, district_id=1, rank_hierarchy=1)


class FakeDB:
    def units_in_district(self, district_id):
        return {1: [1, 2, 3, 4], 2: [5, 6, 7, 8], 3: [9, 10, 11, 12]}[district_id]


def scoped(sql, caller, db=None):
    ast = validate.validate(sql)
    units = rbac.allowed_units(caller, db or FakeDB())
    return rbac.apply(ast, caller, units)


def test_constable_is_scoped_to_own_unit():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', CONSTABLE)
    assert 'IN (3)' in sql.replace(' ', ' ')


def test_inspector_is_scoped_to_district_units():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', INSPECTOR)
    assert 'IN (1, 2, 3, 4)' in sql


def test_dgp_gets_no_unit_predicate():
    sql, _ = scoped('SELECT CaseMaster.CrimeNo FROM CaseMaster', DGP)
    assert 'PoliceStationID' not in sql


def test_scope_uses_the_casemaster_alias():
    sql, _ = scoped(
        'SELECT cm.CrimeNo FROM CaseMaster cm', CONSTABLE
    )
    assert 'cm.PoliceStationID IN (3)' in sql


def test_existing_or_condition_is_parenthesised_before_anding_scope():
    sql, _ = scoped(
        'SELECT CaseMaster.CrimeNo FROM CaseMaster '
        "WHERE CaseMaster.CaseStatusID = 1 OR CaseMaster.CaseStatusID = 2",
        CONSTABLE,
    )
    assert '(' in sql.split('WHERE', 1)[1].split('AND')[0]
    # The bypass this guards against: OR binding looser than AND.
    assert 'OR CaseMaster.CaseStatusID = 2 AND' not in sql


def test_lookup_only_query_is_not_scoped():
    sql, _ = scoped('SELECT District.DistrictName FROM District', CONSTABLE)
    assert 'PoliceStationID' not in sql


def test_sensitive_column_in_where_is_rejected_for_everyone():
    for caller in (CONSTABLE, INSPECTOR, SP, DGP):
        with pytest.raises(RbacError):
            scoped(
                'SELECT CaseMaster.CrimeNo FROM CaseMaster '
                'LEFT JOIN ComplainantDetails '
                'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
                'WHERE ComplainantDetails.CasteID = 2',
                caller,
            )


def test_sensitive_column_in_projection_is_redacted_for_constable():
    sql, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        CONSTABLE,
    )
    assert redact == ["CasteID"]
    assert 'CasteID' in sql  # still selected; the value is masked after execution


def test_sp_aggregate_over_sensitive_column_is_not_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
        'GROUP BY ComplainantDetails.CasteID',
        SP,
    )
    assert redact == []


def test_sp_row_level_sensitive_column_is_still_redacted():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        SP,
    )
    assert redact == ["CasteID"]


def test_inspector_aggregate_over_sensitive_column_is_redacted():
    _, redact = scoped(
        'SELECT ComplainantDetails.ReligionID, COUNT(CaseMaster.CaseMasterID) FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID '
        'GROUP BY ComplainantDetails.ReligionID',
        INSPECTOR,
    )
    assert redact == ["ReligionID"]


def test_redact_key_follows_the_alias():
    _, redact = scoped(
        'SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID AS caste FROM CaseMaster '
        'LEFT JOIN ComplainantDetails '
        'ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID',
        CONSTABLE,
    )
    assert redact == ["caste"]


def test_redact_rows_replaces_only_named_keys():
    rows = [{"CrimeNo": "1" * 18, "CasteID": 2}]
    out = rbac.redact_rows(rows, ["CasteID"])
    assert out == [{"CrimeNo": "1" * 18, "CasteID": rbac.MASK}]
    assert rows[0]["CasteID"] == 2  # input not mutated


def test_allowed_units_tiers():
    db = FakeDB()
    assert rbac.allowed_units(DGP, db) is None
    assert rbac.allowed_units(SP, db) == [1, 2, 3, 4]
    assert rbac.allowed_units(INSPECTOR, db) == [1, 2, 3, 4]
    assert rbac.allowed_units(CONSTABLE, db) == [3]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_rbac.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.rbac'`.

- [ ] **Step 3: Write `rbac.py`**

Create `functions/crime_query/rbac.py`:

```python
"""Role scoping and DPDP masking, applied to a validated AST.

Scope is a PoliceStationID IN (...) predicate ANDed onto the query. Sensitive
columns are rejected outside the projection and masked inside it, unless the
caller is senior enough and the query is an aggregate.
"""
from dataclasses import dataclass

from sqlglot import exp

from . import catalog
from .validate import table_aliases

STATEWIDE_MAX_HIERARCHY = 2   # DGP, IGP
DISTRICT_MAX_HIERARCHY = 4    # SP, Inspector
SENSITIVE_MAX_HIERARCHY = 3   # SP and above
MASK = "[MASKED]"


class RbacError(Exception):
    """Raised when the caller may not run this query at all."""


@dataclass(frozen=True)
class Caller:
    employee_id: int
    unit_id: int
    district_id: int
    rank_hierarchy: int  # lower number = higher authority


def allowed_units(caller, db):
    """Station IDs the caller may see. None means statewide."""
    if caller.rank_hierarchy <= STATEWIDE_MAX_HIERARCHY:
        return None
    if caller.rank_hierarchy <= DISTRICT_MAX_HIERARCHY:
        return db.units_in_district(caller.district_id)
    return [caller.unit_id]


def _projection_column_nodes(select):
    nodes = set()
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            nodes.add(id(column))
    return nodes


def _group_column_nodes(select):
    group = select.args.get("group")
    if group is None:
        return set()
    return {id(column) for column in group.find_all(exp.Column)}


def _dotted(column, aliases):
    return "{0}.{1}".format(aliases[column.table], column.name)


def _output_key(projection):
    """The dict key a row will carry for this projection."""
    if isinstance(projection, exp.Alias):
        return projection.alias
    return projection.name


def _sensitive_policy(select, caller, aliases):
    """Return the list of output keys to redact, or raise RbacError."""
    projection_nodes = _projection_column_nodes(select)
    group_nodes = _group_column_nodes(select)
    is_grouped = select.args.get("group") is not None
    authorised = caller.rank_hierarchy <= SENSITIVE_MAX_HIERARCHY and is_grouped

    for column in select.find_all(exp.Column):
        if _dotted(column, aliases) not in catalog.SENSITIVE_COLUMNS:
            continue
        if id(column) in projection_nodes:
            continue
        if authorised and id(column) in group_nodes:
            continue
        raise RbacError(
            "caste and religion may only appear in the selected columns of an "
            "aggregate query; {0} was used to filter or sort".format(
                _dotted(column, aliases)
            )
        )

    if authorised:
        return []

    redact = []
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            if _dotted(column, aliases) in catalog.SENSITIVE_COLUMNS:
                redact.append(_output_key(projection))
                break
    return redact


def _casemaster_alias(aliases):
    for alias, table in aliases.items():
        if table == "CaseMaster":
            return alias
    return None


def apply(select, caller, units):
    """Rewrite the validated AST for this caller. Returns (sql_text, redact_keys)."""
    aliases = table_aliases(select)
    redact = _sensitive_policy(select, caller, aliases)

    scoped = select
    alias = _casemaster_alias(aliases)
    if alias is not None and units is not None:
        literals = [exp.Literal.number(unit) for unit in units]
        predicate = exp.In(
            this=exp.column("PoliceStationID", table=alias),
            expressions=literals,
        )
        # Select.where() routes through exp.and_, which parenthesises a bare OR
        # on the left. That parenthesisation is the authorisation boundary.
        scoped = select.where(predicate, copy=True)

    return scoped.sql(), redact


def redact_rows(rows, redact_keys):
    """Replace the value of every redacted key. Does not mutate the input."""
    if not redact_keys:
        return rows
    masked = []
    for row in rows:
        copy = dict(row)
        for key in redact_keys:
            if key in copy:
                copy[key] = MASK
        masked.append(copy)
    return masked
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_rbac.py -v`
Expected: PASS — 14 passed.

If `test_existing_or_condition_is_parenthesised_before_anding_scope` fails, sqlglot's `Select.where()` is not parenthesising the existing `OR`. Do not paper over it with string manipulation — build the condition explicitly instead:

```python
    existing = select.args.get("where")
    if existing is not None:
        combined = exp.And(this=exp.Paren(this=existing.this), expression=predicate)
        scoped = select.copy()
        scoped.set("where", exp.Where(this=combined))
    else:
        scoped = select.where(predicate, copy=True)
```

- [ ] **Step 5: Commit**

```bash
git add functions/crime_query/rbac.py tests/test_rbac.py
git commit -m "feat: rank-based query scoping and DPDP column masking"
```

---

### Task 6: Database layer and append-only audit log

Two backends behind one small surface: `SqliteDB` for development, tests, and the eval harness; `ZcqlDB` for Catalyst. No environment-variable switching inside the library — the choice is made once, in `main.py`. That keeps every test free of global state.

`append_audit` is append-only by convention and by API: there is no update or delete method, and `AuditLog` is absent from `catalog.TABLES` so no generated SQL can reach it.

The exact ZCQL call signature and row shape come from Task 2's findings document. If Task 2 recorded table-nested rows (`{"CaseMaster": {"CrimeNo": ...}}`), `_flatten` below is already correct; if it recorded flat rows, `_flatten` becomes the identity and its test changes accordingly.

**Files:**
- Create: `functions/crime_query/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `catalog.AUDIT_TABLE`, `catalog.AUDIT_COLUMNS`, `catalog.sqlite_ddl()`.
- Produces:
  - `class SqliteDB` — `__init__(self, path)`, `execute(sql) -> List[dict]`, `units_in_district(district_id) -> List[int]`, `lookup(table, column) -> List[str]`, `caller_for(employee_id) -> Optional[rbac.Caller]`, `append_audit(**fields) -> None`, `close()`
  - `class ZcqlDB` — same methods, backed by `zcatalyst_sdk`
  - Both satisfy the informal `DB` interface that `rbac.allowed_units`, `prompt.build_prompt`, and `agent.answer` depend on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_db.py`:

```python
import pytest

from functions.crime_query import db as db_module
from functions.crime_query.rbac import Caller
from tools import gen_data


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_execute_returns_list_of_dicts(db):
    rows = db.execute('SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 3')
    assert len(rows) == 3
    assert set(rows[0]) == {"CrimeNo"}


def test_execute_returns_empty_list_not_none(db):
    rows = db.execute(
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.CrimeRegisteredDate = '1900-01-01'"
    )
    assert rows == []


def test_units_in_district(db):
    assert db.units_in_district(1) == [1, 2, 3, 4]
    assert db.units_in_district(3) == [9, 10, 11, 12]


def test_lookup_returns_distinct_sorted_values(db):
    heads = db.lookup("CrimeSubHead", "CrimeHeadName")
    assert "Two-Wheeler Theft" in heads
    assert heads == sorted(set(heads))


def test_caller_for_reads_rank_hierarchy_from_schema(db):
    caller = db.caller_for(1)
    assert isinstance(caller, Caller)
    assert caller.employee_id == 1
    assert caller.unit_id == 1
    assert caller.district_id == 1
    assert caller.rank_hierarchy == 4  # Inspector, seeded first in every unit


def test_caller_for_unknown_employee_is_none(db):
    assert db.caller_for(999999) is None


def test_append_audit_writes_a_row(db):
    before = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    db.append_audit(
        EmployeeID=1,
        RankHierarchy=4,
        Question="how many burglaries",
        GeneratedSQL="SELECT COUNT(*) FROM CaseMaster",
        ExecutedSQL="SELECT COUNT(*) FROM CaseMaster",
        CrimeNos="",
        RowCount=1,
        Timestamp="2026-07-09T10:00:00",
    )
    after = db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]
    assert after == before + 1


def test_audit_log_is_not_reachable_through_execute(db):
    # execute() is the path generated SQL takes; AuditLog is not in the catalog,
    # so validate() rejects it long before this. This asserts the second line of
    # defence: db.execute refuses the audit table by name.
    with pytest.raises(db_module.DBError):
        db.execute('SELECT AuditLog.Question FROM AuditLog')


def test_flatten_unwraps_table_nested_rows():
    nested = [{"CaseMaster": {"CrimeNo": "1"}, "Unit": {"UnitName": "Bengaluru East"}}]
    assert db_module.ZcqlDB._flatten(nested) == [
        {"CrimeNo": "1", "UnitName": "Bengaluru East"}
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.db'`.

- [ ] **Step 3: Write `db.py`**

Create `functions/crime_query/db.py`:

```python
"""Two backends, one surface. SqliteDB for dev/test/eval, ZcqlDB for Catalyst.

The backend is chosen once, in main.py. Nothing here reads the environment.
"""
import sqlite3

from . import catalog
from .rbac import Caller


class DBError(Exception):
    """Raised when a query is refused or the backend fails."""


def _reject_audit_table(sql):
    if catalog.AUDIT_TABLE.lower() in sql.lower():
        raise DBError(
            "{0} is not queryable through execute()".format(catalog.AUDIT_TABLE)
        )


class SqliteDB(object):
    """Local backend. Also used by the eval harness."""

    def __init__(self, path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql):
        _reject_audit_table(sql)
        return self.execute_raw(sql)

    def execute_raw(self, sql, params=()):
        try:
            cursor = self._conn.execute(sql, params)
        except sqlite3.Error as err:
            raise DBError(str(err))
        return [dict(row) for row in cursor.fetchall()]

    def units_in_district(self, district_id):
        rows = self.execute_raw(
            'SELECT UnitID FROM "Unit" WHERE DistrictID = ? ORDER BY UnitID',
            (district_id,),
        )
        return [row["UnitID"] for row in rows]

    def lookup(self, table, column):
        rows = self.execute_raw(
            'SELECT DISTINCT "{0}" AS v FROM "{1}" ORDER BY "{0}"'.format(column, table)
        )
        return [row["v"] for row in rows if row["v"] is not None]

    def caller_for(self, employee_id):
        rows = self.execute_raw(
            'SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, '
            'Rank.Hierarchy AS RankHierarchy '
            'FROM "Employee" JOIN "Rank" ON Employee.RankID = Rank.RankID '
            'WHERE Employee.EmployeeID = ?',
            (employee_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return Caller(
            employee_id=row["EmployeeID"],
            unit_id=row["UnitID"],
            district_id=row["DistrictID"],
            rank_hierarchy=row["RankHierarchy"],
        )

    def append_audit(self, **fields):
        columns = [c for c in catalog.AUDIT_COLUMNS if c != "AuditID"]
        values = [fields[c] for c in columns]
        placeholders = ",".join("?" for _ in columns)
        quoted = ",".join('"{0}"'.format(c) for c in columns)
        self._conn.execute(
            'INSERT INTO "{0}" ({1}) VALUES ({2})'.format(
                catalog.AUDIT_TABLE, quoted, placeholders
            ),
            values,
        )
        self._conn.commit()

    def close(self):
        self._conn.close()


class ZcqlDB(object):
    """Catalyst Data Store backend. Call signature confirmed in Task 2's findings."""

    def __init__(self, app):
        self._zcql = app.zcql()
        self._datastore = app.datastore()

    @staticmethod
    def _flatten(rows):
        """ZCQL returns rows keyed by table name; the rest of the code wants flat dicts."""
        flat = []
        for row in rows:
            merged = {}
            for value in row.values():
                merged.update(value)
            flat.append(merged)
        return flat

    def execute(self, sql):
        _reject_audit_table(sql)
        return self.execute_raw(sql)

    def execute_raw(self, sql):
        try:
            return self._flatten(self._zcql.execute_query(sql))
        except Exception as err:
            raise DBError(str(err))

    def units_in_district(self, district_id):
        rows = self.execute_raw(
            "SELECT Unit.UnitID FROM Unit WHERE Unit.DistrictID = {0}".format(
                int(district_id)
            )
        )
        return sorted(row["UnitID"] for row in rows)

    def lookup(self, table, column):
        rows = self.execute_raw(
            "SELECT {0}.{1} FROM {0}".format(table, column)
        )
        values = {row[column] for row in rows if row.get(column) is not None}
        return sorted(values)

    def caller_for(self, employee_id):
        rows = self.execute_raw(
            "SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, "
            "Rank.Hierarchy FROM Employee "
            "LEFT JOIN Rank ON Employee.RankID = Rank.RankID "
            "WHERE Employee.EmployeeID = {0}".format(int(employee_id))
        )
        if not rows:
            return None
        row = rows[0]
        return Caller(
            employee_id=row["EmployeeID"],
            unit_id=row["UnitID"],
            district_id=row["DistrictID"],
            rank_hierarchy=row["Hierarchy"],
        )

    def append_audit(self, **fields):
        # Data Store row insert, not ZCQL: ZCQL is SELECT-only on Catalyst too.
        try:
            self._datastore.table(catalog.AUDIT_TABLE).insert_row(fields)
        except Exception as err:
            raise DBError("audit write failed: {0}".format(err))

    def close(self):
        pass
```

`append_audit` writes through the Data Store row API rather than ZCQL, because ZCQL is SELECT-only on Catalyst too. The exact method name (`insert_row`) is the one signature Task 2 cannot confirm without a live table; Task 12 Step 3 verifies it against the SDK before deployment. It raises `DBError` rather than swallowing the failure — an audit write that silently no-ops would make `PLAN.md`'s "immutable audit trail" a false claim.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS — 9 passed.

If `test_caller_for_reads_rank_hierarchy_from_schema` returns `rank_hierarchy == 5`, the generator's per-unit staffing plan changed order. Read `_employees()` in `tools/gen_data.py` and fix the expected value, not the generator.

- [ ] **Step 5: Commit**

```bash
git add functions/crime_query/db.py tests/test_db.py
git commit -m "feat: sqlite and zcql backends with append-only audit log"
```

---

### Task 7: NL→SQL prompt builder

`PLAN.md` §1.1 is explicit: the prompt carries the schema **and the actual lookup values**, so the model maps "murder" to `CrimeSubHead.CrimeHeadName = 'Murder'` and "Bengaluru East" to the right `Unit`, instead of guessing a value that does not exist in the data. Lookup values are read live from the database, so they can never drift from what is stored.

Today's date goes in as a literal, and the rules forbid date functions. "In the last 6 months" therefore becomes `>= '2026-01-09'`, computed by the model from the date it was given. This is the single change that makes the same SQL run on both SQLite and ZCQL.

**Files:**
- Create: `functions/crime_query/prompt.py`
- Test: `tests/test_prompt.py`

**Interfaces:**
- Consumes: `catalog.describe()`, `catalog.ALLOWED_FUNCTIONS`, `db.lookup()`.
- Produces:
  - `LOOKUP_FIELDS: List[Tuple[str, str]]` — the (table, column) pairs whose values are injected
  - `def lookup_values(db) -> Dict[str, List[str]]` — keyed `"Table.Column"`
  - `def build_prompt(question: str, db, today: datetime.date) -> str`
  - `def build_answer_prompt(question: str, rows: List[dict], sql: str) -> str`
  - `def repair_prompt(previous_sql: str, error: str, original_prompt: str) -> str` — the one re-prompt after a `ValidationError`
  - `MAX_ROWS_IN_ANSWER_PROMPT = 40`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompt.py`:

```python
import datetime as dt

import pytest

from functions.crime_query import db as db_module
from functions.crime_query import prompt
from tools import gen_data

TODAY = dt.date(2026, 7, 9)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_lookup_values_include_real_data_values(db):
    values = prompt.lookup_values(db)
    assert "Two-Wheeler Theft" in values["CrimeSubHead.CrimeHeadName"]
    assert "Bengaluru East" in values["Unit.UnitName"]
    assert "Bengaluru City" in values["District.DistrictName"]
    assert "Charge Sheeted" in values["CaseStatusMaster.CaseStatusName"]


def test_prompt_contains_schema_lookups_question_and_today(db):
    text = prompt.build_prompt("how many burglaries last month", db, TODAY)
    assert "CaseMaster(" in text
    assert "Two-Wheeler Theft" in text
    assert "how many burglaries last month" in text
    assert "2026-07-09" in text


def test_prompt_states_the_hard_rules(db):
    text = prompt.build_prompt("x", db, TODAY)
    for rule in [
        "SELECT",
        "CaseMaster.CrimeNo",
        "qualify every column",
        "COUNT, SUM, AVG, MIN, MAX",
        "no subqueries",
        "date functions",
    ]:
        assert rule.lower() in text.lower(), rule


def test_prompt_forbids_the_audit_table(db):
    assert "AuditLog" not in prompt.build_prompt("x", db, TODAY)


def test_answer_prompt_carries_rows_and_forbids_invented_crimenos():
    text = prompt.build_answer_prompt(
        "how many?",
        [{"CrimeNo": "1" * 18}],
        "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1",
    )
    assert "1" * 18 in text
    assert "only" in text.lower()


def test_answer_prompt_truncates_large_row_sets():
    rows = [{"CrimeNo": str(i).zfill(18)} for i in range(500)]
    text = prompt.build_answer_prompt("q", rows, "SELECT 1")
    assert str(len(rows)) in text  # the true count is stated
    assert len(text) < 40000
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.prompt'`.

- [ ] **Step 3: Write `prompt.py`**

Create `functions/crime_query/prompt.py`:

```python
"""Prompt construction for NL->SQL generation and answer composition.

Lookup values are read live from the database so the model never invents a
crime head or a station that does not exist in the data (PLAN.md 1.1).
"""
import json

from . import catalog

LOOKUP_FIELDS = [
    ("CrimeHead", "CrimeGroupName"),
    ("CrimeSubHead", "CrimeHeadName"),
    ("CaseStatusMaster", "CaseStatusName"),
    ("District", "DistrictName"),
    ("Unit", "UnitName"),
    ("Act", "ShortName"),
    ("CaseCategory", "LookupValue"),
    ("GravityOffence", "LookupValue"),
    ("OccupationMaster", "OccupationName"),
]

MAX_ROWS_IN_ANSWER_PROMPT = 40

_RULES = """Rules, all mandatory:
1. Emit exactly one SELECT statement. Nothing else. No INSERT, UPDATE, DELETE, DROP.
2. Qualify every column with its table name, e.g. CaseMaster.CrimeNo, never CrimeNo.
3. Use only these functions: COUNT, SUM, AVG, MIN, MAX. No date functions, no CAST,
   no string functions.
4. No subqueries, no CTEs, no UNION, no window functions.
5. Dates are stored as text in 'YYYY-MM-DD' form. Compare them with string literals
   you compute yourself from today's date. Example: the last 6 months is
   CaseMaster.CrimeRegisteredDate >= '2026-01-09'.
6. Any query that reads case data must include CaseMaster, joining back to it on
   CaseMasterID, so the result can be scoped to the caller's role.
7. Any query returning individual cases must select CaseMaster.CrimeNo, so the answer
   can cite them. Aggregate queries need not.
8. Add a LIMIT. Never above 200.
9. Use only the exact lookup values listed below. If the question names something not
   in those lists, choose the closest listed value.

Return only the SQL. No explanation, no markdown fence."""

_ANSWER_RULES = """Rules:
1. Answer only from the rows given. Do not use outside knowledge.
2. Cite crime numbers only if they appear verbatim in the rows above. Never invent,
   complete, or adjust a crime number.
3. If the rows are empty, say plainly that no matching cases were found.
4. Keep names and crime numbers exactly as written.
5. Two or three sentences."""


def lookup_values(db):
    """Read the live distinct values for every lookup field."""
    values = {}
    for table, column in LOOKUP_FIELDS:
        key = "{0}.{1}".format(table, column)
        values[key] = db.lookup(table, column)
    return values


def build_prompt(question, db, today):
    values = lookup_values(db)
    lookup_block = "\n".join(
        "{0}: {1}".format(key, ", ".join(str(v) for v in vals))
        for key, vals in values.items()
    )
    return (
        "You translate questions about the Karnataka police crime database into SQL.\n\n"
        "Today's date is {today}.\n\n"
        "Schema:\n{schema}\n\n"
        "Lookup values that exist in the data:\n{lookups}\n\n"
        "{rules}\n\n"
        "Question: {question}\nSQL:"
    ).format(
        today=today.isoformat(),
        schema=catalog.describe(),
        lookups=lookup_block,
        rules=_RULES,
        question=question,
    )


def build_answer_prompt(question, rows, sql):
    shown = rows[:MAX_ROWS_IN_ANSWER_PROMPT]
    body = json.dumps(shown, indent=None, default=str)
    return (
        "You answer questions about police case data using only the rows provided.\n\n"
        "Question: {question}\n\n"
        "SQL that produced the rows:\n{sql}\n\n"
        "Rows returned: {total} (showing the first {shown})\n{body}\n\n"
        "{rules}\n\nAnswer:"
    ).format(
        question=question,
        sql=sql,
        total=len(rows),
        shown=len(shown),
        body=body,
        rules=_ANSWER_RULES,
    )


def repair_prompt(previous_sql, error, original_prompt):
    """Second attempt after a ValidationError. The error text is the hint."""
    return (
        "{original}\n\n"
        "Your previous attempt was rejected.\n"
        "SQL: {sql}\n"
        "Reason: {error}\n\n"
        "Emit corrected SQL only.\nSQL:"
    ).format(original=original_prompt, sql=previous_sql, error=error)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_prompt.py -v`
Expected: PASS — 6 passed.

- [ ] **Step 5: Commit**

```bash
git add functions/crime_query/prompt.py tests/test_prompt.py
git commit -m "feat: schema- and lookup-grounded NL to SQL prompt"
```

---

### Task 8: LLM client

Two implementations of one method. `FakeLLM` hands back a scripted list of responses and records the prompts it saw — every test above `agent.py` uses it, so no test ever touches the network. `QuickMLLLM` posts to the QuickML LLM Serving endpoint (Qwen 2.5-14B) and strips the markdown fence that instruction-tuned models add even when told not to.

**Files:**
- Create: `functions/crime_query/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class FakeLLM` — `__init__(self, responses: List[str])`, `complete(prompt) -> str`, attribute `prompts: List[str]`
  - `class QuickMLLLM` — `__init__(self, endpoint, api_key, timeout=30)`, `complete(prompt) -> str`
  - `class LLMError(Exception)`
  - `def strip_fence(text: str) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm.py`:

```python
import pytest

from functions.crime_query import llm


def test_fake_llm_returns_scripted_responses_in_order():
    fake = llm.FakeLLM(["first", "second"])
    assert fake.complete("a") == "first"
    assert fake.complete("b") == "second"
    assert fake.prompts == ["a", "b"]


def test_fake_llm_raises_when_script_exhausted():
    fake = llm.FakeLLM(["only"])
    fake.complete("a")
    with pytest.raises(llm.LLMError):
        fake.complete("b")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SELECT 1", "SELECT 1"),
        ("```sql\nSELECT 1\n```", "SELECT 1"),
        ("```\nSELECT 1\n```", "SELECT 1"),
        ("  ```sql\nSELECT 1;\n```  ", "SELECT 1"),
        ("SELECT 1;", "SELECT 1"),
    ],
)
def test_strip_fence(raw, expected):
    assert llm.strip_fence(raw) == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.llm'`.

- [ ] **Step 3: Write `llm.py`**

Create `functions/crime_query/llm.py`:

```python
"""LLM clients. FakeLLM for tests, QuickMLLLM for Catalyst QuickML LLM Serving."""
import re

import requests

_FENCE = re.compile(r"^\s*```(?:sql)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class LLMError(Exception):
    """Raised when the model cannot be reached or returns nothing usable."""


def strip_fence(text):
    """Remove a markdown code fence and a single trailing semicolon."""
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    return text.strip().rstrip(";").strip()


class FakeLLM(object):
    """Scripted responses. Records every prompt it was given."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        if not self._responses:
            raise LLMError("FakeLLM script exhausted after {0} calls".format(len(self.prompts)))
        return self._responses.pop(0)


class QuickMLLLM(object):
    """Qwen 2.5-14B served by Catalyst QuickML LLM Serving."""

    def __init__(self, endpoint, api_key, timeout=30):
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout

    def complete(self, prompt):
        try:
            response = requests.post(
                self._endpoint,
                headers={
                    "Authorization": "Zoho-oauthtoken {0}".format(self._api_key),
                    "Content-Type": "application/json",
                },
                json={"prompt": prompt, "temperature": 0.0, "max_tokens": 512},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as err:
            raise LLMError("QuickML request failed: {0}".format(err))
        except ValueError as err:
            raise LLMError("QuickML returned non-JSON: {0}".format(err))

        text = payload.get("output") or payload.get("text") or ""
        if not text.strip():
            raise LLMError("QuickML returned an empty completion")
        return text
```

`temperature=0.0` is not a style choice: the eval in Task 10 measures SQL correctness across runs, and a non-zero temperature makes that number noise.

The response key (`output` vs `text`) is a guess against the QuickML serving contract. Task 12 Step 2 confirms it against a live endpoint; the `or` chain means either shape works, and an unrecognised shape raises rather than returning an empty answer.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS — 7 passed.

- [ ] **Step 5: Commit**

```bash
git add functions/crime_query/llm.py tests/test_llm.py
git commit -m "feat: QuickML LLM client with fake for tests"
```

---

### Task 9: The agent — orchestration, citation, verification

Wires the pieces into the request data flow from `PLAN.md` §1.0: generate → validate → scope → execute → redact → compose → verify → audit.

Two behaviours carry the headline claim from `PLAN.md` §4 ("hallucination rate: % of answer claims not traceable to a CrimeNo, target ~0"):

- **One repair attempt.** A `ValidationError` is fed back to the model as a hint (`prompt.repair_prompt`), once. A second failure is an honest refusal, not a third guess.
- **Citation verification.** Every 18-digit number in the composed answer is checked against the crime numbers actually present in the returned rows. Numbers that are not there were invented by the model; they are removed from the text and counted. The answer carries `hallucinated_crimenos` so the eval harness can measure the rate directly rather than inferring it.

Aggregate queries return no `CrimeNo`, so their citation is the `WHERE` clause that produced the number — `filter_citation`. That is what makes "1,240 burglaries" auditable.

Audit is written on every path, including refusals, because `PLAN.md` §1.5 says every query is logged, not every successful query.

**Files:**
- Create: `functions/crime_query/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `prompt.build_prompt`, `prompt.repair_prompt`, `prompt.build_answer_prompt`, `validate.validate`, `validate.ValidationError`, `rbac.allowed_units`, `rbac.apply`, `rbac.redact_rows`, `rbac.RbacError`, `llm.LLMError`, `db.DBError`, `db.append_audit`.
- Produces:
  - `CRIMENO_RE` — compiled `\b\d{18}\b`
  - `class Answer` — dataclass with `text: str`, `sql: str`, `rows: List[dict]`, `citations: List[str]`, `filter_citation: str`, `hallucinated_crimenos: List[str]`, `refused: bool`, `refusal_reason: str`. `citations` holds every crime number **present in the returned rows** — not the subset the model happened to name in its prose.
  - `def crime_numbers(rows) -> List[str]`
  - `def verify_citations(text, allowed) -> Tuple[str, List[str], List[str]]` — `(clean_text, cited, hallucinated)`
  - `def answer(question, caller, db, llm, today, now=None) -> Answer`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent.py`:

```python
import datetime as dt

import pytest

from functions.crime_query import agent
from functions.crime_query import db as db_module
from functions.crime_query.llm import FakeLLM
from functions.crime_query.rbac import Caller, MASK
from tools import gen_data

TODAY = dt.date(2026, 7, 9)
NOW = dt.datetime(2026, 7, 9, 10, 0, 0)
CONSTABLE = Caller(employee_id=9, unit_id=1, district_id=1, rank_hierarchy=6)
SP = Caller(employee_id=97, unit_id=1, district_id=1, rank_hierarchy=3)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_crime_numbers_are_extracted_from_any_column(db):
    rows = [{"CrimeNo": "1" * 18}, {"cn": "2" * 18}, {"n": 5}]
    assert agent.crime_numbers(rows) == ["1" * 18, "2" * 18]


def test_verify_citations_keeps_real_numbers():
    allowed = ["1" * 18]
    text, cited, bad = agent.verify_citations("See case {0}.".format("1" * 18), allowed)
    assert cited == ["1" * 18]
    assert bad == []
    assert "1" * 18 in text


def test_verify_citations_strips_invented_numbers():
    allowed = ["1" * 18]
    invented = "9" * 18
    text, cited, bad = agent.verify_citations(
        "Cases {0} and {1}.".format("1" * 18, invented), allowed
    )
    assert bad == [invented]
    assert invented not in text
    assert "1" * 18 in text


def test_row_level_answer_cites_returned_crimenos(db):
    sql = (
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.PoliceStationID = 1 LIMIT 3"
    )
    llm = FakeLLM([sql, "Found three cases."])
    result = agent.answer("recent cases", CONSTABLE, db, llm, TODAY, NOW)
    assert not result.refused
    assert len(result.citations) == 3
    assert all(len(c) == 18 for c in result.citations)


def test_aggregate_answer_cites_the_filter_instead(db):
    llm = FakeLLM([
        "SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster "
        "WHERE CaseMaster.CaseStatusID = 1",
        "There are many open cases.",
    ])
    result = agent.answer("how many open cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.citations == []
    assert "CaseStatusID" in result.filter_citation
    assert "PoliceStationID" in result.filter_citation  # the injected scope is visible


def test_scope_is_applied_so_constable_sees_only_own_unit(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo, CaseMaster.PoliceStationID FROM CaseMaster LIMIT 200",
        "ok",
    ])
    result = agent.answer("all cases", CONSTABLE, db, llm, TODAY, NOW)
    assert {row["PoliceStationID"] for row in result.rows} == {1}


def test_sensitive_column_is_masked_for_constable(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo, ComplainantDetails.CasteID FROM CaseMaster "
        "LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID LIMIT 5",
        "ok",
    ])
    result = agent.answer("complainant castes", CONSTABLE, db, llm, TODAY, NOW)
    assert all(row["CasteID"] == MASK for row in result.rows)


def test_sp_aggregate_over_caste_is_not_masked(db):
    llm = FakeLLM([
        "SELECT ComplainantDetails.CasteID, COUNT(CaseMaster.CaseMasterID) AS n "
        "FROM CaseMaster LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID "
        "GROUP BY ComplainantDetails.CasteID",
        "Distribution follows.",
    ])
    result = agent.answer("caste distribution", SP, db, llm, TODAY, NOW)
    assert not result.refused
    assert all(row["CasteID"] != MASK for row in result.rows)


def test_invalid_sql_triggers_exactly_one_repair_attempt(db):
    good = "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 2"
    llm = FakeLLM(["SELECT CaseMaster.PhoneNumber FROM CaseMaster", good, "ok"])
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert not result.refused
    assert len(llm.prompts) == 3
    assert "PhoneNumber" in llm.prompts[1]  # the rejection reason was fed back


def test_two_invalid_attempts_refuse_without_executing(db):
    llm = FakeLLM([
        "SELECT CaseMaster.PhoneNumber FROM CaseMaster",
        "DROP TABLE CaseMaster",
    ])
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
    assert result.rows == []
    assert result.text


def test_rbac_rejection_refuses_and_does_not_retry(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "LEFT JOIN ComplainantDetails "
        "ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID "
        "WHERE ComplainantDetails.CasteID = 2 LIMIT 5",
        "unused",
    ])
    result = agent.answer("cases by caste", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
    assert len(llm.prompts) == 1  # an authorisation refusal is not a repairable error


def test_hallucinated_crimeno_is_stripped_and_counted(db):
    invented = "9" * 18
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster "
        "WHERE CaseMaster.PoliceStationID = 1 LIMIT 1",
        "The relevant case is {0}.".format(invented),
    ])
    result = agent.answer("a case", CONSTABLE, db, llm, TODAY, NOW)
    assert result.hallucinated_crimenos == [invented]
    assert invented not in result.text


def test_every_call_writes_exactly_one_audit_row(db):
    def audit_count():
        return db.execute_raw('SELECT COUNT(*) AS n FROM "AuditLog"')[0]["n"]

    before = audit_count()
    agent.answer(
        "cases", CONSTABLE, db,
        FakeLLM(["SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1", "ok"]),
        TODAY, NOW,
    )
    agent.answer("bad", CONSTABLE, db, FakeLLM(["DROP TABLE Unit", "DROP TABLE Unit"]), TODAY, NOW)
    assert audit_count() == before + 2


def test_audit_row_records_question_sql_and_crimenos(db):
    agent.answer(
        "how many cases in my station",
        CONSTABLE, db,
        FakeLLM(["SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1", "ok"]),
        TODAY, NOW,
    )
    row = db.execute_raw(
        'SELECT * FROM "AuditLog" ORDER BY AuditID DESC LIMIT 1'
    )[0]
    assert row["Question"] == "how many cases in my station"
    assert "CrimeNo" in row["GeneratedSQL"]
    assert "PoliceStationID" in row["ExecutedSQL"]
    assert row["EmployeeID"] == CONSTABLE.employee_id
    assert len(row["CrimeNos"].split(",")[0]) == 18


def test_db_error_is_reported_not_raised(db):
    llm = FakeLLM([
        "SELECT CaseMaster.CrimeNo FROM CaseMaster LIMIT 1",
        "ok",
    ])
    db.close()  # force a DBError on execute
    result = agent.answer("cases", CONSTABLE, db, llm, TODAY, NOW)
    assert result.refused
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.agent'`.

- [ ] **Step 3: Write `agent.py`**

Create `functions/crime_query/agent.py`:

```python
"""Orchestration: generate -> validate -> scope -> execute -> redact -> compose
-> verify -> audit.

Every path writes exactly one audit row, including refusals.
"""
import datetime as dt
import re
from dataclasses import dataclass, field

from sqlglot import exp

from . import prompt as prompt_module
from . import rbac, validate
from .db import DBError
from .llm import LLMError, strip_fence

CRIMENO_RE = re.compile(r"\b\d{18}\b")

REFUSAL_TEXT = (
    "I could not answer that safely. {reason} "
    "Try naming the crime type, station, or date range explicitly."
)


@dataclass
class Answer:
    text: str
    sql: str = ""
    rows: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    filter_citation: str = ""
    hallucinated_crimenos: list = field(default_factory=list)
    refused: bool = False
    refusal_reason: str = ""


def crime_numbers(rows):
    """Every 18-digit crime number present in the result rows, in row order."""
    found = []
    for row in rows:
        for value in row.values():
            if isinstance(value, str) and CRIMENO_RE.fullmatch(value):
                if value not in found:
                    found.append(value)
    return found


def verify_citations(text, allowed):
    """Strip crime numbers the rows do not contain. Returns (text, cited, hallucinated)."""
    allowed_set = set(allowed)
    cited, hallucinated = [], []

    for candidate in CRIMENO_RE.findall(text):
        if candidate in allowed_set:
            if candidate not in cited:
                cited.append(candidate)
        elif candidate not in hallucinated:
            hallucinated.append(candidate)

    clean = text
    for bad in hallucinated:
        clean = clean.replace(bad, "[unverified reference removed]")
    return clean, cited, hallucinated


def _filter_citation(sql):
    """The WHERE clause that produced an aggregate, rendered for display."""
    try:
        select = validate.validate(sql)
    except validate.ValidationError:
        return ""
    where = select.args.get("where")
    if where is None:
        return "no filter (all cases in scope)"
    return where.this.sql()


def _generate_sql(question, caller, db, llm, today):
    """One generation, one repair. Returns validated AST or raises ValidationError."""
    base_prompt = prompt_module.build_prompt(question, db, today)
    raw = strip_fence(llm.complete(base_prompt))
    try:
        return validate.validate(raw), raw
    except validate.ValidationError as first_error:
        repair = prompt_module.repair_prompt(raw, str(first_error), base_prompt)
        retry = strip_fence(llm.complete(repair))
        return validate.validate(retry), retry


def _audit(db, caller, question, generated, executed, citations, rows, now):
    db.append_audit(
        EmployeeID=caller.employee_id,
        RankHierarchy=caller.rank_hierarchy,
        Question=question,
        GeneratedSQL=generated,
        ExecutedSQL=executed,
        CrimeNos=",".join(citations),
        RowCount=len(rows),
        Timestamp=now.isoformat(),
    )


def _refuse(db, caller, question, generated, reason, now):
    _audit(db, caller, question, generated, "", [], [], now)
    return Answer(
        text=REFUSAL_TEXT.format(reason=reason),
        sql=generated,
        refused=True,
        refusal_reason=reason,
    )


def answer(question, caller, db, llm, today, now=None):
    now = now or dt.datetime.utcnow()
    generated = ""

    try:
        select, generated = _generate_sql(question, caller, db, llm, today)
    except (validate.ValidationError, LLMError, DBError) as err:
        # DBError belongs here too: build_prompt reads lookup values from the DB.
        return _refuse(db, caller, question, generated, str(err), now)

    try:
        units = rbac.allowed_units(caller, db)
        executed_sql, redact_keys = rbac.apply(select, caller, units)
    except rbac.RbacError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    try:
        rows = db.execute(executed_sql)
    except DBError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    rows = rbac.redact_rows(rows, redact_keys)
    allowed = crime_numbers(rows)

    try:
        composed = llm.complete(prompt_module.build_answer_prompt(question, rows, executed_sql))
    except LLMError as err:
        return _refuse(db, caller, question, generated, str(err), now)

    text, _mentioned, hallucinated = verify_citations(composed, allowed)
    filter_citation = _filter_citation(executed_sql) if not allowed else ""

    # Citations are the crime numbers the *rows* contain, not the ones the model
    # chose to mention. A model that answers "three cases were found" without
    # listing them still produces a fully citable answer.
    _audit(db, caller, question, generated, executed_sql, allowed, rows, now)

    return Answer(
        text=text,
        sql=executed_sql,
        rows=rows,
        citations=allowed,
        filter_citation=filter_citation,
        hallucinated_crimenos=hallucinated,
    )
```

Note `_filter_citation` re-validates rather than being handed the AST: the scoped SQL is a different string from the one `validate` returned, and re-parsing it is the cheapest way to be certain the citation shows the filter that *actually ran*, scope predicate included. That is why `test_aggregate_answer_cites_the_filter_instead` asserts `PoliceStationID` appears in it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_agent.py -v`
Expected: PASS — 15 passed.

`test_db_error_is_reported_not_raised` closes the connection before calling `answer`, so the first thing to fail is `db.lookup` inside `build_prompt`, not `db.execute`. `sqlite3.ProgrammingError` subclasses `sqlite3.Error`, so `SqliteDB.execute_raw` converts it to `DBError`, and the `except (ValidationError, LLMError, DBError)` around `_generate_sql` turns it into a refusal. That is why `DBError` appears in that tuple — remove it and this test raises instead of refusing.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: PASS — all tests from Tasks 1, 3, 4, 5, 6, 7, 8, 9.

- [ ] **Step 6: Commit**

```bash
git add functions/crime_query/agent.py tests/test_agent.py
git commit -m "feat: agent orchestration with citation verification and audit"
```

---

### Task 10: Eval harness — the 30-question labelled set

`PLAN.md` §4 names four numbers this plan must produce: SQL correctness ≥ 85% on a 30-question set, hallucination rate ≈ 0, p95 latency < 8 s, and Kannada parity (Task 11). This task builds the harness and the labelled set.

Correctness is measured as **execution accuracy**, not string equality: the generated SQL and the gold SQL are both run, and their result sets are compared as order-insensitive multisets of stringified values. A model that writes `COUNT(*)` where the gold writes `COUNT(CaseMaster.CaseMasterID)` is correct, and should score as correct.

The eval runs as a `Hierarchy = 1` caller (DGP), so no scope predicate is injected and the generated SQL is directly comparable to the gold SQL. Scoping is tested in Task 5; conflating the two here would make a correctness regression indistinguishable from an RBAC change.

Every gold query is a count, a min/max, or an ordered listing — nothing whose result depends on tie-breaking. That is deliberate: the generator is deterministic, so the gold answers are stable, and a flaky eval number is worse than no eval number.

**Files:**
- Create: `eval/questions.yaml`
- Create: `eval/run_eval.py`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `agent.answer`, `db.SqliteDB`, `llm.QuickMLLLM`, `llm.FakeLLM`.
- Produces:
  - `def load_questions(path) -> List[dict]` — each `{"id", "question", "sql"}`
  - `def normalise(rows) -> List[Tuple[str, ...]]` — order-insensitive comparable form
  - `def score(generated_rows, gold_rows) -> bool`
  - `def run(db, llm, questions, today) -> dict` — `{"accuracy", "hallucination_rate", "p95_latency_s", "results"}`

- [ ] **Step 1: Write `eval/questions.yaml`**

Thirty questions, each with the gold SQL that answers it against the seeded dataset.

```yaml
- id: 1
  question: How many cases are there in total?
  sql: SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
- id: 2
  question: How many burglary cases are there?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    WHERE CrimeSubHead.CrimeHeadName = 'Burglary'
- id: 3
  question: How many two-wheeler thefts were registered in Bengaluru East?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft' AND Unit.UnitName = 'Bengaluru East'
- id: 4
  question: Give me the crime numbers of five murder cases.
  sql: >
    SELECT CaseMaster.CrimeNo FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    WHERE CrimeSubHead.CrimeHeadName = 'Murder'
    ORDER BY CaseMaster.CrimeNo LIMIT 5
- id: 5
  question: Which police station has registered the most cases?
  sql: >
    SELECT Unit.UnitName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    GROUP BY Unit.UnitName ORDER BY n DESC, Unit.UnitName LIMIT 1
- id: 6
  question: How many cases were registered in Mysuru district?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    LEFT JOIN District ON Unit.DistrictID = District.DistrictID
    WHERE District.DistrictName = 'Mysuru'
- id: 7
  question: How many cases have been charge sheeted?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseStatusMaster ON CaseMaster.CaseStatusID = CaseStatusMaster.CaseStatusID
    WHERE CaseStatusMaster.CaseStatusName = 'Charge Sheeted'
- id: 8
  question: How many heinous offences are there?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN GravityOffence ON CaseMaster.GravityOffenceID = GravityOffence.GravityOffenceID
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
    LEFT JOIN CrimeHead ON CaseMaster.CrimeMajorHeadID = CrimeHead.CrimeHeadID
    GROUP BY CrimeHead.CrimeGroupName
- id: 12
  question: How many complainants are farmers?
  sql: >
    SELECT COUNT(ComplainantDetails.ComplainantID) AS n FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID
    LEFT JOIN OccupationMaster ON ComplainantDetails.OccupationID = OccupationMaster.OccupationID
    WHERE OccupationMaster.OccupationName = 'Farmer'
- id: 13
  question: What is the average age of complainants?
  sql: >
    SELECT AVG(ComplainantDetails.AgeYear) AS n FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID
- id: 14
  question: How many female victims are recorded?
  sql: >
    SELECT COUNT(Victim.VictimMasterID) AS n FROM CaseMaster
    LEFT JOIN Victim ON CaseMaster.CaseMasterID = Victim.CaseMasterID
    WHERE Victim.GenderID = 2
- id: 15
  question: How many accused persons are recorded across all cases?
  sql: >
    SELECT COUNT(Accused.AccusedMasterID) AS n FROM CaseMaster
    LEFT JOIN Accused ON CaseMaster.CaseMasterID = Accused.CaseMasterID
- id: 16
  question: How many arrests have been made?
  sql: >
    SELECT COUNT(ArrestSurrender.ArrestSurrenderID) AS n FROM CaseMaster
    LEFT JOIN ArrestSurrender ON CaseMaster.CaseMasterID = ArrestSurrender.CaseMasterID
- id: 17
  question: What is the most common type of crime?
  sql: >
    SELECT CrimeSubHead.CrimeHeadName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    GROUP BY CrimeSubHead.CrimeHeadName ORDER BY n DESC, CrimeSubHead.CrimeHeadName LIMIT 1
- id: 18
  question: How many cases are registered at Belagavi City station?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    WHERE Unit.UnitName = 'Belagavi City'
- id: 19
  question: List the crime numbers of all dacoity cases.
  sql: >
    SELECT CaseMaster.CrimeNo FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    WHERE CrimeSubHead.CrimeHeadName = 'Dacoity' ORDER BY CaseMaster.CrimeNo LIMIT 200
- id: 20
  question: How many cases were charged under IPC section 302?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN ActSectionAssociation ON CaseMaster.CaseMasterID = ActSectionAssociation.CaseMasterID
    WHERE ActSectionAssociation.ActID = 'IPC' AND ActSectionAssociation.SectionID = '302'
- id: 21
  question: How many cases are there in each case status?
  sql: >
    SELECT CaseStatusMaster.CaseStatusName, COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseStatusMaster ON CaseMaster.CaseStatusID = CaseStatusMaster.CaseStatusID
    GROUP BY CaseStatusMaster.CaseStatusName
- id: 22
  question: How many zero FIRs have been registered?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CaseCategory ON CaseMaster.CaseCategoryID = CaseCategory.CaseCategoryID
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
    LEFT JOIN ChargesheetDetails ON CaseMaster.CaseMasterID = ChargesheetDetails.CaseMasterID
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
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    LEFT JOIN District ON Unit.DistrictID = District.DistrictID
    WHERE District.DistrictName = 'Bengaluru City'
      AND CaseMaster.CrimeRegisteredDate >= '2026-01-01'
      AND CaseMaster.CrimeRegisteredDate <= '2026-12-31'
- id: 28
  question: Break down complainants by religion.
  sql: >
    SELECT ComplainantDetails.ReligionID, COUNT(ComplainantDetails.ComplainantID) AS n
    FROM CaseMaster
    LEFT JOIN ComplainantDetails ON CaseMaster.CaseMasterID = ComplainantDetails.CaseMasterID
    GROUP BY ComplainantDetails.ReligionID
- id: 29
  question: How many non-heinous cases were registered in Mysuru district?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    LEFT JOIN District ON Unit.DistrictID = District.DistrictID
    LEFT JOIN GravityOffence ON CaseMaster.GravityOffenceID = GravityOffence.GravityOffenceID
    WHERE District.DistrictName = 'Mysuru' AND GravityOffence.LookupValue = 'Non-Heinous'
- id: 30
  question: How many two-wheeler thefts happened in Bengaluru East since April 2026?
  sql: >
    SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster
    LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.CrimeSubHeadID
    LEFT JOIN Unit ON CaseMaster.PoliceStationID = Unit.UnitID
    WHERE CrimeSubHead.CrimeHeadName = 'Two-Wheeler Theft'
      AND Unit.UnitName = 'Bengaluru East'
      AND CaseMaster.CrimeRegisteredDate >= '2026-04-01'
```

Question 28 groups by `ComplainantDetails.ReligionID`, a sensitive column. That is intentional: it exercises the "authorised caller, aggregate query, no redaction" path end to end, and it fails loudly if `SENSITIVE_MAX_HIERARCHY` is ever tightened without updating the eval.

- [ ] **Step 2: Write the failing test**

Create `tests/test_eval.py`:

```python
import pytest

from eval import run_eval
from functions.crime_query import db as db_module
from functions.crime_query import validate
from functions.crime_query.llm import FakeLLM
from tools import gen_data


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


@pytest.fixture(scope="module")
def questions():
    return run_eval.load_questions(run_eval.QUESTIONS_PATH)


def test_thirty_questions_with_unique_ids(questions):
    assert len(questions) == 30
    assert len({q["id"] for q in questions}) == 30


def test_every_gold_query_passes_the_validator(questions):
    for question in questions:
        validate.validate(question["sql"])  # raises on failure


def test_every_gold_query_returns_at_least_one_row(db, questions):
    for question in questions:
        rows = db.execute(question["sql"])
        assert rows, question["id"]


def test_normalise_is_order_insensitive():
    a = [{"x": 1, "y": "b"}, {"x": 2, "y": "a"}]
    b = [{"x": 2, "y": "a"}, {"x": 1, "y": "b"}]
    assert run_eval.normalise(a) == run_eval.normalise(b)


def test_normalise_ignores_column_names_but_not_values():
    assert run_eval.normalise([{"n": 5}]) == run_eval.normalise([{"count": 5}])
    assert run_eval.normalise([{"n": 5}]) != run_eval.normalise([{"n": 6}])


def test_score_accepts_equivalent_aggregate_spellings(db):
    gold = db.execute('SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster')
    generated = db.execute('SELECT COUNT(*) AS total FROM CaseMaster')
    assert run_eval.score(generated, gold)


def test_run_scores_a_perfect_model_at_one(db, questions):
    subset = questions[:3]
    scripted = []
    for question in subset:
        scripted.extend([question["sql"], "Answer."])
    report = run_eval.run(db, FakeLLM(scripted), subset, run_eval.TODAY)
    assert report["accuracy"] == 1.0
    assert report["hallucination_rate"] == 0.0
    assert report["p95_latency_s"] >= 0


def test_run_counts_a_hallucinated_crimeno(db, questions):
    question = questions[3]  # the murder-crime-number listing
    invented = "9" * 18
    llm = FakeLLM([question["sql"], "The case is {0}.".format(invented)])
    report = run_eval.run(db, llm, [question], run_eval.TODAY)
    assert report["hallucination_rate"] == 1.0
    assert report["accuracy"] == 1.0  # the SQL was right; only the prose lied
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_eval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval'`.

- [ ] **Step 4: Write `eval/run_eval.py`**

Create `eval/__init__.py` as an empty file, then `eval/run_eval.py`:

```python
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
    parser.add_argument("--api-key", default=os.environ.get("QUICKML_API_KEY"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.endpoint or not args.api_key:
        parser.error("set QUICKML_ENDPOINT and QUICKML_API_KEY, or pass them explicitly")

    db = db_module.SqliteDB(args.sqlite)
    llm = QuickMLLLM(args.endpoint, args.api_key)
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python -m pytest tests/test_eval.py -v`
Expected: PASS — 8 passed.

If `test_every_gold_query_returns_at_least_one_row` fails on question 19 or 22 (dacoity, zero FIR), the generator's weights made those categories too rare. Raise the dacoity weight in `gen_data.CRIME_SUBHEADS` sampling or the Zero-FIR probability, regenerate, and re-run — do not delete the question.

- [ ] **Step 6: Run the real eval against QuickML**

This is the number that goes on the slide. It needs a live endpoint.

```bash
python -m tools.gen_data --sqlite build/crime.db
export QUICKML_ENDPOINT="..."   # from the Catalyst console
export QUICKML_API_KEY="..."
python -m eval.run_eval --verbose
```

Expected: `SQL correctness` ≥ 85%, `Hallucination rate` 0.0%, `p95 latency` < 8 s. The command exits non-zero if either of the first two targets is missed.

Below 85%: read the `generated` vs `gold` lines for the failures. The fix is almost always in `prompt.py` — a missing lookup field or an under-specified rule — not in `validate.py`. Loosening the validator to make the eval pass converts a correctness failure into a security failure.

- [ ] **Step 7: Commit**

```bash
git add eval/__init__.py eval/questions.yaml eval/run_eval.py tests/test_eval.py
git commit -m "feat: 30-question eval with execution accuracy and hallucination rate"
```

---

### Task 11: Kannada bridge — detect, pivot to English, render back

`PLAN.md` §1.6 and committed feature 1 ("cited answer, English + Kannada"). The design is translate–reason–translate: detect the language, translate the question to English, run the *entire* existing pipeline unchanged, then render the answer back in Kannada.

Two decisions worth stating, because both are load-bearing:

- **Detection needs no service.** Kannada occupies Unicode block U+0C80–U+0CFF. Counting characters in that range is one line and cannot fail, time out, or cost a quota. Zia is used for translation, not detection.
- **Names and crime numbers are never translated.** They are swapped out for opaque placeholders before the text is sent to Zia and swapped back afterwards. An 18-digit crime number rendered into Kannada numerals is an uncitable answer, which is the one thing this system may not produce. `PLAN.md` §3 rates weak Kannada generation as a *known* high risk — the placeholder swap is why that risk does not touch citations.

The Zia call is wrapped so a translation failure degrades to the English answer with a note, rather than failing the request. That is the `PLAN.md` §2 cut line ("Voice input → typed Kannada only") applied one level down.

**Files:**
- Create: `functions/crime_query/translate.py`
- Test: `tests/test_translate.py`

**Interfaces:**
- Consumes: `agent.CRIMENO_RE`.
- Produces:
  - `KANNADA_RANGE = (0x0C80, 0x0CFF)`
  - `def detect(text: str) -> str` — `"kn"` or `"en"`
  - `def protect(text, tokens) -> Tuple[str, Dict[str, str]]`
  - `def restore(text, mapping) -> str`
  - `class ZiaTranslator` — `__init__(self, app)`, `translate(text, source, target) -> str`
  - `class NullTranslator` — identity; used when Zia is unavailable and in tests
  - `def to_english(text, translator) -> str`
  - `def to_user_language(text, language, translator, protected_tokens) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_translate.py`:

```python
import pytest

from functions.crime_query import translate

KANNADA_Q = "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"
CRIMENO = "104430006202600001"


class EchoTranslator:
    """Records calls; returns the text with a marker so we can see it was translated."""

    def __init__(self):
        self.calls = []

    def translate(self, text, source, target):
        self.calls.append((text, source, target))
        return "<{0}>{1}".format(target, text)


class BrokenTranslator:
    def translate(self, text, source, target):
        raise translate.TranslationError("Zia unavailable")


def test_detect_kannada():
    assert translate.detect(KANNADA_Q) == "kn"


def test_detect_english():
    assert translate.detect("How many thefts in Bengaluru East?") == "en"


def test_detect_english_for_mostly_ascii_with_a_stray_kannada_char():
    assert translate.detect("Cases in ಬೆಂಗಳೂರು East last month with many words here") == "en"


def test_detect_empty_string_is_english():
    assert translate.detect("") == "en"


def test_protect_and_restore_round_trip():
    text = "Case {0} filed by Ravi Kumar.".format(CRIMENO)
    protected, mapping = translate.protect(text, [CRIMENO, "Ravi Kumar"])
    assert CRIMENO not in protected
    assert "Ravi Kumar" not in protected
    assert translate.restore(protected, mapping) == text


def test_protect_placeholders_survive_a_translation_step():
    text = "Case {0}.".format(CRIMENO)
    protected, mapping = translate.protect(text, [CRIMENO])
    translated = EchoTranslator().translate(protected, "en", "kn")
    assert CRIMENO in translate.restore(translated, mapping)


def test_protect_longest_token_first():
    # "Ravi" is a substring of "Ravi Kumar"; the longer token must win.
    text = "Ravi Kumar and Ravi"
    protected, mapping = translate.protect(text, ["Ravi", "Ravi Kumar"])
    assert translate.restore(protected, mapping) == text


def test_to_english_skips_translation_for_english_input():
    translator = EchoTranslator()
    assert translate.to_english("How many thefts?", translator) == "How many thefts?"
    assert translator.calls == []


def test_to_english_translates_kannada():
    translator = EchoTranslator()
    result = translate.to_english(KANNADA_Q, translator)
    assert result.startswith("<en>")
    assert translator.calls[0][1:] == ("kn", "en")


def test_to_user_language_is_identity_for_english():
    translator = EchoTranslator()
    assert translate.to_user_language("Answer.", "en", translator, []) == "Answer."
    assert translator.calls == []


def test_to_user_language_preserves_crimeno_verbatim():
    translator = EchoTranslator()
    text = "The case is {0}.".format(CRIMENO)
    result = translate.to_user_language(text, "kn", translator, [CRIMENO])
    assert CRIMENO in result
    assert "<kn>" in result


def test_translation_failure_degrades_to_english_with_a_note():
    text = "The case is {0}.".format(CRIMENO)
    result = translate.to_user_language(text, "kn", BrokenTranslator(), [CRIMENO])
    assert CRIMENO in result
    assert "English" in result


def test_null_translator_is_identity():
    assert translate.NullTranslator().translate("x", "en", "kn") == "x"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_translate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.translate'`.

- [ ] **Step 3: Write `translate.py`**

Create `functions/crime_query/translate.py`:

```python
"""Kannada bridge: detect -> pivot to English -> reason -> render back.

Names and crime numbers never reach the translator. They are swapped for
opaque placeholders first, because a crime number rendered in Kannada numerals
is an uncitable answer.
"""
KANNADA_RANGE = (0x0C80, 0x0CFF)
KANNADA_SHARE_THRESHOLD = 0.15

DEGRADE_NOTE = " (Kannada translation unavailable; answer shown in English.)"


class TranslationError(Exception):
    """Raised when the translation service cannot be reached."""


def detect(text):
    """'kn' if a meaningful share of letters are Kannada, else 'en'."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    low, high = KANNADA_RANGE
    kannada = sum(1 for c in letters if low <= ord(c) <= high)
    return "kn" if kannada / len(letters) >= KANNADA_SHARE_THRESHOLD else "en"


def protect(text, tokens):
    """Replace each token with an opaque placeholder. Longest token first."""
    mapping = {}
    for index, token in enumerate(sorted(set(tokens), key=len, reverse=True)):
        if not token or token not in text:
            continue
        placeholder = "ZZ{0}ZZ".format(index)
        mapping[placeholder] = token
        text = text.replace(token, placeholder)
    return text, mapping


def restore(text, mapping):
    for placeholder, token in mapping.items():
        text = text.replace(placeholder, token)
    return text


class NullTranslator(object):
    """Used when Zia is unavailable, and in tests."""

    def translate(self, text, source, target):
        return text


class ZiaTranslator(object):
    """Catalyst Zia. Confirm the SDK call against docs/catalyst-zcql-findings.md."""

    def __init__(self, app):
        self._zia = app.zia()

    def translate(self, text, source, target):
        try:
            result = self._zia.translate(text, source_language=source, target_language=target)
        except Exception as err:
            raise TranslationError(str(err))
        translated = result.get("translated_text") if isinstance(result, dict) else result
        if not translated:
            raise TranslationError("Zia returned an empty translation")
        return translated


def to_english(text, translator):
    if detect(text) == "en":
        return text
    return translator.translate(text, "kn", "en")


def to_user_language(text, language, translator, protected_tokens):
    """Render the English answer back, leaving protected tokens untouched."""
    if language == "en":
        return text
    protected, mapping = protect(text, protected_tokens)
    try:
        translated = translator.translate(protected, "en", language)
    except TranslationError:
        return text + DEGRADE_NOTE
    return restore(translated, mapping)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_translate.py -v`
Expected: PASS — 13 passed.

- [ ] **Step 5: Note where Kannada parity is actually measured**

`PLAN.md` §4's fifth metric — 10 paired Kannada/English questions producing the same answer — cannot be tested offline. Parity holds structurally: `to_english` runs *before* the pipeline, so by the time `agent.answer` sees the question it is an English string indistinguishable from one the user typed in English. Nothing downstream can observe the original language.

There is no unit test for this. A test built on a fake translator would assert only that a string is a string. The real check is Task 12 Step 7, against live Zia.

- [ ] **Step 6: Commit**

```bash
git add functions/crime_query/translate.py tests/test_translate.py
git commit -m "feat: Kannada detection and English-pivot translation with verbatim IDs"
```

---

### Task 12: Catalyst function entrypoint and deployment

`PLAN.md` §5: features pass **on Catalyst, not localhost**. This task ships the same tested modules behind an Advanced I/O handler, loads the generated CSVs into the Data Store, and runs the demo's first beat end to end on the platform.

The handler is thin on purpose. It does exactly four things the library cannot: pick the backend, resolve the authenticated user to a `Caller`, do the language pivot, and shape the HTTP response. Everything else is already tested.

**Files:**
- Create: `functions/crime_query/main.py`
- Verify (modify only if the SDK differs): `functions/crime_query/db.py` — `ZcqlDB.append_audit`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `def handler(context, basic_io)` (or the signature the CLI scaffolded in Task 2), and `def handle_question(payload, db, llm, translator, today) -> dict` — the pure, testable core.

- [ ] **Step 1: Write the failing test**

`handle_question` holds all the logic and takes its dependencies as arguments, so it is testable without Catalyst. Create `tests/test_main.py`:

```python
import datetime as dt

import pytest

from functions.crime_query import db as db_module
from functions.crime_query import main, translate
from functions.crime_query.llm import FakeLLM
from tools import gen_data

TODAY = dt.date(2026, 7, 9)
SQL = "SELECT CaseMaster.CrimeNo FROM CaseMaster WHERE CaseMaster.PoliceStationID = 1 LIMIT 2"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    handle = db_module.SqliteDB(str(path))
    yield handle
    handle.close()


def test_english_question_returns_answer_sql_and_citations(db):
    payload = {"employee_id": 9, "question": "recent cases"}
    llm = FakeLLM([SQL, "Two cases found."])
    result = main.handle_question(payload, db, llm, translate.NullTranslator(), TODAY)
    assert result["language"] == "en"
    assert len(result["citations"]) == 2
    assert "PoliceStationID" in result["sql"]
    assert result["refused"] is False


def test_unknown_employee_is_rejected_before_any_llm_call(db):
    llm = FakeLLM([])
    result = main.handle_question(
        {"employee_id": 999999, "question": "x"}, db, llm, translate.NullTranslator(), TODAY
    )
    assert result["refused"] is True
    assert llm.prompts == []


def test_missing_question_is_rejected(db):
    result = main.handle_question(
        {"employee_id": 9}, db, FakeLLM([]), translate.NullTranslator(), TODAY
    )
    assert result["refused"] is True


def test_kannada_question_is_pivoted_and_answer_rendered_back(db):
    class Echo:
        """Stands in for Zia. Mangles every character it is given, on purpose:
        anything that survives verbatim must have been protected."""

        def translate(self, text, source, target):
            return "<{0}>{1}".format(target, text.upper())

    real = [row["CrimeNo"] for row in db.execute(SQL)]
    assert len(real) == 2

    payload = {"employee_id": 9, "question": "ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಪ್ರಕರಣಗಳು?"}
    llm = FakeLLM([SQL, "Cases {0} and {1}.".format(*real)])
    result = main.handle_question(payload, db, llm, Echo(), TODAY)

    assert result["language"] == "kn"
    assert "<kn>" in result["answer"]
    assert sorted(result["citations"]) == sorted(real)
    # Crime numbers survive the round trip untranslated and unmangled.
    for crime_no in real:
        assert crime_no in result["answer"]


def test_response_never_leaks_the_generated_sql_on_refusal(db):
    llm = FakeLLM(["DROP TABLE Unit", "DROP TABLE Unit"])
    result = main.handle_question(
        {"employee_id": 9, "question": "drop everything"}, db, llm,
        translate.NullTranslator(), TODAY,
    )
    assert result["refused"] is True
    assert result["sql"] == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'functions.crime_query.main'`.

- [ ] **Step 3: Write `main.py` and fill in the Data Store insert**

Create `functions/crime_query/main.py`:

```python
"""Catalyst Advanced I/O entrypoint.

Thin by design: pick the backend, resolve the caller, pivot the language,
shape the response. Everything else is tested library code.
"""
import datetime as dt
import json
import os

from . import agent, translate
from .db import SqliteDB, ZcqlDB
from .llm import QuickMLLLM


def handle_question(payload, db, llm, translator, today):
    """Pure core. No Catalyst types, no environment reads."""
    question = (payload.get("question") or "").strip()
    employee_id = payload.get("employee_id")

    if not question:
        return {"refused": True, "answer": "No question was provided.",
                "sql": "", "rows": [], "citations": [], "language": "en"}

    caller = db.caller_for(employee_id) if employee_id is not None else None
    if caller is None:
        return {"refused": True, "answer": "You are not authorised to query this system.",
                "sql": "", "rows": [], "citations": [], "language": "en"}

    language = translate.detect(question)
    english_question = translate.to_english(question, translator)

    result = agent.answer(english_question, caller, db, llm, today)

    protected = list(result.citations)
    rendered = translate.to_user_language(result.text, language, translator, protected)

    return {
        "refused": result.refused,
        "answer": rendered,
        "sql": "" if result.refused else result.sql,
        "rows": result.rows,
        "citations": result.citations,
        "filter_citation": result.filter_citation,
        "hallucinated": result.hallucinated_crimenos,
        "language": language,
    }


def handler(context, basic_io):
    """Signature must match the stub the Catalyst CLI generated in Task 2."""
    import zcatalyst_sdk

    app = zcatalyst_sdk.initialize()
    db = ZcqlDB(app)
    llm = QuickMLLLM(os.environ["QUICKML_ENDPOINT"], os.environ["QUICKML_API_KEY"])
    translator = translate.ZiaTranslator(app)

    payload = json.loads(basic_io.get_argument("body") or "{}")
    result = handle_question(payload, db, llm, translator, dt.date.today())

    basic_io.set_status(403 if result["refused"] else 200)
    basic_io.write(json.dumps(result, default=str))
```

Then verify `ZcqlDB.append_audit` against the live SDK. Task 6 wrote it as `self._datastore.table(AUDIT_TABLE).insert_row(fields)`; confirm that `app.datastore()`, `.table(name)`, and `.insert_row(dict)` are the real method names recorded in `docs/catalyst-zcql-findings.md`, and correct them here if not. Do not proceed to Step 5 until an audit row actually appears in the Data Store — an audit write that silently no-ops would make `PLAN.md`'s "immutable audit trail" a false claim on the slide.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS — 5 passed.

Then the whole suite: `python -m pytest -v` — all tests from Tasks 1, 3–12 pass.

- [ ] **Step 5: Load the data into the Catalyst Data Store**

Create all 27 tables (26 schema tables plus `AuditLog`) in the Data Store, then import the CSVs.

```bash
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
ls build/csv     # 26 files, one per schema table
```

Import order matters — parents before children, or foreign-key columns land with values that reference nothing:

```
State, District, UnitType, Unit, Rank, Designation, Employee,
CrimeHead, CrimeSubHead, CaseStatusMaster, CaseCategory, GravityOffence, Court,
CasteMaster, ReligionMaster, OccupationMaster, Act, Section, CrimeHeadActSection,
CaseMaster, ComplainantDetails, Victim, Accused, ArrestSurrender,
ActSectionAssociation, ChargesheetDetails
```

Verify the load in the console's ZCQL editor:

```sql
SELECT COUNT(CaseMaster.CaseMasterID) FROM CaseMaster
```

Expected: `5000`.

- [ ] **Step 6: Deploy and smoke-test on Catalyst**

```bash
catalyst deploy --only functions
```

Then, with a real function URL and the constable's employee id (9):

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H 'Content-Type: application/json' \
  -d '{"employee_id": 9, "question": "How many two-wheeler thefts in Bengaluru East since April 2026?"}'
```

Expected: HTTP 200, a JSON body whose `sql` contains `PoliceStationID IN (1)` and whose `filter_citation` names the crime sub-head and date filter.

Then the Kannada beat from `PLAN.md` §4:

```bash
curl -s -X POST "$FUNCTION_URL" \
  -H 'Content-Type: application/json' \
  -d '{"employee_id": 9, "question": "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?"}'
```

Expected: `"language": "kn"`, a Kannada `answer`, and every string in `citations` appearing verbatim (Latin digits) inside that Kannada answer.

Then the RBAC beat — the same question as an SP (employee id 97), which must widen the scope:

```bash
curl -s -X POST "$FUNCTION_URL" -H 'Content-Type: application/json' \
  -d '{"employee_id": 97, "question": "How many cases are open?"}' | grep -o 'IN ([0-9, ]*)'
```

Expected: `IN (1, 2, 3, 4)` — the district's four stations, not one.

Finally, confirm the audit trail is real:

```sql
SELECT AuditLog.Question, AuditLog.EmployeeID, AuditLog.CrimeNos FROM AuditLog
```

Expected: one row per curl above, including the refused ones.

- [ ] **Step 7: Run the Kannada parity spot-check against live Zia**

Ten paired questions, Kannada and English. Send each pair and compare the `sql` field, which is language-independent by construction.

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

Expected: the two `sql` lines in each pair are identical. Record the pass count out of 10 for the metrics slide. Extend the loop to all ten pairs.

- [ ] **Step 8: Commit**

```bash
git add functions/crime_query/main.py functions/crime_query/db.py tests/test_main.py
git commit -m "feat: Catalyst entrypoint, Data Store audit insert, deployment smoke tests"
```

---

## What this plan does not build

Named so the next plan's author does not assume they exist:

- `PersonNode` and the four `Edge*` tables, entity resolution, graph traversal, community detection (`PLAN.md` §1.3, §1.7 — committed features 8, 9)
- The `BriefFacts` QuickML Knowledge Base and semantic retrieval (`PLAN.md` §1.2 — the RAG half of Regime A)
- Regime B / GraphRAG routing (`PLAN.md` §1.4) — the orchestrator here always takes the NL→SQL path
- DBSCAN hotspots, trend roll-ups, forecasts, prevention briefings (`PLAN.md` §1.7 — features 10, 11, 14)
- Behavioral profiling (feature 13)
- The chat UI, voice I/O, Cache-backed multi-turn context, SmartBrowz PDF export (features 2, 3, 4)
- The audit *viewer* page (`PLAN.md` §1.5) — the audit table and writes exist; nothing reads them back yet

The seeded trend, spatial cluster, and name variants in Task 3 exist precisely so those later plans have signal to find.
