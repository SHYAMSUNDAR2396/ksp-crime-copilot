# KSP Crime Copilot — Zoho Catalyst implementation guide

This guide explains the implementation boundaries for the application described
in the root [`PLAN.md`](../PLAN.md). `PLAN.md` remains the scope and architecture
source of truth; this document is the practical developer and deployment map.

## 1. Production boundary

The application is a Catalyst-native Python 3.9 system. It does not introduce a
separate database, vector database, agent framework, or self-hosted LLM.

| Boundary | Selected technology |
|---|---|
| HTTP/API | Catalyst API Gateway and Python Advanced I/O Functions |
| Agent control plane | Typed Python supervisor and capability-gated task graph |
| Structured language model | Catalyst QuickML GLM-4.7-Flash deployment (`crm-di-glm47b_30b_it`) |
| Structured query | ZCQL generated from the live catalog, validated with `sqlglot` |
| Semantic retrieval | QuickML multilingual embeddings through a provider-neutral adapter |
| Narrative retrieval | Optional QuickML RAG adapter with deterministic cited fallback |
| Operational persistence | Catalyst Data Store with versioned derived graph tables; SQLite is the deterministic local adapter |
| Sessions | Catalyst Cache |
| Scheduling and retries | Catalyst Job Scheduling and Circuits where enabled |
| PDF export | Catalyst SmartBrowz Browser360 conversion endpoint |
| Files | Stratus |
| Browser | Static web client, browser Web Speech API, same authenticated API |

QuickML model selection is configuration-driven but pinned to GLM-4.7-Flash in
both source and deployment configuration. The retired model deployment must
not be restored.

## 2. Runtime architecture

Interactive requests follow this boundary:

```text
Authenticated browser
  -> API Gateway / Advanced I/O Function
  -> Catalyst principal -> EmployeeID mapping
  -> AccessContext and supervisor task selection
  -> specialist evidence producers
  -> RBAC, citation, conflict, and sensitive-field verification
  -> GLM-4.7-Flash composition/translation when required
  -> cited response + immutable audit record
```

The supervisor is not an unrestricted autonomous loop. It selects a bounded
set of named specialists from `functions/crime_query/supervisor.py`, and
`supervisor_runtime.py` executes the task graph with per-agent deadlines,
bounded retries, failure redaction, and a final composition boundary. Every
specialist receives the caller's immutable access context and returns a typed
`EvidenceBundle`; no model output can widen scope or bypass verification.

The local SQLite adapter runs the same graph inline because its connection is
thread-bound. The Catalyst ZCQL adapter selects the bounded parallel path for
independent specialists. If the account provisions separate specialist
Functions or Circuits, their handlers can be injected behind the same
`EvidenceBundle` contract without changing authorization or composition.

Proactive case processing follows a separate event/job path:

```text
Case ingestion or scheduled window
  -> bounded case projection
  -> identity/entity and graph projections
  -> multilingual MO normalization and index refresh
  -> structured + identity + graph + semantic silent-match scoring
  -> deduplicated alert and recipient routing
  -> scope-checked alert inbox and audit trail
```

## 3. Agent stack and responsibilities

| Agent | Implementation | Model use | Required guard |
|---|---|---|---|
| Supervisor | `supervisor.py`, `supervisor_runtime.py` task selection and execution | None | rank-derived capabilities, deadlines, bounded retries, typed evidence |
| Structured Query Agent | `agent.py`, `prompt.py`, `validate.py`, `rbac.py` | GLM only for NL→ZCQL and post-verification composition | SELECT-only validation, live catalog, ZCQL FK/ROWID joins, RBAC predicate |
| Narrative Retrieval Agent | `mo_matcher.py`, `mo_embeddings.py`, `mo_index.py` | QuickML multilingual embeddings | only visible cases are embedded and returned; bounded top-k |
| Graph Agent | `graph.py`, `intelligence_api.py` | None | bounded hops, visible rows, edge provenance and confidence |
| Analytics Agent | `analytics.py`, `intelligence_api.py` | Optional validated QuickML aggregate forecast provider; deterministic fallback | aggregate-only output; no caste/religion predictive use |
| Silent-Match Agent | `silent_match_scoring.py`, `silent_match_scanner.py` | MO similarity is bounded evidence only | semantic similarity alone cannot create an alert |
| Composition Agent | `llm.py`, `translate.py`, `evidence.py` | GLM-4.7-Flash where language generation is needed | cited claims, protected identifiers, refusal on unsupported evidence |

