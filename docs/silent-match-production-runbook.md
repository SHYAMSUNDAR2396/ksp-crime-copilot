# Silent-match production runbook

This runbook covers the Catalyst deployment boundary for cross-lingual MO
matching and silent-match alerts. The implementation contract is in
[`PLAN.md`](../PLAN.md) and the code path is shared by live and batch scans.

## Components

- `functions/silent_match`: authenticated Advanced I/O API for similar cases,
  alerts, and scan requests.
- `functions/crime_query`: shared Data Store, RBAC, evidence, normalization,
  index, scorer, repository, and scanner modules.
- `functions/silent_match/index_cases.py`: deterministic index-job contract.
- `functions/silent_match/run_scan.py`: one scan contract for Job Scheduling
  and post-ingestion triggers.
- `functions/crime_query/graph_projection.py`: versioned relationship-graph
  projection job for `PersonNode`, `PersonMember`, and the derived edge tables.
- `MoEmbeddingRecord`: versioned operational records; old model/index versions
  are retained for rollback and audit.
- `MoEmbeddingJobState`: case/version indexing status and bounded retry count;
  it contains no narrative text or provider error details.

## Required configuration

Set these values in `functions/silent_match/catalyst-config.json` before
deployment. Do not commit tokens or narrative data.

| Variable | Requirement |
|---|---|
| `QUICKML_ORG_ID` | Catalyst organization ID |
| `QUICKML_EMBEDDINGS_ENDPOINT` | Authenticated QuickML multilingual endpoint; blank is not production-ready |
| `QUICKML_EMBEDDINGS_MODEL` | Provider model identifier |
| `QUICKML_EMBEDDINGS_INDEX_VERSION` | Active persisted-vector version; change only through roll-forward/rollback procedure |
| `QUICKML_EMBEDDINGS_TIMEOUT` | Positive finite request timeout |
| `QUICKML_EMBEDDINGS_BATCH_SIZE` | Positive provider batch limit |
| `KSP_SILENT_MATCH_LOOKBACK_DAYS` | Positive historical candidate window; default 365 |
| `KSP_AUTH_EMPLOYEE_MAP` | Authenticated Catalyst principal to trusted EmployeeID map |

The function obtains its short-lived OAuth token from Catalyst runtime
credentials. No embedding API key belongs in source control.

## Operational schema and index versions

Create the tables from [`silent-match-alerts-ddl.sql`](silent-match-alerts-ddl.sql)
and [`derived-graph-ddl.sql`](derived-graph-ddl.sql) before deploying the
functions. `MoEmbeddingRecord` is unique by
`CaseMasterID + IndexVersion`, not by case alone. This is intentional:

1. deploy the new normalization/model version;
2. index changed or all approved cases into the new version;
3. switch retrieval configuration to the new version;
4. retain the previous version until evaluation and rollback checks pass;
5. remove an old version only through a reviewed retention operation.

The index job skips a case already marked `indexed` for the requested version,
embeds pending cases in the provider's configured batch size, retries a failed
batch one case at a time, retries prior `failed` cases, and records only a safe
case ID/failure count in its result. Provider exceptions and narrative text are
not returned in job logs. A provider vector-count mismatch fails the affected
batch rather than silently dropping cases.

The authoritative ER model has no `Employee.Active` column. Command-recipient
eligibility therefore joins `Employee` to `Rank` and requires
`Rank.Active = 1` with `Rank.Hierarchy <= 3`; an employee-level active flag
must not be invented in the deployment schema.

## Job contracts

The job adapter receives one of these payloads after authentication and input
validation:

```json
{
  "index_version": "mo-v2",
  "trigger_source": "scheduled",
  "changed_case_ids": [101, 102]
}
```

The payload is sent to `POST /index` by a protected Job Scheduling invocation
or an authorized command role. The deployed `QUICKML_EMBEDDINGS_INDEX_VERSION`
must match the requested version; deploy the configuration change before
rolling a new version.

The relationship graph uses the same protected boundary:

```json
{
  "projection_version": "graph-v2",
  "changed_case_ids": [101, 102]
}
```

This is sent to `POST /graph-projection` by Job Scheduling or an authorized
command role. The job writes `PersonNode`, `PersonMember`, and all four
versioned edge tables, then advances `GraphProjectionState.ActiveVersion`.

