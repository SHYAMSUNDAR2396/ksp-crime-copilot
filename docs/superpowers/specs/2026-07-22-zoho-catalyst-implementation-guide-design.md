# Design: Zoho Catalyst Implementation Guide

**Date:** 2026-07-22  
**Status:** Approved design  
**Audience:** Developers and implementers

## Goal

Create a developer-facing Catalyst runbook that explains how to configure,
implement, invoke, verify, deploy, and operate every committed KSP Crime
Copilot feature. The guide will also document future extensions separately so
they are visible without being presented as production commitments.

The guide will be created at:

`docs/zoho-catalyst-implementation-guide.md`

## Scope

### Committed capabilities

The guide covers the 17 capabilities currently committed in `PLAN.md`:

1. Multi-agent execution foundation
2. Natural-language-to-ZCQL question answering
3. Kannada/English voice interaction
4. Context-aware multi-turn investigation
5. PDF export
6. Explainability and immutable audit
7. Rank-derived capability RBAC
8. Crime pattern discovery
9. Criminal network analysis and visualization
10. Hidden-link discovery and entity resolution
11. Crime trend and hotspot detection
12. Predictive analytics and early warnings
13. Socio-demographic descriptive insights
14. Behavioral profiling
15. Proactive prevention briefing
16. Cross-lingual Kannada-English MO matching
17. Cross-jurisdiction silent-match alerts

### Future extensions

These are included in a clearly marked future section only:

- statutory deadline risk engine;
- legal-section copilot;
- auto-drafted case summary or chargesheet skeleton;
- WhatsApp/Telegram mobile copilot;
- migration of the derived graph projection to a dedicated graph database.

## Document structure

1. Purpose, production boundaries, and Catalyst constraints
2. Catalyst project foundation
3. Shared application contracts
4. Feature implementation playbooks
5. Future extension playbooks
6. Deployment and operations
7. Developer reference and readiness checklist

Each feature playbook uses the same template:

- purpose;
- Catalyst services;
- input tables and outputs;
- Function/Circuit topology;
- request or event sequence;
- implementation steps;
- API contract;
- example request and response;
- RBAC and audit requirements;
- failure and retry behavior;
- verification tests;
- operational metrics.

## Architecture

The runbook documents a shared, supervisor-led Catalyst architecture:

```text
Web Client Hosting
  -> Authentication
  -> API Gateway
  -> Supervisor Function
  -> specialist Functions in parallel
  -> Verification Function
  -> Composition Function / QuickML LLM
  -> translated response
```

Case ingestion follows a separate event path:

```text
Case ingestion
  -> ingestion Function
  -> graph/entity-resolution projection
  -> MO normalization/indexing
  -> alert evaluation
  -> Data Store
```

The guide maps responsibilities as follows:

| Responsibility | Catalyst service |
|---|---|
| HTTP entry points | API Gateway and Advanced I/O Functions |
| Orchestration | Supervisor Function and Circuits where regionally available |
| Specialist work | Independent Catalyst Functions |
| Persistent data | Data Store |
| Session state | Cache |
| Reports and files | SmartBrowz and Stratus |
| LLM and RAG | QuickML LLM Serving, RAG, and Knowledge Base |
| ML models | QuickML Pipelines and authenticated endpoints |
| Scheduled work | Catalyst Job Scheduling |
| Browser interaction | Web Client Hosting |
| Voice capture | Browser Web Speech API with Zia or external fallback |

The guide will explicitly distinguish Catalyst-native services, browser-side
capabilities, and external adapters.

## Shared contracts

The implementation guide will define and reuse these contracts:

```text
AccessContext {
  user_id,
  rank_hierarchy,
  employee_id,
  unit_id,
  district_id,
  capabilities[],
  allowed_case_scope[],
  sensitive_field_policy
}
```

```text
TaskContext {
  request_id,
  task_type,
  caller_scope,
  language,
  deadline_ms,
  retry_budget,
  citation_policy,
  active_filters[]
}
```

```text
EvidenceBundle {
  agent_name,
  status,
  claims[],
  rows_or_entities[],
  citations[],
  evidence_signals[],
  confidence,
  limitations[],
  model_or_index_version,
  elapsed_ms
}
```

Every structured or semantic answer must cite `CrimeNo`. Raw Data Store tables
are never exposed directly to the browser. LLM output cannot bypass
authorization, evidence verification, or deterministic calculations.

## Feature implementation details

The guide will identify concrete Catalyst artifacts for each feature. The
relationship and alert features will document artifacts such as:

```text
Functions:
- ingest_case
- resolve_entities
- match_mo
- build_near_edges
- score_silent_match
- write_alert
- reconcile_alerts

Data Store tables:
- PersonNode
- PersonMember
- EdgePersonCase
- EdgeCaseEmployee
- EdgeCaseSection
- EdgeCaseNear
- MoEmbeddingRecord
- SilentMatchAlert
- AlertAction
- AuditLog
```

The guide will treat the relationship layer as a derived relational graph:
Data Store holds nodes and edges, Catalyst Functions perform bounded BFS,
shortest-path, connector, and neighborhood queries, and the React client
renders graph-shaped responses. Every edge carries provenance, confidence,
resolution version, and review state.

Entity resolution will preserve source appearances in `PersonMember` rather
than merging records solely on name similarity. Silent-match scoring will use
structured, identity, graph, geographic, time, and semantic evidence; semantic
similarity alone cannot create an alert.

## Deployment and operations

The guide will describe this deployment sequence:

1. Create or update Data Store schema.
2. Configure Authentication and API Gateway.
3. Deploy Functions.
4. Configure QuickML Knowledge Base, models, and endpoints.
5. Configure Cache and Stratus.
6. Create Job Pools and scheduled jobs.
7. Seed synthetic data.
8. Run projection and index rebuilds.
9. Execute smoke tests.
10. Promote from development to production.

It will cover environment configuration, secrets, Function timeouts, retries,
partial-agent results, bulk writes, job reconciliation, model/index versioning,
audit retention, alert deduplication, graph rebuilds, rollback, and RBAC denial
monitoring.

Catalyst Job Scheduling is the scheduling boundary. Legacy Cron/Event Listener
assumptions will be documented as compatibility risks rather than presented as
the primary production design.

## Verification

Every feature playbook will include happy-path, empty-result, unauthorized,
cross-district, malformed-input, timeout/partial-agent, stale-index,
citation-completeness, and idempotent-replay tests where applicable.

The final readiness checklist will verify that tables, indexes, Functions, API
authentication, RBAC, QuickML authentication, citations, graph provenance,
alert idempotency, scheduled-job observability, sensitive-field masking, and
voice fallbacks are configured.

## Non-goals

- Replacing `PLAN.md` or the existing feature-specific implementation plans.
- Introducing a standalone database, vector store, or LLM host where Catalyst
  already provides the required service.
- Presenting future extensions as implemented functionality.
- Making caste, religion, or other sensitive demographic fields predictive
  features.
- Exposing unrestricted recursive graph traversal or uncited model output.
