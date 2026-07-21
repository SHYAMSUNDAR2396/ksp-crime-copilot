# Rank-Derived Capability RBAC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Add rank-derived, default-deny capability authorization across the supervisor, existing query path, semantic/graph agents, silent-match alerts, scans, exports, and audit views.

**Architecture:** Keep SQL station/district scoping and sensitive-field masking in functions/crime_query/rbac.py. Add functions/crime_query/access.py as the single capability policy boundary that resolves immutable AccessContext from existing rank/unit/district data. The Supervisor gates specialist dispatch, each agent receives AccessContext, evidence merging rechecks scope, and alert/API handlers enforce resource and action permissions before returning or mutating state.

**Tech Stack:** Python 3.9, existing SQLite/ZCQL Catalyst backends, sqlglot, Flask/Catalyst Advanced I/O, pytest, and the existing Data Store AuditLog. No role table, permissions table, external identity provider, or schema change is introduced.

## Global Constraints

- Do not introduce a separate role database. Authority comes from Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, and Employee.RankID -> Rank.Hierarchy.
- Lower Rank.Hierarchy values indicate higher authority.
- Derive five buckets: Constable, SI/IO, Inspector, SP/Command, and DGP/Statewide.
- Capabilities are default-denied.
- Capability authorization never overrides station, district, assignment, case visibility, or sensitive-field policies.
- Apply policy at gateway/entrypoint, supervisor dispatch, agent resource access, evidence merge, verifier, and response/action layers.
- Use stable errors CAPABILITY_DENIED, SCOPE_DENIED, SENSITIVE_FIELD_DENIED, and ACTION_DENIED.
- Do not return partial identifiers, CrimeNos, names, excerpts, graph nodes, or alert scores for inaccessible resources.
- Existing caste/religion masking remains independent of capability grants and applies to queries, agents, alerts, citations, chat cards, exports, and audit views.
- Alert visibility and alert disposition are separate capabilities; Linked and Dismissed still require a non-empty note.
- Operational alert tables remain outside the NL-to-SQL allowlist.
- Preserve Python 3.9 compatibility, deployed absolute-import fallbacks, and Catalyst ROWID join rules.
- No emergency bypass, user-configurable roles, or schema changes.

---

## File Structure

Create:

~~~
functions/crime_query/access.py
functions/crime_query/supervisor.py
functions/crime_query/policy_audit.py

tests/test_access.py
tests/test_supervisor_access.py
tests/test_policy_audit.py
~~~

Modify:

~~~
functions/crime_query/rbac.py
functions/crime_query/agent.py
functions/crime_query/main.py
functions/crime_query/db.py
functions/crime_query/silent_match_api.py
functions/crime_query/silent_match_scanner.py
functions/crime_query/silent_match_repository.py
tests/test_rbac.py
tests/test_agent.py
tests/test_main.py
tests/test_silent_match_api.py
tests/test_silent_match_scanner.py
tests/test_silent_match_repository.py
PLAN.md
docs/silent-match-production-runbook.md
~~~

The current query path remains compatible with handle_question(payload, db,
llm, translator, today). The capability layer is injected through the resolved
AccessContext and does not require callers to understand policy internals.

## Shared Interfaces

~~~
class AccessContext(object):
    employee_id
    rank_hierarchy
    access_bucket
    unit_ids
    district_ids
    capabilities
    sensitive_data_policy
    alert_actions
    audit_visibility

    def has(self, capability):
        # -> bool
        raise NotImplementedError

class AccessPolicyError(Exception):
    code

def resolve_access_context(caller, db):
    # -> AccessContext

def require_capability(context, capability):
    # returns None or raises AccessPolicyError

def can_read_case(context, case_bundle):
    # -> bool

def can_read_case_pair(context, anchor_bundle, matched_bundle):
    # -> bool

def can_act_on_alert(context, alert, action):
    # -> bool or raises ACTION_DENIED

class AgentSpec(object):
    name
    required_capabilities
    resource_types
    supports_partial_results
    timeout_ms
    retry_policy

class TaskContext(object):
    request_id
    access_context
    task_type
    resource_scope
    selected_agents
    deadline_ms

