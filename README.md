# KSP Crime Copilot

Conversational intelligence for the Karnataka State Police crime database. The project combines secure natural-language querying, Kannada-English language support, explainable citations, rank-derived access control, and a Catalyst-native multi-agent architecture for crime analysis.

> **Project:** KSP Datathon 2026, Challenge 01  
> **Platform:** Zoho Catalyst  
> **Data:** Official relational schema with deterministic synthetic rows for development and evaluation

## Overview

KSP Crime Copilot helps police personnel query structured CCTNS-style crime data using a chatbot or speech. It is designed for Kannada-first interaction with an English reasoning pivot, while preserving crime numbers, names, dates, and locations exactly for reliable citations.

The system is deliberately evidence-led:

- Structured questions use validated natural-language-to-SQL.
- Narrative questions use `CaseMaster.BriefFacts` retrieval.
- Link and pattern questions use a derived relationship layer rather than an invented graph database.
- Every answer is scoped by the caller's rank and unit/district access.
- Every factual answer must cite accessible `CrimeNo` values or the applied filter.
- Sensitive caste and religion fields are masked server-side and never used for prediction or scoring.

## Current Status

The repository contains a working Python query backend, deterministic synthetic data generator, SQLite test path, Catalyst Advanced I/O entrypoint, SQL validation, RBAC, translation helpers, citation checks, and test/evaluation harnesses.

The broader product plan covers the Catalyst-hosted chatbot, browser voice interface, multi-agent supervisor, cross-lingual MO matching, derived graph visualization, and cross-jurisdiction silent-match alerts. These capabilities are specified in `PLAN.md` and linked implementation documents; many are implemented locally while live Catalyst readiness remains an account-level gate documented in [`docs/CATALYST_RUNBOOK.md`](docs/CATALYST_RUNBOOK.md).

The current workspace has not re-verified live Catalyst readiness: CLI access,
authenticated principal mapping, RAG/embedding endpoints, and authenticated
smoke execution remain deployment gates. See [`docs/CATALYST_RUNBOOK.md`](docs/CATALYST_RUNBOOK.md)
before treating the live path as fully closed.

The disconnected backup demo is replayable with synthetic data through
[`docs/DEMO_REPLAY.md`](docs/DEMO_REPLAY.md); its current nine-beat transcript
is [`docs/demo-replay.json`](docs/demo-replay.json). The offline synthetic
contract baseline and live-measurement boundary are recorded in
[`docs/evaluation-slide.md`](docs/evaluation-slide.md).

## Main Capabilities

### Conversational query

- Chatbot text queries in English, Kannada, or mixed language.
- Speech queries using a provider-neutral voice architecture.
- Follow-up questions using Catalyst Cache session context.
- English-pivot reasoning with Kannada response rendering.
- SQL generation restricted to an allowlisted schema and safe functions.
- Evidence verification, refusal handling, and citation-preserving answers.
- PDF export of conversation history through SmartBrowz.

### Crime intelligence

- Crime counts, filters, dates, sections, stations, and case facts.
- Semantic retrieval over `BriefFacts`.
- Cross-lingual Kannada-English modus operandi matching.
- Derived person, case, section, employee, and proximity relationships.
- Network traversal, community/centrality analysis, and graph visualization.
- Trend analysis, geographic hotspots, and geographic early warnings.
- Cross-jurisdiction silent-match alerts with evidence scoring and deduplication.
- Cited behavioral and prevention briefings as decision support, never automatic risk scores.

### Governance and safety

- Rank-derived capabilities using `Rank.Hierarchy`.
- Unit and district scope from `Employee.UnitID` and `Employee.DistrictID`.
- Server-side masking for DPDP-sensitive demographic fields.
- Immutable audit records for questions, SQL, citations, refusals, and actions.
- No predictive use of caste or religion.
- No raw audio persistence by default in the voice design.

## Architecture

```mermaid
flowchart LR
  CHAT["Chatbot text input"] --> INPUT["Final query text"]
  VOICE["Browser voice input"] --> STT["Speech recognition"] --> INPUT
  INPUT --> GW["Catalyst API Gateway<br/>authentication + RBAC"]
  GW --> SUP["Supervisor Agent<br/>typed task graph"]
  SUP --> SQL["Structured Query Agent"]
  SUP --> RAG["Narrative Retrieval Agent"]
  SUP --> GRAPH["Graph Agent"]
  SUP --> ANALYTICS["Analytics / Alert Agents"]
  SQL --> VERIFY["Verification + Citation"]
  RAG --> VERIFY
  GRAPH --> VERIFY
  ANALYTICS --> VERIFY
  VERIFY --> COMPOSE["Composition + translation"]
  COMPOSE --> ANSWER["Cited chat answer<br/>and optional speech"]
  SUP -.-> CACHE[("Catalyst Cache")]
  GW -.-> AUDIT[("Data Store audit log")]
  SQL -.-> DATA[("Catalyst Data Store")]
  RAG -.-> INDEX[("QuickML Knowledge Base")]
```