```json
{
  "date_window": ["2026-06-01", "2026-06-30"],
  "trigger_source": "batch"
}
```

```json
{
  "anchor_case_id": 123,
  "trigger_source": "live"
}
```

Exactly one of `date_window` and `anchor_case_id` is required. A live scan is
started only after required FIR-side enrichment exists; incomplete cases are
reported as `pending_enrichment` and retried by the event/job policy.

Batch anchors use the requested window. Candidate cases use that window plus
`KSP_SILENT_MATCH_LOOKBACK_DAYS`; live candidates end on the anchor date. The
same `SilentMatchScanner` scoring and repository path is used in both modes.

## Deployment sequence

1. Apply the operational and derived-graph DDL and verify table/column types
   in Data Store.
2. Configure Authentication and the security rules in
   [`catalyst-security-rules.json`](catalyst-security-rules.json).
3. Configure the embedding endpoint and principal map.
4. Deploy the function:

   ```bash
   catalyst deploy --only functions:silent_match
   ```

5. Run the graph projection job and a small index job with new versions;
   verify the active projection/index state and rollback records.
6. Configure a nightly Job Scheduling window for batch scans and a completed
   FIR event for live scans. Use bounded retries and do not retry malformed
   payloads.
7. Run the authenticated smoke tests below.

## Smoke tests

Use a real authenticated Catalyst principal and synthetic fixture cases:

The read-only query/similar-case/inbox contract can be exercised with the
repository smoke runner after setting `KSP_CRIME_QUERY_URL`,
`KSP_SILENT_MATCH_URL`, and `CATALYST_TOKEN`:

```bash
python -m tools.catalyst_smoke --execute
```

Run `python -m tools.catalyst_smoke --execute --include-scan --include-projection`
only during an approved synthetic replay; these options write alert/run and
derived graph state.

- `POST /similar-cases` returns only visible candidates, both CrimeNo values,
  original excerpts, and an index/model version.
- A constable cannot retrieve a case pair outside the station scope.
- A completed bilingual anchor creates at most one unordered-pair alert.
- Replaying the live event updates evidence rather than creating a duplicate.
- Both authorized case-side recipients can see the alert; an unrelated
  principal receives no detail or excerpt.
- `GET /alerts` and `GET /alerts/{id}` return only scope-checked rows.
- `POST /alerts/{id}/transition` rejects empty notes for `Linked` and
  `Dismissed`, and retains append-only action history.
- The equivalent batch window produces the same score/evidence as the live
  anchor scan and creates zero duplicate alerts.
- A provider timeout leaves structured scoring available and reports a bounded
  failure/partial result without fabricated semantic evidence.
- Caste and religion values never appear in embeddings, score evidence, audit
  records, or alert responses.

## Rollback and failure handling

- If a new embedding model fails evaluation, switch the active index version
  back to the prior verified version; do not delete the old records first.
- If QuickML embeddings are unavailable, do not claim semantic matches. Keep
  structured scoring and explicit limitations only. The deployed bootstrap
  constructs a bounded unavailable-provider adapter instead of failing the
  whole function at startup; semantic routes return the normal service
  failure while live/batch scoring can still persist identity/structured
  evidence.
- If graph/entity enrichment fails, the silent-match scanner may continue with
  its available structured/identity evidence and records the limitation.
- Graph projection writes are versioned and idempotent; switch
  `GraphProjectionState.ActiveVersion` back to the last verified version for
  rollback rather than deleting the previous projection.
- If recipient insertion fails, the alert remains durable and the recipient
  operation is retried independently.
- If the audit sink fails, the user-facing response must be a safe refusal for
  query paths that require audit, and the operational incident must be raised.

## Current readiness gate

Offline implementation and tests do not prove a live Catalyst deployment. The
following remain account-side gates until executed and recorded:

- authenticated Catalyst CLI deployment;
- Data Store FK/ROWID and operational schema verification;
- derived graph DDL, projection version, and provenance verification;
- working QuickML multilingual embedding endpoint and latency/limit probe;
- principal-to-EmployeeID mapping;
- Job Scheduling/event configuration;
- live authorized/unauthorized alert and deduplication smoke tests.

Do not mark the silent-match module production-ready until those checks are
recorded with redacted output.