LangChain, CrewAI, and a second LLM host are deliberately not part of this
stack. Catalyst Functions provide the composable agent boundary, while the
application owns state, RBAC, evidence, and audit behavior.

## 4. Shared contracts

### AccessContext

`auth.py` maps the authenticated Catalyst principal to a trusted EmployeeID.
`access.py` derives rank, station/district scope, capabilities, masking policy,
and audit visibility from the official employee, rank, unit, and district rows.
The browser's `employee_id` is discarded by the live handler.

### TaskContext

`supervisor.build_task_context()` records the request ID, task profile, caller
scope, selected agents, required agents, deadline, retry budget, denials, and
policy version. Missing required capability produces a safe refusal and policy
audit row.

### EvidenceBundle

Every evidence producer returns claims, rows/entities, citations, bounded
signals, confidence, limitations, elapsed time, and model/index version.
`evidence.filter_visible_bundle()` and `merge_bundles()` remove out-of-scope
content and conflicting or unsupported claims before composition.

Every user-visible case claim must be traceable to a `CrimeNo`. Raw Data Store
rows and model traces are never sent directly to the browser.

## 5. Feature implementation map

| Capability | Entry point | Primary implementation |
|---|---|---|
| Text question answering | `crime_query/main.py` | supervisor runtime → `agent.py` preparation → ZCQL/RBAC → evidence merge → composition |
| Kannada/English and voice parity | `main.py` | `translate.py`, `voice.py`, Cache-backed conversation |
| Multi-turn investigation | `main.py` | `conversation.py`, `conversation_api.py` |
| PDF conversation export | `operation=export` | `conversation_export.py` + SmartBrowz |
| Audit viewer | `operation=audit` | `audit_api.py` and `policy_audit.py` |
| Network view | `operation=network` | `graph.py` and derived edge tables |
| Trends/hotspots | `operation=analytics` | per-station/type deterministic fallback, DBSCAN, scoped rows; live QuickML Pipeline remains an account-side enhancement |
| Behavioral profile | `operation=profile` | cited visible case narratives and identity keys |
| Demographics | `operation=demographics` | aggregate-only `ComplainantDetails`, `Victim`, and `Accused` rows |
| Similar cases | `silent_match /similar-cases` | `MoMatcher` + OperationalMoIndex |
| Graph projection | `silent_match /graph-projection` | `GraphProjectionJob` + versioned derived edge tables |
| Alert inbox/detail/actions | `silent_match /alerts...` | `SilentMatchAPI` + scope checks |
| Batch/live scan | `silent_match /scan` or Job | one `SilentMatchScanner` contract |

The silent-match loader uses `KSP_SILENT_MATCH_LOOKBACK_DAYS` (default 365).
Batch scans select anchors in the requested window and historical candidates in
that window plus the lookback. Live scans select candidates ending on the anchor
date. This keeps retrieval bounded and preserves batch/live scoring parity.

## 6. Catalyst configuration

The repository root [`catalyst.json`](../catalyst.json) is the whole-project
deployment manifest. It targets both Advanced I/O functions and the `web/`
client; the function-specific `catalyst-config.json` files remain the source
of each function's runtime and environment configuration. Its `predeploy`
hook runs [`tools/prepare_catalyst_deploy.py`](../tools/prepare_catalyst_deploy.py)
so the independently packaged `silent_match` function receives its reviewed
shared-module closure without duplicating source ownership. If a function is
uploaded directly from the console, run that preparation command first.