class EvidenceBundle(object):
    agent_name
    status
    claims
    rows_or_entities
    citations
    evidence_signals
    confidence
    limitations
    policy_version
~~~

Use immutable dataclasses or equivalent frozen DTOs. The policy version is a
constant such as access-policy-v1 and is recorded in audit events.

### Task 1: Implement rank-derived AccessContext and capability matrix

**Files:**
- Create: functions/crime_query/access.py
- Create: tests/test_access.py
- Test fixtures: tests/test_access.py

**Interfaces:**
- Consumes: rbac.Caller, db.units_in_district(), and the existing rank hierarchy.
- Produces: AccessBucket, Capability constants, AccessContext,
  resolve_access_context(), has_capability(), require_capability(),
  can_read_case(), can_read_case_pair(), and can_act_on_alert().

Use this exact rank mapping:

~~~python
STATEWIDE_MAX_HIERARCHY = 2
COMMAND_HIERARCHY = 3
INSPECTOR_HIERARCHY = 4
SI_IO_HIERARCHY = 5

def bucket_for_rank(rank_hierarchy):
    if rank_hierarchy <= STATEWIDE_MAX_HIERARCHY:
        return "DGP_STATEWIDE"
    if rank_hierarchy == COMMAND_HIERARCHY:
        return "SP_COMMAND"
    if rank_hierarchy == INSPECTOR_HIERARCHY:
        return "INSPECTOR"
    if rank_hierarchy == SI_IO_HIERARCHY:
        return "SI_IO"
    return "CONSTABLE"
~~~

The capability grants must match the approved matrix. Constables get own-station
structured/narrative/similar-case reads and own-session export. SI/IO gets
district reads, visible assigned alert reads, assigned alert review/disposition,
own-assigned live scans, own-case deadline view, and own-session export.
Inspectors get district intelligence and district alert review/disposition but
no batch scans. SP/Command gets district batch scans, district intelligence,
and district audit. DGP/Statewide gets statewide intelligence, approved
statewide scans, and statewide audit summaries. Graph access follows the matrix;
it is denied to Constables.

- [ ] **Step 1: Write failing rank/capability tests.**

~~~python
def test_rank_three_is_sp_command():
    caller = Caller(employee_id=1, unit_id=1, district_id=1,
                    rank_hierarchy=3)
    context = resolve_access_context(caller, fake_db)
    assert context.access_bucket == "SP_COMMAND"
    assert context.has("run_batch_scan")
    assert not context.has("run_live_scan")

def test_constable_defaults_to_own_station_reads_only():
    caller = Caller(employee_id=2, unit_id=7, district_id=2,
                    rank_hierarchy=6)
    context = resolve_access_context(caller, fake_db)
    assert context.unit_ids == (7,)
    assert context.district_ids == (2,)
    assert context.has("retrieve_similar_cases")
    assert not context.has("view_graph")
    assert not context.has("view_cross_jurisdiction_alerts")
    assert not context.has("dispose_alerts")

def test_unknown_capability_is_denied():
    context = resolve_access_context(constable, fake_db)
    with pytest.raises(AccessPolicyError) as error:
        require_capability(context, "invented_capability")
    assert error.value.code == "CAPABILITY_DENIED"
~~~

- [ ] **Step 2: Run tests and verify failure.**

Run: python3 -m pytest tests/test_access.py -q

Expected: FAIL because access.py and its policy types do not exist.

- [ ] **Step 3: Implement frozen AccessContext and matrix.**

Represent statewide scope with None and scoped jurisdictions with immutable tuples.
Do not query or copy case rows while constructing AccessContext. Keep the
sensitive_data_policy explicit, with caste/religion always masked unless the
existing aggregate policy permits the exact projection.

- [ ] **Step 4: Implement resource predicates.**

can_read_case() must check the case station/district against context scope and,
for SI/IO assigned-case operations, the caller's employee ownership fields.
can_read_case_pair() must require both cases to be visible. can_act_on_alert()
must distinguish review from dispose and return ACTION_DENIED when the alert is
readable but the requested transition is not allowed.

- [ ] **Step 5: Run focused tests.**

Run: python3 -m pytest tests/test_access.py -q

Expected: PASS.

- [ ] **Step 6: Commit the policy core.**

