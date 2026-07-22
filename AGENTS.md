# Repository Guidelines

## Project Structure

- `functions/crime_query/` contains the Python 3.9 Zoho Catalyst Advanced I/O function.
- `tests/` contains the pytest suite for query generation, validation, RBAC, translation, database adapters, and agents.
- `tools/` contains synthetic-data generation and Catalyst Data Store import/remapping utilities.
- `eval/` contains the question set and QuickML-backed evaluation harness.
- `docs/` contains schema DDL, Catalyst deployment notes, feature specs, and implementation plans.
- `PLAN.md` is the current architecture and scope source of truth; `Police_FIR_ER_Diagram.md` is the authoritative schema.

## Development Commands

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
```

Run the full offline test suite with `python -m pytest -q`. Generate or refresh
the local SQLite database and CSV fixtures with the data-generator command.
Live Catalyst deployment requires an authenticated CLI and configured QuickML
credentials:

```bash
catalyst deploy --only functions:crime_query
```

Use `docs/CATALYST_RUNBOOK.md` for Data Store setup, imports, smoke tests, and
known live-account limitations.

## Coding Style

Use four-space indentation, focused modules, type-aware Python, and `snake_case`
for functions and variables. Use `PascalCase` for classes and descriptive
constants in `UPPER_SNAKE_CASE`. No formatter or linter is currently configured;
keep changes compatible with Python 3.9 and preserve the Catalyst runtime's
absolute-import fallback pattern.

## Testing Guidelines

Add or update focused pytest tests under `tests/` for every behavior change.
Name files `test_<module>.py` and tests `test_<behavior>`. Prefer SQLite and
fakes for deterministic local tests; reserve live Catalyst checks for the
runbook smoke-test workflow. Run `python -m pytest -q` before submitting.

## Commits and Pull Requests

Use concise, imperative, conventional prefixes such as `feat:`, `fix:`,
`docs:`, or `validate:`; keep each commit focused. Pull requests should explain
the behavior and schema impact, link the relevant plan/spec, list test commands
and results, and call out any live Catalyst verification still pending.

## Security and Data Handling

Never commit OAuth tokens, API keys, production exports, or sensitive case data.
Enforce RBAC server-side using rank and unit/district scope. Preserve `CrimeNo`
citation requirements, mask sensitive demographic fields, and do not add
predictive use of caste or religion data.
