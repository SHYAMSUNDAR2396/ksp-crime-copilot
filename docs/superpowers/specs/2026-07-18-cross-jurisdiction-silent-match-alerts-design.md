# Cross-Jurisdiction Silent-Match Alerts Design

Date: 2026-07-21
Project: KSP Crime Copilot
Status: Approved for written-spec review

## Goal

Build the first proactive intelligence feature for KSP Crime Copilot: one
deterministic alert engine that finds likely links between a completed FIR and
cases in other police stations or districts through both replayable batch
scans and event-ready single-case scans.

The first version must be deterministic, explainable, role-scoped, and
demo-safe. It should not require the full graph layer to exist first, but it
must preserve clean hooks so the same evidence can later feed `PersonNode` and
`Edge*` tables.

## Product Scope

Cross-Jurisdiction Silent-Match Alerts turn the product from a pull-only Q&A
system into a push intelligence system. A Catalyst Cron job, or a local
replayable batch command in development, scans anchor FIRs and persists durable
alerts when a case appears related to another case outside the anchor police
station.

The first implementation supports two alert types:

- `possible_same_person`: evidence suggests an accused in the anchor case may
  be the same person as an accused in a different case.
- `possible_linked_pattern`: no reliable accused identity match is required,
  but the cases share enough pattern evidence to warrant human review.

The alert wording must stay careful. It may say "possible same accused" or
"possible linked pattern"; it must never say that a same offender, gang, or
network is confirmed. Officers make that determination through the triage
workflow.

## Trigger Strategy

The alert engine exposes one scanner contract:

```text
scan(date_window | anchor_case_id) -> alert upserts + recipient actions
```

The batch path supplies a date window and is invoked by Catalyst Cron or a
local replay command. The live path supplies one `anchor_case_id` after FIR
ingestion completes. Both paths use the same candidate selection, scorer,
deduplication, recipient routing, and persistence code.

The live trigger runs only after the required case-side data is available:
`CaseMaster`, accused records, act/section associations, crime type, station,
district, and `BriefFacts` when present. If related records arrive separately,
the trigger waits and retries through the enrichment flow described below.

The first implementation does not require `PersonNode` or any graph edge table.
When graph evidence is available later, it enriches the same alert's
`EvidenceJSON` and does not introduce a second lifecycle.

## Data Model

Three new durable tables are required.

### `SilentMatchAlert`

One row per matched case pair.

Required fields:

- `SilentMatchAlertID`
- `AlertType`
- `AnchorCaseMasterID`
- `MatchedCaseMasterID`
- `AnchorCrimeNo`
- `MatchedCrimeNo`
- `AnchorPoliceStationID`
- `MatchedPoliceStationID`
- `AnchorDistrictID`
- `MatchedDistrictID`
- `Score`
- `ConfidenceBand`
- `Status`
- `Summary`
- `EvidenceJSON`
- `DetectionSource`
- `LastEvaluatedAt`
- `LastScanRunID`
- `GeneratedAt`
- `UpdatedAt`

`EvidenceJSON` stores structured evidence using stable signal names such as:

- `person_name_similarity`
- `person_age_band_match`
- `person_gender_match`
- `shared_crime_subhead`
- `shared_section`
- `time_window_days`
- `geo_distance_km`
- `mo_similarity`

Those names are also the graph-expansion hook. Later graph tables can materialize
the same signals without changing the alert UI or lifecycle semantics.

### `SilentMatchRecipient`

One row per alert recipient.

Required fields:

- `SilentMatchRecipientID`
- `SilentMatchAlertID`
- `RecipientEmployeeID`
- `RecipientUnitID`
- `RecipientDistrictID`
- `RecipientRoleBucket`
- `Seen`
- `SeenAt`
- `CreatedAt`

Recipients include:

- the anchor case operational side,
- the matched case operational side,
- command users for the involved district or districts.

### `SilentMatchAction`

Append-only lifecycle history.

Required fields:

- `SilentMatchActionID`
- `SilentMatchAlertID`
- `ActorEmployeeID`
- `ActionType`
- `FromStatus`
- `ToStatus`
- `Note`
- `PreviousScore`
- `PreviousConfidenceBand`
- `EvidenceSnapshotJSON`
- `CreatedAt`

`Linked` and `Dismissed` actions require a non-empty note. Notes are audit text,
not chat messages. Re-evaluation inserts an `evidence_updated` action with the
previous score, confidence band, and evidence snapshot; status transition
actions use the same table with `ActionType = status_changed`.

## Match Candidate Selection

The scanner first narrows the search space with structured filters:

1. Load anchor cases in the scan window, or the explicit completed anchor case.
2. For each anchor, select prior candidate cases outside the anchor station.
3. Prefer candidates in a different district for higher demo impact, but allow
   cross-station same-district matches because those are still operationally
   useful.
4. Restrict candidates by a configurable lookback window so the scan remains
   fast and explainable.
5. Join only existing schema tables: `CaseMaster`, `Accused`,
   `ActSectionAssociation`, `CrimeSubHead`, `Unit`, `District`, and
   `CaseMaster.BriefFacts`.

The first implementation must not depend on a graph database or external vector
store. It uses deterministic text similarity over `BriefFacts` locally. QuickML
RAG can replace only the `mo_similarity` signal later, without changing alert
storage or workflow.

## Deduplication And Re-evaluation

Deduplicate by alert type and the unordered pair of
`AnchorCaseMasterID`/`MatchedCaseMasterID`. This prevents batch and live paths
from creating separate alerts for the same pair. The stored anchor remains the
case that first produced the alert, while the pair is treated as undirected for
deduplication.

On a repeat detection, recompute the complete evidence set and update the
current score, confidence band, summary, `EvidenceJSON`, `DetectionSource`,
`LastEvaluatedAt`, and `LastScanRunID`. Before updating, insert an
`evidence_updated` action containing the previous score, confidence band, and
full previous evidence snapshot. Do not duplicate existing recipient rows.

Keep recipient `Seen` state unless a new recipient is added. A refreshed alert
does not silently reopen `Linked` or `Dismissed`; it records an evidence-update
action and surfaces the update to authorized recipients. An officer may move
the alert back to `Reviewing` explicitly.

## Scoring Rules

The scorer is a transparent weighted model over explicit signals. It is not a
predictive risk model.

### `possible_same_person`

Required identity evidence:

- normalized accused-name similarity,
- same or compatible gender when present,
- age within the configured band when both ages are present.

Supporting evidence increases confidence:

- same crime subhead,
- shared act/section,
- close incident or registration dates,
- geographic proximity,
- similar MO terms in `BriefFacts`.

The alert summary should describe the identity evidence as a candidate match,
not as a confirmed identity.

### `possible_linked_pattern`

No person match is required. The alert requires:

- at least one strong pattern signal, such as same crime subhead plus shared
  section,
- at least one contextual signal, such as time proximity, geo proximity, or MO
  similarity.

This prevents noisy alerts based only on "same crime type somewhere else."

### Confidence Bands

- `High`: strong identity evidence with supporting pattern evidence, or several
  strong pattern signals.
- `Medium`: one strong signal plus one or more contextual signals.
- `Low`: stored only for debugging or evaluation; hidden from the default inbox.

The default alert inbox shows `High` and `Medium`.

Initial implementation thresholds:

- Persist alerts at score `>= 60`.
- Show `Medium` for scores `60-79`.
- Show `High` for scores `>= 80`.
- Record sub-threshold candidate evaluations in tests, not in production alert
  tables.

Initial signal weights:

- accused identity candidate: `50`
- shared crime subhead: `15`
- shared act/section: `15`
- incident or registration dates within 30 days: `10`
- geo distance within 5 km: `10`
- deterministic MO similarity over `BriefFacts`: `10`

## Guardrails

- Caste and religion fields are never used in candidate selection, scoring, or
  summaries.
- The feature never creates a per-person risk score.
- Every alert cites both `CrimeNo`s.
- Every alert records the exact evidence signals that caused it.
- RBAC is enforced when a recipient reads an alert, not only when alerts are
  generated.
- Human-entered `Linked` and `Dismissed` dispositions are stored in
  `SilentMatchAction`.
- Generated alerts are decision support only.

## User Experience

The Alert Inbox is the operational source of truth. It appears inside the
proactive intelligence dashboard and can be linked from chat.

Inbox rows or cards show:

- alert type,
- confidence band,
- generated time,
- anchor and matched `CrimeNo`s,
- stations and districts involved,
- status,
- compact "why matched" evidence.

Users can filter by:

- `New`,
- `Reviewing`,
- `Linked`,
- `Dismissed`,
- confidence band,
- jurisdiction.

The chat push card is part of the first demo path. It renders an already
persisted alert and links back to the alert detail panel; it does not generate
or store alerts independently.

Clicking an alert opens a detail panel with:

- case-pair summary,
- side-by-side `CrimeNo` citations,
- shared evidence signals,
- allowed `BriefFacts` excerpts,
- recipient visibility,
- status history,
- actions to mark `Reviewing`, `Linked`, or `Dismissed`.

For demo impact, chat may surface a push-style assistant card:

> New possible cross-station match found.

That card links to the same durable alert detail. The inbox remains the source
of truth.

## Workflow