### Query flow

1. The officer submits a typed chatbot message or a final speech transcript.
2. Catalyst authenticates the caller and derives rank/unit/district scope.
3. Language is detected; Kannada or mixed-language text is normalized for reasoning while protected identifiers remain unchanged.
4. The Supervisor Agent creates a typed `TaskContext` and fans out only the relevant specialist tasks.
5. Specialists return typed `EvidenceBundle` objects containing claims, rows, citations, confidence, limitations, and model/index versions.
6. Verification checks authorization, conflicts, citations, and unsupported claims.
7. Composition renders the verified answer in the requested language.
8. The same `turn_id` is returned for voice requests so stale responses cannot be spoken after an interruption.

## Zoho Catalyst Services

| Catalyst service | Responsibility |
|---|---|
| Web Client Hosting | Chatbot, speech controls, citation panel, graph/map views, PDF download |
| Authentication | Login and authenticated caller identity |
| API Gateway | Authentication boundary, authorization hooks, throttling, audit hooks |
| Functions / Advanced I/O | Query handler, supervisor, specialist agents, validation, retries, evidence verification |
| Data Store | Official tables, derived edge tables, alerts, MO metadata, and audit log |
| Cache | Conversation context and active filters |
| QuickML LLM Serving | NL-to-SQL, answer composition, profiling, translation orchestration |
| QuickML Knowledge Base | Semantic retrieval over `BriefFacts` |
| QuickML Pipelines | DBSCAN hotspots, trends, anomaly/forecast processing |
| Zia | Language/OCR support and possible voice fallback where configured |
| SmartBrowz | Conversation-to-PDF export |
| Stratus | PDF and generated artifact storage |
| Cron / Circuits | Index refresh, graph rebuilds, batch alert scans, and durable long-running tasks |

## Data Model

The authoritative schema is [`Police_FIR_ER_Diagram.md`](Police_FIR_ER_Diagram.md). It is a 26-table relational CCTNS-style model centered on `CaseMaster`.

Important schema constraints:

- `CaseMaster.BriefFacts` is the primary free-text narrative field.
- `latitude` and `longitude` provide geographic data.
- There is no native cross-case person identifier.
- There are no phone, vehicle, address, or bank-account entities in the provided schema.
- Hidden relationships are derived during ingestion and stored in Catalyst Data Store tables such as `PersonNode`, `EdgePersonCase`, `EdgeCaseEmployee`, `EdgeCaseSection`, and `EdgeCaseNear`.
- Catalyst foreign-key columns use parent `ROWID` values in the live import path; see the remapping utility and runbook.

## Repository Layout

```text
functions/crime_query/       Catalyst Advanced I/O Python function
  main.py                    Request handler and query orchestration
  agent.py                   NL-to-SQL preparation and answer verification
  supervisor_runtime.py      bounded typed specialist fan-out and composition
  catalog.py                 Schema catalog, DDL, identifying/sensitive columns
  db.py                      SQLite and Catalyst Data Store adapters
  llm.py                     QuickML LLM client
  prompt.py                  Schema-aware prompts and repair prompts
  rbac.py                    Rank, unit, district, masking, and scope rules
  translate.py               Kannada detection, translation, and token protection
  validate.py                SQL parsing and allowlist validation
tests/                       Offline pytest suite
tools/                       Synthetic data and Catalyst import/remapping tools
eval/                        Labelled questions and QuickML evaluation harness
docs/                        Runbook, DDL, specs, and implementation plans
PLAN.md                      Current architecture and execution plan
AGENTS.md                    Contributor and repository guidelines
Police_FIR_ER_Diagram.md     Authoritative provided schema
requirements.txt             Local development dependencies
```

## Prerequisites

- Python 3.9 or a compatible Python environment.
- `pip` and virtual-environment support.
- Zoho Catalyst CLI and an authenticated Catalyst project for live deployment.
- QuickML credentials for the live LLM evaluation path.

