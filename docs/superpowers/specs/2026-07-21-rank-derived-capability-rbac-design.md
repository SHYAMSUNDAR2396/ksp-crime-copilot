# Rank-Derived Capability RBAC Design

Date: 2026-07-21
Project: KSP Crime Copilot
Status: Approved for written-spec review

## Goal

Add explicit capability-based access control to the supervisor-led multi-agent
architecture while keeping Rank.Hierarchy, Employee.UnitID, and Employee.DistrictID
as the only authority source.

The design controls specialist dispatch, data retrieval, graph access,
cross-jurisdiction alerts, scans, exports, dispositions, and audit visibility.
It must default-deny, preserve existing sensitive-field masking, and never
leak inaccessible case metadata.

## Authority Model

Do not introduce a separate role database. Resolve an immutable AccessContext
from the existing schema:

- Employee.EmployeeID
- Employee.UnitID
- Employee.DistrictID
- Employee.RankID -> Rank.Hierarchy

Lower Rank.Hierarchy values indicate higher authority. The system derives five
access buckets:

| Bucket | Data scope |
|---|---|
| Constable | Own police station |
| SI/IO | Own district and assigned investigation context |
| Inspector | Own district and district intelligence |
| SP/Command | District-wide command intelligence and approved aggregates |
| DGP/Statewide | Statewide intelligence and cross-district operations |

The bucket is a policy classification, not a new stored role. The existing
rank and station/district relationships remain the hard data boundary.

## AccessContext

The supervisor resolves the caller once per request or proactive task:

~~~
AccessContext {
  employee_id,
  rank_hierarchy,
  access_bucket,
  unit_ids,
  district_ids,
  capabilities[],
  sensitive_data_policy,
  alert_actions[],
  audit_visibility
}
~~~

AccessContext is immutable for the lifetime of a task. It may be stored in
request-scoped task context, but sensitive case values must not be copied into
Cache merely to enforce policy.

## Capabilities

The initial capability vocabulary is:

- query_structured_cases
- retrieve_narratives
- retrieve_similar_cases
- view_graph
- view_cross_jurisdiction_alerts
- review_alerts
- dispose_alerts
- run_batch_scan
- run_live_scan
- view_deadline_risk
- export_conversation
- view_audit

Capabilities are default-denied. A specialist is dispatched only when the
AccessContext grants the capability required by that specialist. Capability
authorization does not override jurisdiction or sensitive-field policies.

## Capability Matrix

| Capability | Constable | SI/IO | Inspector | SP/Command | DGP/Statewide |
|---|---|---|---|---|---|
| Structured case queries | Own station | District | District | District | Statewide |
| Narrative retrieval | Own station | District | District | District | Statewide |
| Similar-case search | Own station | District | District | District | Statewide |
| Graph/network view | Denied | District | District | District | Statewide |
| Cross-jurisdiction alerts | Denied | Visible assigned cases | District | District | Statewide |
| Review alerts | Denied | Assigned/visible cases | District | District | Statewide |
| Dispose alerts | Denied | Assigned cases | District | District | Statewide |
| Run batch scan | Denied | Denied | Denied | Approved district | Approved statewide |
| Run live scan | Denied | Own assigned case | District case | District | Statewide |
| Deadline-risk view | Own cases | Assigned cases | District | District | Statewide |
| Conversation export | Own session | Own session | Own session | Own session | Own session |
| Audit view | Own actions | Own actions | District actions | District audit | Statewide summary |

The table grants a maximum scope. The actual result is the intersection of
capability, jurisdiction, case visibility, and sensitive-field policy.

Alert visibility and alert disposition are separate. An employee may review
an alert without being allowed to move it to Linked or Dismissed. Linked and
Dismissed transitions continue to require a non-empty note.

## Enforcement Flow

RBAC is enforced throughout the multi-agent task graph:

1. API Gateway authenticates the employee.
2. AccessContext is resolved from Rank, Employee, Unit, and District.
3. The Supervisor filters the task graph by required capability.
4. Each dispatched specialist receives the immutable AccessContext.
5. Data loaders apply station/district scope before retrieval.
6. The evidence merger drops bundles outside the caller's scope.
7. The verifier rejects inaccessible citations, entities, and excerpts.
8. The response layer applies masking and action checks again.

No agent may bypass the supervisor, query operational alert tables through
NL-to-SQL, or return a resource that the caller cannot read directly.

## Agent Requirements

Every specialist declares a required capability and resource scope:

~~~
AgentSpec {
  name,
  required_capabilities[],
  resource_types[],
  supports_partial_results,
  timeout_ms,
  retry_policy
}
~~~

Examples:

- Structured Query Agent requires query_structured_cases.
- Narrative Retrieval Agent requires retrieve_narratives.
- MoMatcher search requires retrieve_similar_cases.
- Graph Agent requires view_graph.
- SilentMatchAgent requires view_cross_jurisdiction_alerts for reads and
  dispose_alerts only for lifecycle writes.
- Scan jobs require run_batch_scan or run_live_scan.
- Audit Agent requires view_audit.

An agent receiving an inaccessible resource returns a typed SCOPE_DENIED result.
It must not return a partial identifier, CrimeNo, name, excerpt, graph node, or
alert score unless that item is independently visible.

## Errors and Audit

Use stable policy error codes:

- CAPABILITY_DENIED: the rank bucket lacks the requested capability.
- SCOPE_DENIED: the capability exists, but the resource is outside unit,
  district, assignment, or statewide scope.
- SENSITIVE_FIELD_DENIED: the requested projection violates masking policy.
- ACTION_DENIED: the employee can read the resource but cannot perform the
  requested lifecycle action.

Denied operations are not agent failures. The supervisor records the denial
and either returns a safe refusal or continues without that specialist when the
task policy permits partial evidence.

Audit records include:

- employee id and rank hierarchy;
- access bucket and capability;
- task/request id;
- resource type and non-sensitive resource identifier;
- allowed or denied result;
- denial code or action;
- selected specialists;
- evidence bundle ids;
- final response or alert outcome;
- policy version.

Audit viewers are themselves scope-limited. A user cannot use audit records to
discover cases outside their normal visibility.

## Sensitive Data Guardrails

Existing caste/religion protections remain independent from capability grants:

- Caste and religion fields never enter agent inputs, semantic text, features,
  alert evidence, summaries, or logs.
- Authorized aggregate access does not grant row-level sensitive access.
- No rank bucket can use caste or religion in predictive, semantic, identity,
  or alert scoring.
- Error messages, citations, chat cards, exports, and audit views use the same
  masking policy as direct query results.

## Testing Requirements

Tests must cover:

- all five rank buckets;
- own-station, own-district, cross-district, and statewide boundaries;
- every capability in the matrix;
- default-deny behavior;
- supervisor dispatch suppression;
- agent-level scope checks;
- evidence-bundle filtering;
- inaccessible citation and excerpt rejection;
- sensitive-field masking and exclusion from logs;
- cross-jurisdiction alert visibility;
- separate review and disposition permissions;
- required notes for Linked and Dismissed;
- batch/live scan authorization;
- export scope;
- audit visibility boundaries;
- no resource leakage through error messages or partial results.

The existing query, RBAC, translation, alert, and matching test suites must
continue to pass.

## Out Of Scope

- A new role or permissions table.
- User-configurable roles.
- Cross-agency identity federation.
- Emergency bypass or break-glass access.
- Changes to the frozen crime schema.
- Relaxing caste/religion masking.
- Authorization based on model confidence or agent recommendation.