Initial statuses:

- `New`
- `Reviewing`
- `Linked`
- `Dismissed`

Transitions:

- `New` -> `Reviewing`
- `New` -> `Linked`
- `New` -> `Dismissed`
- `Reviewing` -> `Linked`
- `Reviewing` -> `Dismissed`

`Linked` and `Dismissed` require a note. The system should reject an empty note
for those transitions.

## Recipients And Notification

Recipients are generated from existing case ownership and command hierarchy:

- Anchor-side operational recipient: `CaseMaster.PolicePersonID`, when present
  and visible.
- Matched-side operational recipient: `ArrestSurrender.IOID`, when present and
  visible.
- District command recipients: active employees with
  `Rank.Hierarchy <= 3` in each involved district.
- Statewide command recipients: alerts spanning districts or alerts within an
  explicitly authorized district filter.

The live path creates the same durable `SilentMatchRecipient` rows as batch
mode. The alert detail endpoint rechecks access to both cases before returning
evidence. If an employee lacks access to either case, the alert is not shown
to that employee.

The inbox is the source of truth. Chat renders a card containing alert type,
confidence, both `CrimeNo`s, stations, districts, compact evidence, status,
and a link to the shared alert detail. It does not create an independent
notification or lifecycle record.

## Reliability And Failure Handling

The live trigger is asynchronous and idempotent.

- Duplicate ingestion events are safe because the scanner upserts by alert
  type and case pair.
- If accused, section, or narrative records are not ready, the trigger records
  `pending_enrichment` and retries with bounded backoff.
- If enrichment remains incomplete after the retry window, the scanner emits
  only evidence-supported alerts or skips alert creation with an auditable
  reason.
- Missing `BriefFacts` or unavailable semantic matching never blocks identity
  and structured scoring.
- Graph rebuild failure never blocks live or batch alerts.
- Recipient creation retries independently, so notification failure cannot
  duplicate an alert.
- Each run records its run id, source (`batch` or `live`), anchor count,
  candidate count, alert count, skipped cases, duration, and failure reasons.

Run metadata must distinguish "no match found" from "matching not attempted"
and "matching attempted with incomplete evidence."

## Testing Requirements

Tests should prove correctness, auditability, and RBAC safety.

Required coverage:

- scorer tests for both alert types,
- tests explaining why a candidate did or did not meet threshold,
- batch and single-anchor live scan tests that produce identical alerts from
  identical seeded data,
- duplicate-trigger tests proving idempotent upsert behavior,
- re-evaluation tests proving evidence updates preserve append-only history and
  do not silently reopen terminal statuses,
- recipient-routing tests for anchor side, matched side, and command users,
- enrichment retry and partial-evidence tests,
- lifecycle tests for valid transitions and required notes,
- action-history tests proving events are append-only,
- RBAC read tests proving recipients can see their alerts and unrelated users
  cannot,
- regression tests proving caste and religion are never scoring inputs.

## Synthetic And Demo Data

The synthetic data generator should seed a small set of deliberate cases:

- one high-confidence same-person match across at least two stations,
- one medium-confidence linked-pattern match without a person match,
- one near miss that should not alert,
- one cross-district alert for the main demo moment.

The demo flow:

1. Replay or register a new FIR.
2. Trigger the live scanner after ingestion completes.
3. Show the alert appearing in both authorized users' inboxes and the chat
   card.
4. Open the alert detail panel and explain the evidence.
5. Run the batch scanner over the same period and show that it creates no
   duplicate.
6. Refresh evidence, rerun, and show the score/history update.
7. Mark the alert `Reviewing` or `Linked` with an audit note.

## Out Of Scope

- Graph-gated alert generation and full graph traversal APIs.
- Full officer collaboration, assignment, or messaging.
- SMS, email, WhatsApp, or Telegram delivery.
- Predictive offender scoring.
- Use of caste or religion as features.
- External vector database or non-Catalyst services.

## Implementation Decisions For Planning

- Alert tables are operational tables, like `AuditLog`. They must be created by
  local DDL and Catalyst Data Store setup, but kept out of the NL-to-SQL query
  allowlist so the LLM cannot freely query operational alert history.
- The same scanner must accept either a date window or a single completed
  anchor case. Catalyst Cron invokes the former; a post-ingestion Function
  invokes the latter.
- Command recipients are active employees with `Rank.Hierarchy <= 3` in each
  involved district. Statewide ranks receive the alert only when the alert spans
  districts or when their explicit inbox filter includes that district.
- Operational case-side recipients are the case registering officer
  (`CaseMaster.PolicePersonID`) and any arrest IO (`ArrestSurrender.IOID`) when
  present and visible under RBAC.