1. Create the official Data Store tables from [`schema-ddl.sql`](schema-ddl.sql),
   the operational tables from [`silent-match-alerts-ddl.sql`](silent-match-alerts-ddl.sql),
   and the versioned graph tables from [`derived-graph-ddl.sql`](derived-graph-ddl.sql).
2. Preserve foreign-key semantics: child FK values point to the parent
   `ROWID`; application projections expose business IDs through joins.
3. Configure authenticated API access using [`CATALYST_SECURITY.md`](CATALYST_SECURITY.md)
   and [`catalyst-security-rules.json`](catalyst-security-rules.json).
4. Set `KSP_AUTH_EMPLOYEE_MAP` to the deployment's principal-to-EmployeeID map.
5. Set the QuickML GLM endpoint, org ID, and model in
   `functions/crime_query/catalyst-config.json`.
6. Configure the multilingual embedding endpoint/model for the silent-match
   function; an empty endpoint is intentionally a live-deployment blocker.
7. Optionally configure `QUICKML_ANALYTICS_ENDPOINT`, model, and timeout for
   the validated time-series provider. It receives aggregate counts only;
   malformed or unavailable provider output falls back to the deterministic
   station-by-crime-type moving average and is marked in the response.
8. Configure `SMARTBROWZ_ENDPOINT` and grant `ZohoCatalyst.pdfshot.EXECUTE`.
9. Configure Cache, Stratus, Job Scheduling, and Circuit retry policies before
   enabling graph projection, index refresh, and proactive scans.

Deploy the two Advanced I/O functions with their local configuration files:

```bash
catalyst deploy --only functions:crime_query
catalyst deploy --only functions:silent_match
```

The exact live smoke tests and known Catalyst account limitations are in
[`CATALYST_RUNBOOK.md`](CATALYST_RUNBOOK.md). Silent-match indexing, rollback,
and alert verification are detailed in
[`silent-match-production-runbook.md`](silent-match-production-runbook.md).
The root [`catalyst-pipelines.yaml`](../catalyst-pipelines.yaml) defines the
offline verification stage used by Catalyst Pipelines; it intentionally does
not pass `--require-live`, so account-side production gates remain explicit
and cannot be bypassed by a green CI run.
Local tests do not prove live
ZCQL relationship configuration, authenticated principal mapping, QuickML
credentials, SmartBrowz conversion, or embedding availability.

## 7. Verification checklist

Before calling a deployment ready, verify all of the following against the
authenticated Catalyst project:

- Data Store row counts and every FK/ROWID relationship match the ER diagram.
- Constable, inspector, SP, and statewide requests produce the expected scope.
- Missing principal mapping and missing capability both refuse safely.
- Every answer and alert contains only authorized `CrimeNo` citations.
- Caste and religion remain descriptive aggregate dimensions only and are never
  used as person risk or predictive features.
- GLM-4.7-Flash returns a composed answer without visible reasoning traces.
- Kannada/English text and voice paths produce the same scoped evidence.
- Cache session ownership prevents cross-employee transcript access.
- SmartBrowz export returns a verified PDF or the documented safe HTML fallback.
- Similar-case retrieval never embeds an inaccessible narrative.
- Batch/live scans produce identical evidence for identical fixtures and repeat
  runs update, rather than duplicate, alerts.
- Graph edges carry source IDs, confidence, and provenance.
- Policy and query audit rows are written for both success and refusal paths.
- Job, QuickML, embedding, and SmartBrowz failures are observable and return
  bounded partial/refusal responses.

## 8. Future extensions — not production commitments

The following are intentionally outside the current implementation boundary:

- statutory deadline risk engine;
- legal-section copilot;
- automatic chargesheet or case-summary drafting;
- WhatsApp/Telegram mobile copilot;
- replacement of the derived relational graph with a dedicated graph database.

Do not add these by weakening the current citation, RBAC, audit, or sensitive
data controls.
