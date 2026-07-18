# Cross-Jurisdiction Silent-Match Alerts Design

Date: 2026-07-18
Project: KSP Crime Copilot
Status: Approved for implementation planning

## Goal

Build the first proactive intelligence feature for KSP Crime Copilot: a
replayable batch alert system that finds likely links between newly registered
or recently scanned FIRs and cases in other police stations or districts.

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

The system supports two alert types:

- `possible_same_person`: evidence suggests an accused in the anchor case may
  be the same person as an accused in a different case.
- `possible_linked_pattern`: no reliable accused identity match is required,
  but the cases share enough pattern evidence to warrant human review.

The alert wording must stay careful. It may say "possible same accused" or
"possible linked pattern"; it must never say that a same offender, gang, or
network is confirmed. Officers make that determination through the triage
workflow.

## Trigger Strategy

The design supports an event-ready product story but implements the reliable
path first.

Initial implementation:

- A replayable batch scan selects anchor cases by a date window.
- In production this maps to Catalyst Cron.
- In local development and demos the same scanner can be run for a chosen
  window so the alert moment is deterministic.

Later trigger, using the same scanner interface:

- A Data Store insert or post-ingestion Function can call the same scanner for
  one anchor case when FIR registration events are available.
- The scanner API should therefore accept both a date window and an explicit
  anchor case id.

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
- `FromStatus`
- `ToStatus`
- `Note`
- `CreatedAt`

`Linked` and `Dismissed` actions require a non-empty note. Notes are audit text,
not chat messages.

## Match Candidate Selection

The scanner first narrows the search space with structured filters:

1. Load anchor cases in the scan window, or the explicit anchor case.
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

## Testing Requirements

Tests should prove correctness, auditability, and RBAC safety.

Required coverage:

- scorer tests for both alert types,
- tests explaining why a candidate did or did not meet threshold,
- batch scan tests that generate deterministic alerts from seeded synthetic
  data,
- recipient-routing tests for anchor side, matched side, and command users,
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
2. Run the batch scan for the selected window.
3. Show the alert appearing in the inbox and chat card.
4. Open the alert detail panel and explain the evidence.
5. Mark the alert `Reviewing` or `Linked` with an audit note.

## Out Of Scope

- Full graph materialization and graph traversal APIs.
- Real-time Data Store trigger integration.
- Full officer collaboration, assignment, or messaging.
- Predictive offender scoring.
- Use of caste or religion as features.
- External vector database or non-Catalyst services.

## Implementation Decisions For Planning

- Alert tables are operational tables, like `AuditLog`. They must be created by
  local DDL and Catalyst Data Store setup, but kept out of the NL-to-SQL query
  allowlist so the LLM cannot freely query operational alert history.
- Command recipients are active employees with `Rank.Hierarchy <= 3` in each
  involved district. Statewide ranks receive the alert only when the alert spans
  districts or when their explicit inbox filter includes that district.
- Operational case-side recipients are the case registering officer
  (`CaseMaster.PolicePersonID`) and any arrest IO (`ArrestSurrender.IOID`) when
  present and visible under RBAC.
