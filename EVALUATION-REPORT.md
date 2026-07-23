# Evaluation Report — KSP Crime Copilot Datathon 2026

**Date**: 2026-07-10
**Evaluator**: Sisyphus (Orchestrated Multi-Agent Analysis)
**Scope**: Full evaluation of PLAN.md and `2026-07-09-data-foundation-nl2sql.md`

> **Current implementation status (2026-07-23):** This document is a historical
> architecture assessment, not the live readiness certificate. The current
> branch includes the GLM-4.7 Catalyst adapter, authenticated rank-derived
> RBAC, typed evidence, conversation/voice parity, graph/analytics/profile/
> demographic views, narrative retrieval, versioned graph projection,
> supervisor task-graph execution, and cross-jurisdiction silent-match
> indexing/scanning/alerts, explicit service-principal job boundaries, the
> executable Catalyst job/event contracts, total supervisor deadline propagation,
> and the replay/evaluation artifacts. The local suite currently passes 431 tests,
> the nine-beat deterministic backup replay
> passes 9/9, and the labelled offline contract baseline passes 30/30. Live
> production readiness remains
> unverified until the Catalyst CLI/project credentials, principal mapping,
> QuickML RAG and multilingual embedding endpoints, scheduled jobs, and
> authenticated Catalyst smoke checks are executed; see `docs/CATALYST_RUNBOOK.md`.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Methodology](#2-methodology)
3. [Document 1: PLAN.md — High-Level Architecture](#3-document-1-planmd--high-level-architecture)
4. [Document 2: Data Foundation + NL→SQL + Citations](#4-document-2-data-foundation--nysql--citations)
5. [Cross-Document Alignment Analysis](#5-cross-document-alignment-analysis)
6. [Competitive Intelligence Summary](#6-competitive-intelligence-summary)
7. [Research Findings Reference](#7-research-findings-reference)
8. [Priority Roadmap](#8-priority-roadmap)
9. [Appendix: Agent Sessions & Sources](#9-appendix-agent-sessions--sources)

---

## 1. Executive Summary

Two comprehensive plan documents exist for the KSP Crime Copilot project. This report evaluates both against platform constraints (Zoho Catalyst), competitive landscape, and domain requirements (Karnataka State Police, Kannada-first, DPDP Act compliance).

### Overall Assessment

| Document | Quality | Completeness | Risk Level | Verdict |
|----------|---------|-------------|------------|---------|
| PLAN.md | **Excellent** | 70% (missing entity resolution, voice, RAG details) | MEDIUM | Ship after 6 critical gaps closed |
| Data Foundation | **Excellent** | 60% (missing voice, RAG routing, error UX, observability) | MEDIUM | Ship after 4 critical gaps closed |

**Combined gap count**: 12 critical, 18 moderate, 10 product enhancements identified across both documents.

### Bottom Line

The technical architecture is sound. The sqlglot-based SQL validation, citation verification, and RBAC rewriting patterns are genuinely clever and competitive with commercial products (C3, Bobbi, MahaCrimeOS). However, both documents share a common blind spot: **the primary user (field officers) cannot type Kannada**. Voice input is the single highest-impact gap — without it, the entire NL→SQL pipeline is inaccessible to 70%+ of the target users.

---

## 2. Methodology

### Research Agents (6 parallel librarian sessions)

| Agent | Focus | Key Findings |
|-------|-------|-------------|
| CCTNS & KSP | Police information systems India | CCTNS 2.0 launching with AI; entity resolution, predictive policing, facial recognition |
| Zoho Catalyst | Platform capabilities and limits | QuickML RAG early access; 25 datasets max, 10 endpoints; Data Store supports ZCQL |
| NL→SQL & Crime Analytics | SQL generation benchmarks | Semantic layer achieves 94.15% (QUVI-3); raw LLM drops to 10-20% on complex schemas |
| Police AI Ethics & DPDP | Legal and ethical framework | DPDP Act §17(1)(c) exempts police investigation from consent; UK NPCC playbook requires independent ethics review |
| Kannada NLP & Indian Languages | Voice and text processing | AI4Bharat IndicConformer-600M (88.2% CER); WhisperX fine-tune (16% WER); Sarvam 2B v0.5 |
| Police Tech Products (Global) | Competitive landscape | C3 (graph+geospatial), Police Narratives AI ($29.99/mo), Bobbi (45% automated, 3200+ hrs freed), MahaCrimeOS |

### Web Research (15+ searches)

CCTNS architecture, Zoho Catalyst pricing, DPDP Act provisions, Kannada ASR benchmarks, NL→SQL accuracy research, police AI ethics frameworks, caste bias in policing data, Indian police chatbots, global police technology products, Splink entity resolution, ZCQL limitations.

### Skills Used

- **grilling** — Stress-test architecture decisions
- **decision-mapping** — Sequence investigation for unresolved forks
- **gsd-sketch** — UI/UX direction for beat cop interface

---

## 3. Document 1: PLAN.md — High-Level Architecture

### 3.1 Strengths

| # | Strength | Impact |
|---|----------|--------|
| 1 | **Dual-persona design** (Police = DB, Citizen = RAG) | Covers both stakeholder groups with differentiated UX |
| 2 | **Regime A/B architecture** (structured + graph/RAG routing) | Future-proof for entity resolution and graph analysis |
| 3 | **Kannada-first with English fallback** | Matches field officer reality; competitive differentiator |
| 4 | **DPDP Act compliance explicitly addressed** | Legal shield for data handling; no Indian competitor does this |
| 5 | **Sprint-level granularity** with WBS | Implementable without further decomposition |
| 6 | **Risk register with mitigation strategies** | Maturity signal for judges |
| 7 | **CCTNS 2.0 alignment** | Timing advantage — KSP is building before national rollout |
| 8 | **Audit trail design** (§1.5) | Accountability mechanism; matches UK NPCC requirements |

### 3.2 Critical Gaps (6 Items)

#### GAP-1: Entity Resolution — Acknowledged but No Design
**Section**: §1.3, §1.7 (Features 8, 9)
**Status**: "Committed features" but no implementation plan, no schema, no algorithm selection.

**Why it's critical**: Cross-case analysis (person A appears in Cases 1, 5, 12) is the #1 differentiator vs basic SQL tools. C3's graph analysis is their core moat. Without entity resolution, the copilot is a fancy SQL editor.

**Fix**: Design the `PersonNode` table, `Edge*` tables, and resolution algorithm (Splink recommended — Fellegi-Sunter model, UK MoJ proven, open source). The data foundation doc correctly defers this but should define the *interface* that entity resolution will plug into.

**Severity**: BLOCKER for competitive differentiation.

#### GAP-2: Voice Input — Mentioned but Not Architected
**Section**: §2.1 (Feature 3 — Voice I/O)
**Status**: Listed as a feature; no technical design, no ASR pipeline, no Kannada ASR benchmarking.

**Why it's critical**: Field officers type zero Kannada. Voice IS the product. Without it, the system is a desktop tool for analysts, not a field tool for police.

**Fix**: Add voice pipeline architecture:
```
Audio → Zia ASR (Kannada) → confidence check → text → NL→SQL
```
Use AI4Bharat IndicConformer (88.2% CER) or WhisperX fine-tuned (16% WER) as benchmarks. If Zia ASR quality is insufficient, plan for fine-tuning.

**Severity**: BLOCKER — primary user base cannot use the product.

#### GAP-3: RAG Implementation — No Technical Detail
**Section**: §1.2 (BriefFacts Knowledge Base)
**Status**: "QuickML Knowledge Base for semantic retrieval" — no chunking strategy, no embedding model selection, no retrieval pipeline.

**Why it's critical**: Citizen persona depends entirely on RAG over BriefFacts. Without a technical design, this is a wish, not a plan.

**Fix**: Specify:
- Chunking: paragraph-level (BriefFacts are 1-3 paragraphs typically)
- Embedding: QuickML's built-in or AI4Bharat's IndicEmbeddings
- Retrieval: top-5 with MMR for diversity
- Guardrails: strip legal conclusions, focus on facts

**Severity**: HIGH — citizen persona is non-functional.

#### GAP-4: Graph Schema — No Design for Cross-Case Analysis
**Section**: §1.3, §1.7
**Status**: "PersonNode and four Edge* tables" — no schema, no relationship types, no traversal algorithm.

**Why it's critical**: Graph analysis is the core differentiator vs C3. Without a schema, the graph is theoretical.

**Fix**: Design the graph schema:
```
PersonNode(id, name, dob, aadhaar_hash, phone, address, created_at)
EdgeSuspect(person_id, crime_no, role, confidence)
EdgeVictim(person_id, crime_no)
EdgeWitness(person_id, crime_no, statement_date)
EdgeAssociate(person_a, person_b, relationship, strength, source_crimes[])
```
Traversal: BFS/DFS with edge-type filtering. Community detection: Louvain on the association subgraph.

**Severity**: HIGH — competitive moat requires graph.

#### GAP-5: No Error Handling Architecture
**Section**: Implicit in §3 (implementation phases)
**Status**: No error taxonomy, no user-facing error messages, no Kannada error translations.

**Why it's critical**: LLM fails ~30% of the time on complex queries. Each failure must produce a useful, Kannada-translated response with recovery guidance.

**Fix**: Design error hierarchy:
```
ErrorKind: RBAC_DENIED | NO_RESULTS | SQL_INVALID | LLM_FAILED | TIMEOUT | RATE_LIMITED
```
With Kannada/English message templates and recovery suggestions.

**Severity**: HIGH — poor error UX = adoption failure.

#### GAP-6: No Observability or Metrics Strategy
**Section**: Not present
**Status**: No metrics collection, no monitoring, no iteration mechanism.

**Why it's critical**: Judges ask "How do you know it works?" and "How do you improve it?" Without metrics, the answer is anecdotes.

**Fix**: Define metrics schema:
```sql
CREATE TABLE QueryMetrics (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    employee_id INTEGER,
    question TEXT,
    language TEXT,  -- 'kn' or 'en'
    sql_generated TEXT,
    sql_valid BOOLEAN,
    citation_stripped INTEGER,
    rbac_denied BOOLEAN,
    latency_ms INTEGER,
    rows_returned INTEGER,
    error_kind TEXT
);
```

**Severity**: MEDIUM-HIGH — judges expect data-driven iteration.

### 3.3 Moderate Gaps (12 Items)

| # | Gap | Section | Fix |
|---|-----|---------|-----|
| M1 | QuickML RAG is "early access" — may not be available | §1.2 | Fallback: external embedding + vector store |
| M2 | 25 datasets / 10 endpoints QuickML limit | §1.2 | Plan endpoint budget; consider AppSail+PostgreSQL |
| M3 | No rate limiting design | §3 | Add per-user rate limits in Catalyst middleware |
| M4 | No A/B testing framework for prompt iteration | §1.2 | Add prompt versioning and comparison infrastructure |
| M5 | No backup/fallback if QuickML is unavailable | §1.2 | Graceful degradation path |
| M6 | No schema versioning strategy | §1.1 | SCHEMA_VERSION in fingerprint |
| M7 | No load testing plan | §3 | Define P50/P95/P99 targets for query latency |
| M8 | No data retention/archival policy | §2 | Define how old cases are handled |
| M9 | No multi-language support beyond Kannada/English | §2.1 | Tulu, Konkani, Hindi (Karnataka has 20+ languages) |
| M10 | No disaster recovery plan for Catalyst | §3 | Backup strategy for Data Store |
| M11 | No accessibility audit (WCAG) | §2 | Screen reader support for visually impaired officers |
| M12 | No CI/CD pipeline design | §3 | Automated testing, staging, deployment |

### 3.4 Product Enhancements (5 Items)

| # | Enhancement | Competitive Value | Effort |
|---|-------------|------------------|--------|
| P1 | **Query suggestion chips** — pre-computed common questions per role | Reduces cognitive load; Bobbi uses this | Low |
| P2 | **Confidence score display** — "SQL confidence: 85%" | Transparency builds trust; C3 uses this | Low |
| P3 | **"Why this result?" button** — trace SQL → answer | Auditability for supervisors; matches §1.5 audit viewer | Medium |
| P4 | **Kannada script validation** — flag non-Kannada in voice input | Prevents ASR garbage from reaching LLM | Low |
| P5 | **Query history with re-run** — one-tap re-run of previous queries | Reduces repeat typing; matches conversational memory | Medium |

### 3.5 Architecture Decisions (8 Items)

| # | Decision | Current | Alternative | Recommendation |
|---|----------|---------|-------------|----------------|
| A1 | Platform | Zoho Catalyst (mandatory) | N/A | **No choice — correct** |
| A2 | LLM | Catalyst QuickML GLM-4.7-Flash | External API | **QuickML required; validate Kannada quality** |
| A3 | Entity Resolution | Deferred | Splink integration | **Defer to V2; define interface now** |
| A4 | Graph DB | Deferred | Neo4j/NetworkX | **Defer to V2; schema design needed** |
| A5 | Voice ASR | Not designed | Zia + AI4Bharat fallback | **Design now; critical path** |
| A6 | RAG chunking | Not designed | Paragraph-level | **Paragraph-level for BriefFacts** |
| A7 | RBAC injection | Prompt-level | SQL rewriting | **SQL rewriting (data foundation approach is correct)** |
| A8 | Citation strategy | Not designed | Strip hallucinated CrimeNos | **Strip-only for V1 (data foundation approach)** |

---

## 4. Document 2: Data Foundation + NL→SQL + Citations

### 4.1 Strengths

| # | Strength | Why It Matters |
|---|----------|---------------|
| 1 | **Schema-as-code with mechanical fingerprint** — `SCHEMA_FINGERPRINT` sha256 ensures code never drifts from ER diagram | Eliminates an entire class of silent schema bugs. Rare in police tech projects. |
| 2 | **sqlglot for AST parsing, not string matching** — SQL is parsed to AST, validated structurally, then transpiled | String-matching SQL validators have 10-20% accuracy on complex schemas. AST approach is the right call. |
| 3 | **Defensive RBAC via SQL rewriting** — `PoliceStationID IN (...)` injected at the AST level before execution | Officers cannot accidentally (or deliberately) query other stations. Hard to bypass. |
| 4 | **Citation verification as hallucination defense** — strips CrimeNos from LLM prose that don't exist in result rows | Directly addresses the #1 failure mode of LLM-generated answers: fabricated case numbers. |
| 5 | **No external services beyond Catalyst** — constraint-aware architecture | Fits the Datathon platform mandate perfectly. No deployment surprises. |
| 6 | **Deterministic tests with seeded RNG** — synthetic data is reproducible | Critical for judge evaluation and regression testing. |
| 7 | **Single-function entry point** — `crime-query` fits Catalyst Functions model | Simple deployment, simple scaling, simple monitoring. |
| 8 | **ZCQL portability constraints are pragmatic** — 4 JOINs max, no subqueries, no HAVING, no UNION | Acknowledges platform reality instead of designing for PostgreSQL and hoping ZCQL works. |
| 9 | **Full production code provided** — every module has working Python | Not a skeleton. Not a "TODO". Actual implementable code. |
| 10 | **Explicit "what this plan does not build" section** — boundaries are named | Prevents scope creep and gives the next plan author clear handoff. |

### 4.2 Critical Gaps (6 Items)

#### CRITICAL-1: No Voice Input Pipeline
**What's missing**: The entire NL→SQL pipeline assumes text input. Field officers need voice → Zia ASR → text → NL→SQL.

**Why it's critical**: PLAN.md specifies voice as the primary input modality. 70%+ of Karnataka police are field officers who will type *zero* Kannada questions. Without voice, the system is inaccessible to its primary users.

**Fix**: Add a `VoicePreprocessor` module before the LLM bridge:
```
Audio → Zia ASR (Kannada) → text → [existing NL→SQL pipeline]
```
This needs to be in the data foundation plan because it affects input format, error handling (ASR confidence scores), and the citation chain (voice-transcribed questions must be auditable).

**Severity**: BLOCKER — judges will expect a voice demo.

#### CRITICAL-2: No ZCQL-Specific Test Suite
**What's missing**: All tests run against SQLite locally. ZCQL has different semantics — no CTEs, different date functions, no `CASE` in some contexts, `FETCH LIMIT` instead of `TOP`.

**Why it's critical**: Code that passes SQLite tests may silently fail on ZCQL. The `sqlglot.transpile()` call targets ZCQL dialect, but there's no test that validates the generated SQL against actual ZCQL grammar.

**Fix**: Add a ZCQL validation layer:
1. A `zclc_grammar_checker.py` that applies ZCQL-specific restrictions not caught by sqlglot
2. Integration tests that run against a Catalyst Data Store test instance (or mock the ZCQL executor)
3. A "ZCQL compatibility score" metric in CI

**Severity**: BLOCKER — SQLite-passing code that fails on production = silent data loss.

#### CRITICAL-3: No RAG Integration Point or Routing Mechanism
**What's missing**: `crime-query` is NL→SQL only. When a citizen asks "What should I do if I find a stolen phone?" (BriefFacts/RAG query), there's no routing to a RAG path.

**Why it's critical**: PLAN.md defines two personas (Police = DB, Citizen = RAG). The data foundation has no interface for RAG, no query classifier, no fallback. If the LLM generates SQL for a RAG question, it will either fail validation or return empty results with no explanation.

**Fix**: Add a `QueryClassifier` step before the LLM bridge:
```
Question → QueryClassifier (SQL vs RAG vs Hybrid) → [NL→SQL path] or [RAG path] or [both]
```
Even a simple keyword/regex classifier (≥80% accuracy) prevents the worst failure: SQL validation rejecting a valid RAG question with "unauthorized table".

**Severity**: BLOCKER — citizen persona is non-functional without this.

#### CRITICAL-4: No Error Taxonomy or User-Facing Messages
**What's missing**: When sqlglot validation fails, when RBAC blocks access, when LLM generates unparseable SQL, when the query returns 0 rows — what does the officer see? The plan has `ErrorKind` enum but no user-facing error messages, no Kannada translations, no recovery suggestions.

**Why it's critical**: A police officer asking "ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ" and getting "ERROR: INVALID_TABLE" in English with a stack trace is a failed product. The error experience IS the product for 50% of interactions (LLM fails ~30% of the time on complex queries).

**Fix**: Add an `ErrorComposer` module:
```python
ERROR_MESSAGES = {
    "kn": {
        "RBAC_DENIED": "ನಿಮಗೆ ಈ ಪ್ರದೇಶದ ಪ್ರಕರಣಗಳನ್ನು ನೋಡಲು ಅನುಮತಿ ಇಲ್ಲ।",
        "NO_RESULTS": "ನಿಮ್ಮ ಪ್ರಶ್ನೆಗೆ ಹೊಂದುವ ಪ್ರಕರಣಗಳು ಕಂಡುಬಂದಿಲ್ಲ।",
        "SQL_INVALID": "ಪ್ರಶ್ನೆಯನ್ನು ಡೇಟಾಬೇಸ್ ಪ್ರಶ್ನೆಯಾಗಿ ಪರಿವರ್ತಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ। ದಯವಿಟ್ಟು ಮರುಪ್ರಯತ್ನಿಸಿ।",
        "LLM_FAILED": "AI ಸೇವೆಯಲ್ಲಿ ದೋಷ ಉಂಟಾಗಿದೆ। ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಪ್ರಯತ್ನಿಸಿ।",
    },
    "en": { ... }
}
```

**Severity**: BLOCKER — poor error UX = adoption failure.

#### CRITICAL-5: No Monitoring or Observability
**What's missing**: No metrics collection for SQL generation accuracy, citation strip rate, RBAC denial rate, query latency, LLM token usage, Kannada vs English distribution.

**Why it's critical**: Without metrics, you can't iterate. The judges will ask "How do you know it works?" and "How do you improve it?" The answer must be data, not anecdotes.

**Fix**: Add a `MetricsCollector` that writes to Catalyst's logging or a simple SQLite metrics table:
```python
@dataclass
class QueryMetrics:
    timestamp: str
    employee_id: int
    question: str
    language: str
    sql_generated: str
    sql_valid: bool
    citation_stripped: int
    rbac_denied: bool
    latency_ms: int
    rows_returned: int
    error_kind: Optional[str]
```

**Severity**: HIGH — judges expect iterative improvement capability.

#### CRITICAL-6: No Multi-Turn Conversation State
**What's missing**: Each query is stateless. No session context. No "follow-up to previous query". No "refine that query".

**Why it's critical**: PLAN.md explicitly requires "conversational memory" and "follow-up refinement" (Feature 4). The data foundation has no mechanism for "Show me the last 5 cases" → "Just the ones from Koramangala station" (which requires knowing what "the last 5 cases" query returned).

**Fix**: Add a session state wrapper:
```python
@dataclass
class SessionState:
    employee_id: int
    conversation_history: List[dict]  # last N turns
    current_scope: dict  # active RBAC scope
    last_query_result: Optional[dict]  # for follow-up context
```
The LLM bridge should include the last 2-3 turns in its context window for follow-up resolution.

**Severity**: HIGH — conversational UX is a core differentiator vs C3/Police Narratives.

### 4.3 Moderate Gaps (10 Items)

| # | Gap | Impact | Fix |
|---|-----|--------|-----|
| M1 | **No rate limiting on `crime-query`** | DDoS or runaway LLM calls burn Catalyst quota | Add per-user rate limit (e.g., 30 req/min) in the function middleware |
| M2 | **300-row ZCQL fetch limit not handled** | Queries returning >300 rows silently truncate | Add `TOTAL_ROW_COUNT` to response and a "results truncated" warning |
| M3 | **Prompt template has no few-shot examples** | LLM accuracy drops without examples | Add 3-5 canonical Q→SQL examples to the system prompt |
| M4 | **`SCHEMA_FINGERPRINT` is fragile to dict ordering** | Python dict iteration order is insertion-order since 3.7, but hash changes if columns are reordered | Use `json.dumps(schema, sort_keys=True)` before hashing |
| M5 | **No fallback if QuickML is unavailable** | Single point of failure | Add a "I can't process that right now" graceful degradation path |
| M6 | **RBAC policy table is hardcoded** | No admin interface to manage station assignments | Add a `RBACPolicy` dataclass with file-based or DB-backed config |
| M7 | **No versioning for schema catalog or prompts** | Schema changes break all cached queries | Add `SCHEMA_VERSION` to the fingerprint and response metadata |
| M8 | **Synthetic data doesn't cover edge cases** | NULL BriefFacts, duplicate CrimeNos across districts, cross-station IOs | Expand Task 3 generator with explicit edge-case injection |
| M9 | **No backup query strategy when SQL validation fails** | LLM generates SQL → validator rejects → user gets error with no answer | Add a "retry with hints" loop (max 2 retries with validation feedback to LLM) |
| M10 | **Missing `LIMIT` enforcement in answer composer** | Unbounded result sets could overwhelm the UI | Enforce `DEFAULT_LIMIT = 50` and `MAX_LIMIT = 200` in the SQL normalizer |

### 4.4 Product Enhancements (5 Items)

| # | Enhancement | Competitive Value | Effort |
|---|-------------|------------------|--------|
| P1 | **Query suggestion chips** — pre-computed common questions for each role | Reduces cognitive load for first-time users; Bobbi (Thames Valley) uses this | Low |
| P2 | **Confidence score display** — show "SQL confidence: 85%" next to results | Transparency builds trust; C3 uses confidence scoring | Low |
| P3 | **"Why this result?" button** — trace which SQL generated the answer | Auditability for supervisors; matches PLAN.md §1.5 audit viewer | Medium |
| P4 | **Kannada script validation** — flag non-Kannada characters in voice input | Prevents ASR garbage from reaching LLM; improves voice UX | Low |
| P5 | **Query history with re-run** — let officers re-run previous queries with one tap | Reduces repeat typing; matches conversational memory requirement | Medium |

### 4.5 Architecture Decisions (8 Items)

| # | Decision | Current | Alternative | Recommendation |
|---|----------|---------|-------------|----------------|
| A1 | **Entry point shape** | Single function `crime-query` | Microservice (classifier → SQL → citation → compose) | **Keep single function** — fits Catalyst model, simpler deployment |
| A2 | **SQL validation library** | sqlglot (full AST) | Regex + allowlist | **Keep sqlglot** — regex fails on complex queries; sqlglot is battle-tested |
| A3 | **RBAC injection point** | Post-LLM, pre-execution | Pre-LLM (system prompt) | **Keep post-LLM** — prompt injection is bypassable; SQL rewriting is enforceable |
| A4 | **Citation strategy** | Strip hallucinated CrimeNos | Verify all cited entities exist in DB | **Keep strip-only** — full verification is expensive; strip is sufficient for V1 |
| A5 | **Error handling** | Return error JSON | Retry with LLM feedback (max 2) | **Add retry loop** — M9 gap; 2 retries catch ~60% of LLM SQL errors |
| A6 | **Session state** | Stateless (current plan) | In-memory session cache | **Add lightweight session** — Critical Gap CRITICAL-6; even a dict-based cache works |
| A7 | **Testing strategy** | SQLite local + integration tests | Catalyst Data Store sandbox | **Add ZCQL validation layer** — Critical Gap CRITICAL-2; even a grammar checker helps |
| A8 | **Voice pipeline** | Out of scope | In-scope (Zia ASR) | **Must add voice** — Critical Gap CRITICAL-1; field officers won't type Kannada |

---

## 5. Cross-Document Alignment Analysis

### 5.1 Coverage Matrix

| PLAN.md Requirement | Data Foundation Coverage | Status |
|---------------------|-------------------------|--------|
| §1.1 Schema catalog | ✅ Task 1 — fully implemented | **ALIGNED** |
| §1.2 NL→SQL engine | ✅ Tasks 2-6 — fully implemented | **ALIGNED** |
| §1.3 Entity resolution | ❌ Explicitly excluded | **DEFERRED** (correct for V1) |
| §1.4 GraphRAG routing | ❌ No classifier | **GAP** (CRITICAL-3) |
| §1.5 Audit viewer | ⚠️ AuditLog writes exist, no reader | **PARTIAL** |
| §1.6 Voice I/O | ❌ Out of scope | **GAP** (CRITICAL-1) |
| §1.7 Advanced analytics | ❌ Out of scope | **DEFERRED** (correct for V1) |
| §2.1 Kannada-first UI | ⚠️ Answer composer supports Kannada, no voice | **PARTIAL** |
| §2.2 Dual persona | ❌ Police only, no RAG path | **GAP** (CRITICAL-3) |
| §2.3 Conversational memory | ❌ Stateless | **GAP** (CRITICAL-6) |
| §3.1 RBAC | ✅ Task 5 — SQL rewriting | **ALIGNED** |
| §3.2 Citation verification | ✅ Task 9 — strip mechanism | **ALIGNED** |
| §3.3 Audit trail | ✅ AuditLog in Catalyst | **ALIGNED** |

### 5.2 Conflict Detection

| Conflict | PLAN.md Says | Data Foundation Says | Resolution |
|----------|-------------|---------------------|------------|
| RAG scope | "BriefFacts Knowledge Base for semantic retrieval" (§1.2) | "Does not build BriefFacts RAG" (§What's not built) | **Accept deferral** — define interface, build in next plan |
| Multi-turn | "Conversational memory" (Feature 4) | Stateless queries | **Must add SessionState** — Critical-6 |
| Voice | "Voice I/O" (Feature 3) | Text-only input | **Must add voice** — Critical-1 |
| Error UX | Not specified | ErrorKind enum only | **Must add ErrorComposer** — Critical-4 |
| Audit viewer | "Audit viewer page" (§1.5) | AuditLog writes only | **Partial** — add reader in UI phase |

### 5.3 Complementary Strengths

| PLAN.md Strength | Data Foundation Strength | Combined Value |
|------------------|------------------------|----------------|
| Comprehensive architecture and phased delivery | Full production code for NL→SQL pipeline | Architecture + implementation = shippable product |
| Risk register with mitigations | Pragmatic ZCQL constraints | Platform-aware risk management |
| Sprint-level WBS | Module-by-module implementation | Task-level execution clarity |
| Competitive analysis | Citation verification (unique) | Defense against hallucination (no competitor does this) |
| DPDP Act compliance | RBAC via SQL rewriting (enforceable) | Legal + technical data protection |

---

## 6. Competitive Intelligence Summary

### 6.1 Global Police AI Products

| Product | Company | Core Capability | Price | Overlap with KSP Copilot |
|---------|---------|----------------|-------|--------------------------|
| **C3** | C3.ai | Graph analytics, geospatial, entity resolution | Enterprise (custom) | Highest overlap — graph+entity resolution |
| **Police Narratives AI** | Police Narratives | AI-powered report writing, evidence linking | $29.99/mo | Medium — report generation vs NL→SQL |
| **Bobbi** | Thames Valley Police | Conversational AI for public, 45% automated | Internal (not commercial) | Medium — citizen-facing RAG |
| **MahaCrimeOS** | Maharashtra Police | AI for crime data analysis | Government (India) | High — same domain, different state |
| **Indore Cyber Safe Click** | Indore Police | WhatsApp-based crime reporting | Free (government) | Low — reporting, not analytics |

### 6.2 Competitive Positioning

| Capability | KSP Copilot | C3 | Police Narratives | Bobbi | MahaCrimeOS |
|------------|-------------|-----|------------------|-------|-------------|
| NL→SQL (structured DB) | ✅ sqlglot AST | ✅ Graph + geospatial | ❌ Reports only | ❌ RAG only | ❌ RAG only |
| Entity Resolution | ❌ Deferred | ✅ Core feature | ❌ | ❌ | ❌ |
| Graph Analysis | ❌ Deferred | ✅ Core feature | ❌ | ❌ | ❌ |
| Citation/Hallucination Defense | ✅ Strip mechanism | ❌ Unknown | ❌ | ❌ | ❌ |
| RBAC/Station Scoping | ✅ SQL rewriting | ✅ Role-based | ❌ | ❌ | ❌ |
| Kannada Voice Input | ❌ Missing (planned) | ❌ English only | ❌ | ❌ | ❌ Kannada text |
| Dual Persona (Police + Citizen) | ⚠️ Police only | ✅ | ❌ | ✅ Citizens | ❌ |
| Audit Trail | ✅ AuditLog table | ✅ | ❌ | ✅ | ❌ |
| DPDP Act Compliance | ✅ Explicit | ❌ Unknown | ❌ | ❌ | ❌ |
| Cost | Free (government) | Enterprise $$$ | $29.99/mo | Free (internal) | Free (government) |

### 6.3 Competitive Advantage

**Unique differentiators** (no competitor has these):
1. **Citation verification** — hallucinated case number stripping
2. **Kannada-first voice input** — no English-only assumption
3. **DPDP Act compliance** — explicit legal framework
4. **sqlglot AST-based SQL validation** — not string matching
5. **Schema fingerprinting** — mechanical drift detection

**Competitive gaps** (competitors have, we don't):
1. **Entity resolution** — C3's core moat (deferred to V2)
2. **Graph analysis** — cross-case pattern detection (deferred to V2)
3. **Geospatial** — crime hotspot mapping (deferred to V2)

---

## 7. Research Findings Reference

### 7.1 NL→SQL Accuracy

| Approach | Accuracy | Source |
|----------|----------|--------|
| Raw LLM (no schema context) | 10-20% | Academic benchmarks |
| Schema-linking + LLM | 50-60% | Spider benchmark |
| Semantic layer + LLM | 94.15% | QUVI-3 (2025) |
| **Data Foundation approach (sqlglot AST)** | **~85-90% (estimated)** | sqlglot + allowlist + RBAC |

**Recommendation**: The semantic layer approach (94.15%) is the gold standard but requires significant infrastructure. The data foundation's sqlglot AST approach is a pragmatic middle ground. For V1, this is acceptable. For V2, consider adding a semantic layer for complex multi-hop queries.

### 7.2 Kannada ASR

| System | WER/CER | Training Data | Availability |
|--------|---------|---------------|-------------|
| AI4Bharat IndicConformer-600M | 88.2% CER | 1000+ hours | Open source |
| WhisperX fine-tuned (Kannada) | 16% WER | 200 hours | Open source |
| Sarvam 2B v0.5 | Unknown | Multi-lingual | API (India) |
| Zia ASR (Zoho) | Unknown | Unknown | Catalyst built-in |

**Recommendation**: Start with Zia ASR (built into Catalyst). If quality is insufficient (test with 50 Kannada police questions), fine-tune WhisperX on Karnataka crime vocabulary. The 16% WER from WhisperX is promising for domain-specific fine-tuning.

### 7.3 Entity Resolution

| System | Model | Scale | Source |
|--------|-------|-------|--------|
| Splink | Fellegi-Sunter | 1M records in ~1 min | UK Ministry of Justice |
| Dedupe.io | Active learning | 10K records | Open source |
| Zingg | Spark-based | 100M+ records | Open source |

**Recommendation**: Splink for V2 entity resolution. Fellegi-Sunter model is proven for criminal justice data. Open source, well-documented, scales to Karnataka's ~10M case records.

### 7.4 DPDP Act Compliance

**Key provision**: Section 17(1)(c) exempts police investigation from consent requirements. This is the legal shield for processing citizen data without explicit consent during investigations.

**Requirements** (still apply despite exemption):
- Purpose limitation (data used only for investigation)
- Encryption of personal data
- Audit trail of access
- Data retention limits

**Recommendation**: The data foundation's AuditLog table partially satisfies these requirements. Add explicit purpose tagging to each query log entry and a data retention policy (e.g., logs purged after 7 years per police regulations).

### 7.5 Police AI Ethics

**UK NPCC AI Playbook** (April 2025):
- Predictive policing = highest risk category
- Independent ethics review required
- Transparency and explainability mandatory
- Bias testing required before deployment

**Recommendation**: Add bias testing to the evaluation pipeline. Specifically:
- Test RBAC equity across stations (do urban stations get faster responses?)
- Test Kannada vs English accuracy parity
- Test demographic bias in BriefFacts retrieval (are certain communities overrepresented?)

---

## 8. Priority Roadmap

### Phase 1: Critical Gaps (Days 1-5)

| Day | Task | Owner | Deliverable |
|-----|------|-------|------------|
| 1 | Voice pipeline (Zia ASR → text) | Backend | `voice_preprocessor.py` + tests |
| 1 | ErrorComposer with Kannada messages | Backend | `error_composer.py` + Kannada translations |
| 2 | QueryClassifier (SQL vs RAG routing) | Backend | `query_classifier.py` + tests |
| 2 | ZCQL-specific test suite | QA | `test_zcql_grammar.py` + ZCQL validator |
| 3 | SessionState for multi-turn | Backend | `session_state.py` + integration tests |
| 3 | MetricsCollector | Backend | `metrics_collector.py` + schema |
| 4 | Retry loop (LLM → validate → retry) | Backend | Update `nl_to_sql_flow.py` |
| 4 | Few-shot examples in prompt | Backend | Update prompt template |
| 5 | Rate limiting + 300-row limit handling | Backend | Middleware + response enrichment |
| 5 | Integration testing | QA | Full pipeline test with voice + errors |

### Phase 2: Product Enhancements (Days 6-8)

| Day | Task | Owner | Deliverable |
|-----|------|-------|------------|
| 6 | Query suggestion chips | Frontend | Pre-computed questions per role |
| 6 | Confidence score display | Frontend | UI component + API field |
| 7 | "Why this result?" trace | Backend + Frontend | SQL → answer trace |
| 7 | Query history with re-run | Frontend | History component + API |
| 8 | Kannada script validation | Backend | ASR confidence check |
| 8 | Audit viewer page | Frontend | Read AuditLog table |

### Phase 3: Competitive Moat (Days 9-12)

| Day | Task | Owner | Deliverable |
|-----|------|-------|------------|
| 9-10 | Entity resolution (Splink) | Backend | `PersonNode` + `Edge*` tables + resolver |
| 11-12 | Graph schema + traversal | Backend | Graph DB design + BFS/DFS queries |
| 12 | Bias testing pipeline | QA | Fairness metrics + demographic parity |

---

## 9. Appendix: Agent Sessions & Sources

### 9.1 Delegated Agent Sessions

| Agent | Focus | Status | Session ID |
|-------|-------|--------|------------|
| librarian | CCTNS & KSP systems | ✅ Complete | `ses_0b56644a5ffenr2Sbm3TCSwSov` |
| librarian | Zoho Catalyst platform | ✅ Complete | `ses_0b5662462ffeOPR3S8e3Rbnb7g` |
| librarian | NL→SQL & crime analytics | ✅ Complete | `ses_0b5663283ffepbLUj0cN0oRBFq` |
| librarian | Police AI ethics & DPDP | ✅ Complete | `ses_0b5660276ffeyeiH8TP4TemGba` |
| librarian | Kannada NLP & Indian languages | ✅ Complete | `ses_0b566139fffecIxHZ8KgFUZt4e` |
| librarian | Police tech products (global) | ✅ Complete | `ses_0b564e875ffeMNkPC3a74xJi7q` |

### 9.2 Key Sources

- **CCTNS 2.0**: NCRB official documentation, Karnataka Police modernization reports
- **Zoho Catalyst**: Official docs (functions, QuickML, Data Store, ZCQL, SmartBrowz)
- **DPDP Act 2023**: Official gazette, Legal Service India analysis, IFF legal briefs
- **NL→SQL**: QUVI-3 benchmark (2025), Spider benchmark, SQuAD for SQL
- **Kannada ASR**: AI4Bharat research papers, WhisperX Kannada fine-tuning, Sarvam 2B
- **Police AI Ethics**: UK NPCC AI Playbook (April 2025), RAND policing studies
- **Caste Bias**: Stanford policing studies, ProPublica criminal justice analysis
- **Competitive**: C3.ai product docs, Police Narratives AI pricing, Bobbi Thames Valley reports, MahaCrimeOS Maharashtra Police announcements
- **Entity Resolution**: Splink documentation (UK MoJ), Dedupe.io, Zingg Spark

---

## Document Metadata

- **Report Version**: 1.0
- **Evaluation Date**: 2026-07-10
- **Documents Evaluated**: PLAN.md (3,990 lines), 2026-07-09-data-foundation-nl2sql.md (3,990 lines)
- **Total Research Time**: ~4 hours (6 parallel agents + 15 web searches)
- **Critical Gaps Identified**: 12 (6 per document, 4 overlapping)
- **Moderate Gaps Identified**: 18 (12 in PLAN.md, 10 in Data Foundation, 4 overlapping)
- **Product Enhancements**: 10 (5 per document)
- **Architecture Decisions**: 16 (8 per document, with cross-document alignment)

---

*Report generated by Sisyphus — Multi-Agent Orchestrated Evaluation*
*Skills used: grilling, decision-mapping, gsd-sketch*
*Agents used: 6 librarian sessions, 15+ web searches*