Local tests use SQLite and fakes; they do not require Catalyst credentials.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the offline test suite:

```bash
python -m pytest -q
```

Generate the deterministic SQLite database and CSV fixtures:

```bash
python -m tools.gen_data --sqlite build/crime.db --csv build/csv
```

The generator creates 5,000 synthetic cases and deliberately seeds patterns used by tests and demonstrations, including two-wheeler theft trends, a burglary cluster, and name variants such as `Ravi Kumar`, `Ravi K`, `R. Kumar`, and `Ravikumar`.

Generate the disconnected backup replay and its transcript:

```bash
python -m tools.demo_replay
```

Generate the labelled offline contract baseline and evaluation slide:

```bash
python -m tools.offline_eval
```

The repository also includes [`catalyst-pipelines.yaml`](catalyst-pipelines.yaml)
for Catalyst CI verification. It runs the offline suite, deployment preflight,
silent-match packaging, and the disconnected demo replay; live account gates
remain in [`docs/CATALYST_RUNBOOK.md`](docs/CATALYST_RUNBOOK.md).

The offline evaluator replays gold SQL and therefore measures execution and
evidence plumbing, not live GLM-4.7 quality. Run the authenticated QuickML
evaluation in the section below for model-quality numbers.
## Evaluation

The evaluation harness compares generated and gold SQL by executing both and comparing result sets. It reports accuracy, hallucination rate, and p95 latency.

Set the required QuickML environment variables and run:

```bash
export QUICKML_ENDPOINT="..."
export QUICKML_TOKEN="..."
export QUICKML_ORG_ID="..."
python -m eval.run_eval --sqlite build/crime.db --verbose
```

The current targets are at least 85% SQL correctness, approximately 0% hallucinated citation rate, and less than 8 seconds p95 latency. See [`eval/questions.yaml`](eval/questions.yaml) and [`eval/run_eval.py`](eval/run_eval.py).

## Catalyst Deployment

Deploy the query function after authenticating the Catalyst CLI and configuring the function environment:

```bash
catalyst deploy --only functions:crime_query
```

The function uses Python 3.9 and pins `zcatalyst-sdk==1.3.0` in [`functions/crime_query/requirements.txt`](functions/crime_query/requirements.txt). QuickML GLM-4.7 endpoint/model and organization settings, plus the SmartBrowz PDF endpoint, are configured through [`functions/crime_query/catalyst-config.json`](functions/crime_query/catalyst-config.json); do not commit tokens or API keys. The deployed function obtains short-lived OAuth tokens from Catalyst runtime credentials.

For table creation, CSV import, Catalyst foreign-key remapping, smoke tests, known deployment behavior, and the current live blocker, follow [`docs/CATALYST_RUNBOOK.md`](docs/CATALYST_RUNBOOK.md).

Run the repository-only preflight before deploying. It validates the schema,
operational DDL, security rules, function configuration, GLM-4.7 selection,
and deployment shape without printing configuration values:

```bash
python -m tools.catalyst_preflight
python -m tools.catalyst_preflight --require-live
```

The first command is expected to pass locally with warnings when account-side
gates are absent. The second must pass before calling the deployment live-ready.

After deployment, use the opt-in redacted smoke runner instead of copying
tokens or response bodies into shell history:

```bash
export KSP_CRIME_QUERY_URL="https://..."
export KSP_SILENT_MATCH_URL="https://..."
export CATALYST_TOKEN="..."
python -m tools.catalyst_smoke --execute
```

Add `--include-scan` only when a synthetic batch scan is intentionally being
run.

## Current Query Contract

The pure offline core accepts an employee identity for deterministic tests. The
deployed Advanced I/O handler ignores any client-supplied employee identity and
resolves the authenticated Catalyst principal through `KSP_AUTH_EMPLOYEE_MAP`.
Scheduled and post-ingestion silent-match jobs use the separate
`KSP_AUTH_SERVICE_MAP` and are restricted to maintenance routes.
An authenticated request therefore sends:

```json
{
  "question": "How many two-wheeler thefts were reported in Bengaluru East?"
}
```

Responses include refusal status, answer text, generated SQL when safe, rows, citations, filter citations, hallucinated crime numbers, and detected language. The planned chatbot and voice contract adds `session_id`, `turn_id`, `input_mode`, `language_segments`, and `response_language` while preserving the same query and authorization path.