~~~bash
git add functions/crime_query/access.py tests/test_access.py
git commit -m "feat: add rank-derived capability policy"
~~~

### Task 2: Integrate AccessContext with the existing SQL/RBAC path

**Files:**
- Modify: functions/crime_query/rbac.py
- Modify: functions/crime_query/agent.py
- Modify: functions/crime_query/main.py
- Test: tests/test_rbac.py
- Test: tests/test_agent.py
- Test: tests/test_main.py

**Interfaces:**
- Consumes: resolve_access_context(), require_capability(), and existing
  Caller/allowed_units()/masking functions.
- Produces: handle_question() responses with stable policy_code values and
  capability-aware structured-query dispatch while preserving answer, rows,
  citations, language, and sql keys.

- [ ] **Step 1: Add failing entrypoint policy tests.**

~~~python
def test_structured_question_requires_query_capability(db, llm, translator):
    payload = {"employee_id": 9, "question": "How many cases are open?"}
    result = main.handle_question(payload, db, llm, translator, TODAY,
                                   access_context=constable_without_query)
    assert result["refused"] is True
    assert result["policy_code"] == "CAPABILITY_DENIED"
    assert result["rows"] == []
    assert result["citations"] == []

def test_existing_constable_query_contract_is_unchanged(db, llm, translator):
    result = main.handle_question(valid_payload, db, llm, translator, TODAY)
    assert result["refused"] is False
    assert "answer" in result
    assert "citations" in result
~~~

The implementer must preserve the old five-argument call by making
access_context optional only at the public boundary; production handler must
always resolve it from the caller and pass it to the supervisor.

- [ ] **Step 2: Run and verify failure.**

Run: python3 -m pytest tests/test_rbac.py tests/test_agent.py tests/test_main.py -q

Expected: FAIL because handle_question has no AccessContext parameter and no
policy_code response.

- [ ] **Step 3: Add capability-aware query dispatch.**

Require query_structured_cases before calling agent.answer(). Keep existing
SQL AST scoping/masking in rbac.py. Do not replace allowed_units() with
capabilities; capabilities decide whether the operation may start, while
allowed_units() decides which rows it may see.

- [ ] **Step 4: Add safe policy responses.**

Return policy_code CAPABILITY_DENIED or SCOPE_DENIED with no SQL, rows,
citations, CrimeNos, names, or narratives. Keep HTTP status 403 in
main.handler() for refused policy results.

- [ ] **Step 5: Run regression tests.**

Run: python3 -m pytest tests/test_rbac.py tests/test_agent.py tests/test_main.py -q

Expected: PASS, including all existing masking and station/district scope tests.

- [ ] **Step 6: Commit SQL-path integration.**

~~~bash
git add functions/crime_query/rbac.py functions/crime_query/agent.py \
  functions/crime_query/main.py tests/test_rbac.py tests/test_agent.py \
  tests/test_main.py
git commit -m "feat: enforce capabilities on structured queries"
~~~

### Task 3: Add supervisor agent requirements and evidence-bundle policy

**Files:**
- Create: functions/crime_query/supervisor.py
- Create: tests/test_supervisor_access.py
- Modify: functions/crime_query/agent.py
- Modify: functions/crime_query/main.py

**Interfaces:**
- Consumes: AccessContext, AgentSpec, TaskContext, EvidenceBundle, and the
  existing structured-query agent.
- Produces: Supervisor.create_task(), Supervisor.select_agents(),
  Supervisor.dispatch(), filter_evidence_bundles(), and stable denial bundles.

Agent requirements must be explicit:

~~~python
AGENT_REQUIREMENTS = {
    "structured_query": ("query_structured_cases",),
    "narrative_retrieval": ("retrieve_narratives",),
    "similar_case_search": ("retrieve_similar_cases",),
    "graph": ("view_graph",),
    "silent_match_read": ("view_cross_jurisdiction_alerts",),
    "batch_scan": ("run_batch_scan",),
    "live_scan": ("run_live_scan",),
    "export": ("export_conversation",),
    "audit": ("view_audit",),
}
~~~

- [ ] **Step 1: Write failing supervisor-policy tests.**