The same authenticated function also accepts `operation: "network"`,
`"analytics"`, `"profile"`, or `"demographics"`. These return scope-checked
graph/aggregate/profile data with an evidence envelope; network and profile
operations require `case_master_id`, while demographic dimensions are a fixed
allowlist and sensitive dimensions remain rank-gated aggregate views.
## Security and Data Handling

- Never commit OAuth tokens, API keys, production exports, or real case data.
- Treat browser metadata and client-supplied employee identifiers as untrusted.
- Enforce rank and unit/district scope in the serving layer, not only in the UI.
- Preserve `CrimeNo` citations through translation and answer composition.
- Mask `CasteID` and `ReligionID` according to rank-derived policy.
- Do not use caste or religion as a predictive, graph, alert, or risk-scoring feature.
- Avoid raw-audio persistence by default and define transcript retention before production voice deployment.
- Log refusals, access decisions, SQL metadata, citations, and actions for auditability.

## Documentation Map

- [`PLAN.md`](PLAN.md): current architecture, Catalyst service map, multi-agent execution plan, capabilities, risks, demo, and definition of done.
- [`docs/CATALYST_RUNBOOK.md`](docs/CATALYST_RUNBOOK.md): live Catalyst setup, imports, deployment, smoke tests, and known gaps.
- [`docs/zoho-catalyst-implementation-guide.md`](docs/zoho-catalyst-implementation-guide.md): implemented agent stack, Catalyst service map, feature contracts, deployment, and readiness checklist.
- [`docs/silent-match-production-runbook.md`](docs/silent-match-production-runbook.md): MO index versioning, scan jobs, rollback, and live alert smoke tests.
- [`docs/catalyst-job-contracts.json`](docs/catalyst-job-contracts.json): validated scheduled and post-ingestion job payload contracts.
- [`docs/schema-ddl.sql`](docs/schema-ddl.sql): local SQLite/Catalyst-oriented DDL.
- [`docs/superpowers/specs/2026-07-22-voice-interaction-architecture-design.md`](docs/superpowers/specs/2026-07-22-voice-interaction-architecture-design.md): provider-neutral chatbot/voice architecture, turn cancellation, stale-response protection, and rollout.
- [`docs/superpowers/specs/2026-07-21-cross-lingual-semantic-mo-matching-design.md`](docs/superpowers/specs/2026-07-21-cross-lingual-semantic-mo-matching-design.md): Kannada-English MO matching.
- [`docs/superpowers/specs/2026-07-18-cross-jurisdiction-silent-match-alerts-design.md`](docs/superpowers/specs/2026-07-18-cross-jurisdiction-silent-match-alerts-design.md): proactive cross-jurisdiction alerts.
- [`docs/superpowers/specs/2026-07-21-rank-derived-capability-rbac-design.md`](docs/superpowers/specs/2026-07-21-rank-derived-capability-rbac-design.md): rank-derived authorization and field masking.
- [`docs/superpowers/plans/2026-07-21-cross-lingual-silent-match-alerts.md`](docs/superpowers/plans/2026-07-21-cross-lingual-silent-match-alerts.md): implementation plan for MO matching and alerts.
- [`docs/superpowers/plans/2026-07-21-rank-derived-capability-rbac.md`](docs/superpowers/plans/2026-07-21-rank-derived-capability-rbac.md): implementation plan for RBAC.
- [`AGENTS.md`](AGENTS.md): contributor workflow, coding style, testing, commits, and security rules.

## Contributing

1. Read [`AGENTS.md`](AGENTS.md), [`PLAN.md`](PLAN.md), and the authoritative schema before changing code or architecture.
2. Keep Catalyst as the mandated deployment platform and use existing repository patterns.
3. Add focused pytest coverage for every behavior change.
4. Run `python -m pytest -q` and `git diff --check` before submitting.
5. Use concise imperative conventional commits such as `feat:`, `fix:`, `docs:`, or `validate:`.
6. Describe schema impact, test results, live Catalyst verification, and security implications in pull requests.

## Contributors

Contributors are listed from the repository's Git history and the project team list:

- **SHYAMSUNDAR2396**
- **jeevanav123**
- [**JheevikhaKannadasan**](https://github.com/JheevikhaKannadasan)
- [**G Thiruvarasmurthy**](https://github.com/Thiruvarasamurthy)
- **PK LATHISS KHUMAR**

GitHub links are included where they were provided by the project team.

## License

No license file is currently declared in this repository. Confirm the intended license and data-use terms before distributing the project or deploying it with non-synthetic case data.