~~~python
def test_supervisor_does_not_dispatch_graph_to_constable():
    task = supervisor.create_task(question="show linked cases",
                                  access_context=constable_context)
    selected = supervisor.select_agents(task)
    assert "graph" not in selected
    assert task.denials[0].code == "CAPABILITY_DENIED"

def test_scope_denied_bundle_is_removed_before_verification():
    bundle = EvidenceBundle(
        agent_name="graph",
        status="ok",
        rows_or_entities=[outside_scope_node],
        citations=["outside-crime-no"],
    )
    filtered = filter_evidence_bundles([bundle], constable_context)
    assert filtered == []
~~~

- [ ] **Step 2: Run and verify failure.**

Run: python3 -m pytest tests/test_supervisor_access.py -q

Expected: FAIL because supervisor.py and bundle filtering do not exist.

- [ ] **Step 3: Implement supervisor task creation and selection.**

Create TaskContext with request id, task type, access context, resource scope,
selected agents, deadline, and policy version. Select only agents whose
required capabilities are present. A denied optional specialist becomes an
audited denial; a denied required capability becomes a safe refused result.

- [ ] **Step 4: Implement EvidenceBundle validation/filtering.**

Reject bundles with missing agent name, unknown policy version, inaccessible
citations, or resource identifiers outside the AccessContext. Do not redact
an inaccessible bundle into a partial result; drop it and record SCOPE_DENIED.

- [ ] **Step 5: Run tests and existing agent tests.**

Run: python3 -m pytest tests/test_supervisor_access.py tests/test_agent.py tests/test_main.py -q

Expected: PASS.

- [ ] **Step 6: Commit supervisor enforcement.**

~~~bash
git add functions/crime_query/supervisor.py \
  functions/crime_query/agent.py functions/crime_query/main.py \
  tests/test_supervisor_access.py
git commit -m "feat: gate specialist dispatch with capabilities"
~~~

### Task 4: Enforce alert visibility, review, and disposition permissions

**Files:**
- Modify: functions/crime_query/silent_match_api.py
- Modify: functions/crime_query/silent_match_repository.py
- Modify: functions/crime_query/silent_match_scanner.py
- Test: tests/test_silent_match_api.py
- Test: tests/test_silent_match_repository.py
- Test: tests/test_silent_match_scanner.py

**Interfaces:**
- Consumes: AccessContext, can_read_case_pair(), can_act_on_alert(), and the
  existing alert/repository/scanner contracts from the silent-match plan.
- Produces: capability-aware alert reads, transition checks, and scan checks.

- [ ] **Step 1: Write failing alert authorization tests.**

~~~python
def test_constable_cannot_read_cross_jurisdiction_alert(api_client):
    response = api_client.get("/alerts/1", employee_id=constable_id)
    assert response.status_code == 403
    assert response.json["policy_code"] == "CAPABILITY_DENIED"
    assert "CrimeNo" not in response.text

def test_readable_alert_does_not_imply_disposition(api_client):
    response = api_client.post(
        "/alerts/1/transition",
        employee_id=si_id,
        json={"to_status": "Linked", "note": "linked"},
    )
    assert response.status_code == 403
    assert response.json["policy_code"] == "ACTION_DENIED"

def test_batch_scan_requires_command_capability(scanner):
    with pytest.raises(AccessPolicyError) as error:
        scanner.scan(date_window=("2026-06-01", "2026-06-30"),
                     access_context=inspector_context)
    assert error.value.code == "CAPABILITY_DENIED"
~~~

- [ ] **Step 2: Run and verify failure.**

Run: python3 -m pytest tests/test_silent_match_api.py \
  tests/test_silent_match_repository.py tests/test_silent_match_scanner.py -q

Expected: FAIL because alert endpoints and scans do not yet enforce
AccessContext capabilities.

- [ ] **Step 3: Guard alert reads with both capability and pair scope.**

GET alert detail requires view_cross_jurisdiction_alerts and
can_read_case_pair(). The repository must not return alert evidence before this
policy check. Chat/inbox serializers use the same guarded read method.

- [ ] **Step 4: Guard transitions separately.**

Review requires review_alerts. Linked and Dismissed require dispose_alerts,
case visibility, valid transition, and a non-empty note. Return ACTION_DENIED
when read is allowed but mutation is not.

- [ ] **Step 5: Guard scan triggers.**

The batch entrypoint requires run_batch_scan. The live entrypoint requires
run_live_scan and an anchor case visible under the caller's assigned/district
scope. Cron/system invocations use an explicit service principal context,
never a fake employee id.

- [ ] **Step 6: Run focused alert tests.**

Run: python3 -m pytest tests/test_silent_match_api.py \
  tests/test_silent_match_repository.py tests/test_silent_match_scanner.py -q

Expected: PASS.

- [ ] **Step 7: Commit alert policy enforcement.**

~~~bash
git add functions/crime_query/silent_match_api.py \
  functions/crime_query/silent_match_repository.py \
  functions/crime_query/silent_match_scanner.py \
  tests/test_silent_match_api.py tests/test_silent_match_repository.py \
  tests/test_silent_match_scanner.py
git commit -m "feat: enforce capability access on silent-match alerts"
~~~

### Task 5: Add policy audit events and scope-safe exports

**Files:**
- Create: functions/crime_query/policy_audit.py
- Modify: functions/crime_query/db.py
- Modify: functions/crime_query/main.py
- Modify: functions/crime_query/silent_match_api.py
- Test: tests/test_policy_audit.py
- Test: tests/test_main.py
- Test: tests/test_silent_match_api.py

**Interfaces:**
- Consumes: AccessContext, policy error codes, existing AuditLog append
  primitives, and export/alert serializers.
- Produces: record_policy_decision(), record_agent_selection(),
  scope_safe_export(), and audit-scope filtering.

- [ ] **Step 1: Write failing audit and export tests.**

~~~python
def test_denial_audit_excludes_case_metadata(audit_db):
    record_policy_decision(
        audit_db, context=constable_context,
        capability="view_graph", code="CAPABILITY_DENIED",
        resource_type="graph",
    )
    row = audit_db.last_policy_event()
    assert row["EmployeeID"] == constable_context.employee_id
    assert "CrimeNo" not in row["Question"]
    assert "BriefFacts" not in row["Question"]

def test_export_is_limited_to_callers_own_session():
    result = scope_safe_export(
        context=inspector_context,
        requested_session_id="other-session",
        rows=[{"CrimeNo": "secret"}],
    )
    assert result.code == "SCOPE_DENIED"
    assert result.rows == []
~~~

- [ ] **Step 2: Run and verify failure.**

Run: python3 -m pytest tests/test_policy_audit.py -q

Expected: FAIL because policy_audit.py and scope-safe export do not exist.

- [ ] **Step 3: Implement policy audit records.**

Record employee id, rank hierarchy, access bucket, capability, task id,
resource type, allow/deny result, denial code/action, selected agents, bundle
ids, outcome, and policy version. Do not place narratives, sensitive fields,
or unauthorized identifiers into policy audit text.

- [ ] **Step 4: Implement audit visibility.**

Own-action viewers see only their own policy events. District audit viewers see
events whose resource scope is inside their district. Statewide viewers see the
approved summary scope. Audit queries use fixed repository methods and remain
outside NL-to-SQL.

- [ ] **Step 5: Implement export checks.**

Require export_conversation and exact session ownership. Re-run normal citation
and masking logic on exported rows; do not trust cached rendered content.

- [ ] **Step 6: Run tests.**

Run: python3 -m pytest tests/test_policy_audit.py tests/test_main.py \
  tests/test_silent_match_api.py -q

Expected: PASS.

- [ ] **Step 7: Commit audit and export enforcement.**

~~~bash
git add functions/crime_query/policy_audit.py functions/crime_query/db.py \
  functions/crime_query/main.py functions/crime_query/silent_match_api.py \
  tests/test_policy_audit.py tests/test_main.py tests/test_silent_match_api.py
git commit -m "feat: audit capability decisions and scope exports"
~~~

### Task 6: Update PLAN.md and operational runbook

**Files:**
- Modify: PLAN.md
- Modify: docs/silent-match-production-runbook.md
- Test: docs-only verification commands

**Interfaces:**
- Consumes: the AccessContext, capability matrix, error codes, and enforcement
  flow defined above.
- Produces: architecture documentation that matches the implementation and
  production runbook steps for rank-boundary and denial verification.

- [ ] **Step 1: Add the RBAC contract to PLAN.md.**

Add a subsection under the supervisor contract with AccessContext, AgentSpec,
capability-based dispatch, evidence-bundle filtering, and the four stable policy
errors. Add the five-bucket capability matrix and state that rank/unit/district
remain the sole authority source.

- [ ] **Step 2: Update PLAN.md diagrams.**

Show API Gateway -> AccessContext -> Supervisor -> capability-filtered parallel
agents -> evidence verifier. Show alert reads/actions passing through separate
visibility and disposition gates.

- [ ] **Step 3: Update the scope, risks, metrics, and definition of done.**

Include default-deny behavior, policy-decision audit coverage, no-leakage
tests, alert disposition separation, and batch/live scan authorization.

- [ ] **Step 4: Add production runbook checks.**

Document test users for all five buckets, safe denial examples, district
boundary checks, alert visibility/disposition checks, export ownership, and
audit-view scope. Include exact commands:

~~~bash
python3 -m pytest tests/test_access.py tests/test_supervisor_access.py \
  tests/test_policy_audit.py -q
python3 -m pytest tests/test_rbac.py tests/test_main.py \
  tests/test_silent_match_api.py tests/test_silent_match_scanner.py -q
~~~

- [ ] **Step 5: Verify documentation consistency.**

Run: git diff --check

Expected: no output. Confirm every capability in the spec appears in PLAN.md
and every policy error appears in the API/runbook contract.

- [ ] **Step 6: Commit documentation.**

~~~bash
git add PLAN.md docs/silent-match-production-runbook.md
git commit -m "docs: add capability RBAC architecture and runbook"
~~~

### Task 7: Full verification and rollout gate

**Files:**
- Modify: docs/silent-match-production-runbook.md
- Test: all existing and new test modules

**Interfaces:**
- Consumes: all policy, supervisor, query, alert, export, and audit changes.
- Produces: passing local suite, Catalyst smoke evidence, and explicit rollout
  decision.

- [ ] **Step 1: Run the full local suite.**

Run: python3 -m pytest -q

Expected: all existing query, validation, translation, generator, RBAC,
matching, alert, supervisor, policy-audit, and API tests pass.

- [ ] **Step 2: Verify rank-boundary matrix against seeded employees.**

For each bucket, issue one allowed query and one denied capability request.
Verify that denied responses contain only policy_code and safe text, with no
CrimeNo, names, excerpts, graph nodes, or alert scores.

- [ ] **Step 3: Verify alert separation.**

Using authorized fixtures, prove an employee can read an alert but cannot
dispose it when dispose_alerts is absent. Prove Linked and Dismissed reject
empty notes. Prove unauthorized cross-district alert detail is denied.

- [ ] **Step 4: Verify audit visibility.**

Prove own-action, district, and statewide audit viewers see only their approved
scope. Prove policy denial events contain no unauthorized case values.

- [ ] **Step 5: Run Catalyst smoke checks.**

Deploy the affected Function, then verify Gateway authentication, rank context
resolution, capability-filtered dispatch, masked output, denied alert access,
authorized alert access, scoped export, and audit persistence against Catalyst
Data Store. Record results in the production runbook.

- [ ] **Step 6: Commit verification evidence.**

~~~bash
git add docs/silent-match-production-runbook.md
git commit -m "docs: record RBAC rollout verification"
~~~

## Spec Coverage Self-Review

- Authority model and five rank buckets: Task 1.
- Immutable AccessContext: Task 1.
- Full capability vocabulary and matrix: Tasks 1 and 3.
- Default-deny dispatch and stable policy errors: Tasks 1-3.
- Multi-agent enforcement and EvidenceBundle filtering: Task 3.
- Existing SQL scope/masking compatibility: Task 2.
- Alert visibility/disposition separation and scan authorization: Task 4.
- Audit records and scope-safe exports: Task 5.
- PLAN.md and runbook integration: Task 6.
- Full rank-boundary, leakage, and Catalyst verification: Task 7.

The plan intentionally does not create a role or permissions table. No
unresolved feature is hidden behind an incomplete requirement, and all later task
interfaces use the names defined in Shared Interfaces.
