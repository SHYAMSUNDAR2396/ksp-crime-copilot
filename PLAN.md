# Execution Plan — KSP Datathon 2026, Challenge 01

**Conversational AI for the Karnataka State Police Crime Database**
Platform: Zoho Catalyst (mandated) · Data: schema provided ([Police_FIR_ER_Diagram.md](Police_FIR_ER_Diagram.md)), rows synthetic

Companion strategy document: [Technical Report](KSP-Datathon2026-Conversational-AI-Technical-Report.html). This plan supersedes the report's §04–§08 architecture wherever the real schema contradicts it.

Current production implementation plan: [Cross-Lingual MO Matching + Silent-Match Alerts](docs/superpowers/plans/2026-07-21-cross-lingual-silent-match-alerts.md). Related designs: [cross-lingual semantic MO matching](docs/superpowers/specs/2026-07-21-cross-lingual-semantic-mo-matching-design.md) and [cross-jurisdiction silent-match alerts](docs/superpowers/specs/2026-07-18-cross-jurisdiction-silent-match-alerts-design.md).

---

## 1. Revised architecture (schema-grounded)

The provided schema is a fully relational CCTNS-style model: 23 tables centred on `CaseMaster`, with the **only free text in `CaseMaster.BriefFacts`** and geo as `latitude`/`longitude`. There are **no phone, vehicle, address, or bank-account entities, and no cross-case person IDs**. Four consequences drive everything below:

1. **NL→SQL is the primary engine.** "Burglaries in Bengaluru East in the last 6 months" is a structured query, not a RAG question.
2. **Document RAG shrinks to `BriefFacts`** — semantic "find similar cases" over case narratives.
3. **The graph must be *derived*.** With no person master table, hidden links come from entity resolution on names, shared IOs, shared act-sections, and geo proximity.
4. **Execution is supervisor-led and multi-agent.** A supervisor decomposes each request or proactive event into typed capability tasks, fans out independent specialists in parallel, merges their evidence, and sends only verified claims to composition.

### 1.0 Architecture & data flow (Catalyst service map)

**Component architecture** — every box is a Zoho Catalyst service; nothing runs off-platform except the browser-side Web Speech API.

```mermaid
flowchart TB
  subgraph EXP["EXPERIENCE — Web Client Hosting"]
    UI["Chat UI · citation panel · graph view · hotspot map · role badge"]
    VOICE["Voice I/O<br/>(browser Web Speech API)"]
    AUTHN["Authentication<br/>login · role from Rank/Unit"]
  end

  subgraph EDGE["EDGE — API Gateway"]
    GW["authZ · throttle · audit hook"]
  end

  subgraph LOGIC["AGENTIC CONTROL PLANE — Supervisor + Specialist Functions"]
    SUP["Supervisor Agent<br/>task graph · fan-out · deadlines"]
    CTX["Typed TaskContext<br/>shared EvidenceBundles"]
    FQ["Structured Query Agent<br/>NL→SQL · validate"]
    FR["Narrative Retrieval Agent<br/>RAG · cross-lingual MO"]
    FG["Graph Agent<br/>traversal · community · centrality"]
    FA["Analytics Agent<br/>trend · forecast · hotspot"]
    FS["Silent-Match Agent<br/>score · deduplicate · route"]
    FV["Verification + Citation Agent"]
    FC["Composition Agent"]
    FT["Translation Agent"]
    FP["Profile + Prevention Agent"]
    FL["Legal Deadline Agent<br/>(future capability)"]
  end

  subgraph AI["INTELLIGENCE — QuickML + Zia + SmartBrowz"]
    LLM["QuickML LLM Serving<br/>Qwen 2.5-14B"]
    RAG["QuickML RAG + Knowledge Base<br/>BriefFacts index"]
    PIPE["QuickML Pipelines<br/>DBSCAN · time-series · anomaly"]
    ZIA["Zia<br/>OCR · language · voice fallback"]
    PDF["SmartBrowz<br/>conversation → PDF"]
  end

  subgraph DATA["DATA"]
    DS[("Data Store<br/>23 tables + edge tables + audit log")]
    CA[("Cache<br/>session context")]
    ST[("Stratus<br/>PDF / blob store")]
  end

  CRON["Cron / Job Scheduling<br/>edge rebuild · MO index · alerts · forecasts"]
  EVENT["Post-ingestion event<br/>completed FIR"]

  VOICE --> UI
  UI --> AUTHN --> GW --> SUP
  EVENT --> SUP
  SUP --> CTX
  CTX -. parallel evidence tasks .-> FQ & FR & FG & FA & FS & FP & FL
  FQ & FR & FG & FA & FS & FP & FL --> CTX
  CTX --> FV --> FC --> FT --> UI
  FQ --> DS
  FR --> RAG
  FR --> DS
  FG --> DS
  FA --> PIPE
  FA --> DS
  FS --> DS
  FT --> ZIA
  FC --> LLM
  FP --> LLM
  FQ --> LLM
  FV --> LLM
  RAG --> DS
  FP --> PDF --> ST
  SUP --> CA
  GW -. audit .-> DS
  CRON --> SUP
```

**Request data flow** — one question, end to end, with the service handling each step.

```mermaid
flowchart LR
  IN["Utterance<br/>voice / text · KN or EN"] --> STT["Speech→text<br/>Web Speech / Zia"]
  STT --> AUTHZ["API Gateway<br/>authenticate + role scope"]
  AUTHZ --> LANG["Detect + pivot to English<br/>(Translation Agent · Zia)"]
  LANG --> CTX{"Follow-up?"}
  CTX -- yes --> MEM[("Cache<br/>prior filters")]
  CTX -- no --> SUP["Supervisor Agent<br/>classify task + build fan-out"]
  MEM --> SUP
  SUP --> TASKS["Typed TaskContext<br/>caller scope · deadline · citation policy"]
  TASKS -. relevant agents in parallel .-> SQLQ["Structured Query Agent<br/>NL→SQL + validate"]
  TASKS -. relevant agents in parallel .-> RET["Narrative Retrieval Agent<br/>QuickML RAG + MO Matcher"]
  TASKS -. relevant agents in parallel .-> GRP["Graph Agent<br/>edge traversal"]
  TASKS -. relevant agents in parallel .-> ANL["Analytics Agent<br/>DBSCAN · forecast"]
  SQLQ & RET & GRP & ANL --> ENV["EvidenceBundles<br/>claims · citations · confidence · limits"]
  ENV --> VER["Verification + Citation Agent<br/>merge · conflict check · RBAC"]
  VER --> COMP["Composition Agent<br/>Qwen 2.5-14B"]
  COMP --> BACK["Translation Agent<br/>IDs/names verbatim"]
  BACK --> OUT["Answer + citations<br/>(+ voice, + PDF on request)"]
  AUTHZ -. every request .-> AUD[("Audit log<br/>Data Store")]
  VER -. result set .-> AUD
```

**Service inventory (what each is for):**

| Catalyst service | Role in this build |
|---|---|
| Web Client Hosting | Chat UI, graph/map views, PDF download |
| Authentication | Login; role derived from `Rank.Hierarchy` + `Employee.UnitID`/`DistrictID` |
| API Gateway | Zero-trust authZ, throttling, audit hook on every call |
| Circuits / Functions | Supervisor, typed task context, specialist agents, retries, and evidence verification |
| QuickML LLM Serving | Qwen 2.5-14B — SQL generation, answer composition, profiling |
| QuickML RAG + Knowledge Base | Semantic search over `BriefFacts` with citation breakdown |
| QuickML Pipelines | DBSCAN hotspots, time-series forecast, anomaly early-warning |
| Zia | Language detect/normalise, OCR for legacy scans, voice STT fallback |
| SmartBrowz | Conversation history → PDF |
| Data Store | 23 schema tables + derived edge tables + MO index + silent-match alerts + append-only audit log |
| Cache | Per-session conversation context for follow-ups |
| Stratus | Blob/PDF storage |
| Cron / Job Scheduling | Edge-table rebuild, MO index refresh, batch alert scans, and forecast refresh |

### 1.0.1 Supervisor contract and typed evidence

The supervisor is the control plane for both conversational requests and
proactive events. It does not answer questions or perform domain scoring. It
creates a request-scoped `TaskContext` containing:

- request/event id, task type, original utterance or anchor case id;
- caller identity, RBAC scope, language state, and citation policy;
- active conversation filters from Cache;
- total deadline, per-agent timeout, retry budget, and selected capabilities.

Relevant specialists run concurrently and return a typed `EvidenceBundle`:

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
  index_or_model_version,
  elapsed_ms
}
```

The supervisor merges bundles, detects conflicts, rechecks RBAC, and passes
only accepted claims to the Verification + Citation Agent. Contradictions are
reported in `limitations[]`; they are never silently averaged. The Composition
Agent receives verified claims only, and the Translation Agent renders the
final answer while preserving names and `CrimeNo`s verbatim.

For proactive work, the same contract is invoked by a post-ingestion Function
or Cron. `SilentMatchAgent` consumes structured, identity, graph, and semantic
bundles, applies the bounded evidence scorer, and writes durable alert state.
The future `Legal Deadline Agent` uses the same contract but is not part of the
current committed feature set until its own spec is approved.

### 1.1 Structured layer (primary)

- All 23 tables loaded into **Catalyst Data Store** exactly as per the ER diagram.
- **Query Agent = NL→SQL**: the prompt to Qwen 2.5-14B (QuickML LLM Serving) contains the schema description plus the *actual lookup values* (CrimeHead/SubHead names, CaseStatus values, district and station names, Act short-names) so the model maps "murder" → `CrimeSubHead.CrimeHeadName='Murder'` and "Bengaluru East" → the right `Unit`/`District` IDs without guessing.
- **Validation layer before execution**: generated SQL is parsed and checked against an allowlist of tables/columns/functions; anything outside it is rejected and re-prompted. SELECT-only, always scoped by the caller's RBAC filter (§1.5). This is the NL→SQL hallucination guard.
- Every structured answer cites the `CrimeNo`s (and aggregate counts cite the filter used), rendered as clickable citations.

### 1.2 Semantic layer (secondary)

- `BriefFacts` chunked **one chunk per case** (narratives are summary-length) into **QuickML Knowledge Base**, each chunk prefixed with metadata: `CrimeNo`, CaseMasterID, district, station, crime head, registered date.
- `Narrative Retrieval Agent` handles "what happened in this case" through QuickML RAG and delegates cross-lingual similar-case retrieval to the provider-neutral `MoMatcher` service.
- `MoMatcher` indexes Kannada, English, and mixed-language `BriefFacts` in one shared embedding space, returns top accessible cases with original sentence excerpts and controlled MO concepts, and records model/index versions.
- `SilentMatchAgent` consumes `mo_similarity` only as bounded evidence (maximum 10 points); semantic similarity alone can never create an alert.
- All hits join back to structured rows via `CaseMasterID` for RBAC, enrichment, and `CrimeNo` citation.

### 1.3 Relationship layer (derived graph)

Built at ingestion as Data Store tables (Catalyst has no native graph DB — same trade-off the report documents):

| Table | Content |
|---|---|
| `PersonNode` | Accused + complainants resolved across cases: normalised name (lowercase, initials expanded, transliteration-normalised) + age band (±3 yrs) + gender → one person node with member records |
| `EdgePersonCase` | `same_person_in` — person node → every case they appear in, with role (accused/complainant) |
| `EdgeCaseEmployee` | `investigated_by` — case → registering officer / IO (`PolicePersonID`, `ArrestSurrender.IOID`) |
| `EdgeCaseSection` | `charged_under` — case → Act/Section (from `ActSectionAssociation`) |
| `EdgeCaseNear` | `near` — case ↔ case within geo radius (e.g. 500 m) and time window (e.g. 30 days) |

- **Traversal in Catalyst Functions**: k-hop neighbourhood of a person node; shortest path between two cases; "who connects these FIRs".
- **Entity resolution is the linchpin and the biggest accuracy risk** — thresholds tuned on seeded synthetic variants in the data generator. Every resolved link carries a match-confidence surfaced in the answer ("possible same person, name variant").

### 1.4 Query routing — supervisor task graphs

The Supervisor Agent classifies the task, selects the smallest relevant set of
specialists, and fans them out concurrently. The old two-regime distinction is
retained as task profiles, not as separate linear pipelines:

**Structured task profile:** `Structured Query Agent` generates and validates
NL→SQL over Data Store for counts, filters, dates, joins, and exact facts.

**Narrative task profile:** `Narrative Retrieval Agent` runs QuickML RAG for
case narratives and `MoMatcher` for cross-lingual similar-case retrieval.

**Relationship task profile:** `Structured Query Agent`, `Graph Agent`, and
`Narrative Retrieval Agent` run in parallel. The graph agent expands derived
edges; the narrative agent reranks `BriefFacts`; the verifier checks the edge
and `CrimeNo` citations together.

**Mixed task profile:** all independent structured, semantic, graph, and
analytics evidence producers run concurrently, then return typed
`EvidenceBundle`s to the verifier. An agent is omitted when its capability is
not required by the task.

**Proactive task profile:** a post-ingestion event or Cron creates a task with
an anchor case or date window. `SilentMatchAgent` combines structured,
identity, graph, and semantic bundles and persists a deduplicated alert. The
same scanner contract supports both live and replayable batch execution.

GraphRAG remains the fusion behavior for link/network questions, but it is
implemented as a supervisor task graph:

```
Supervisor → SQL + graph + BriefFacts/MO agents in parallel
→ typed EvidenceBundles → conflict/RBAC/citation verification
→ composition → answer with CrimeNo + edge citations
```

The supervisor uses Catalyst Function orchestration for short tasks and
Catalyst Circuits for durable fan-out, retries, or long-running work. No agent
can bypass validation, RBAC, or citation verification.

### 1.5 RBAC, masking, audit (mapped to real tables)

- Roles come from the schema itself: `Rank.Hierarchy` + `Employee.UnitID`/`DistrictID`. Demo logins are rows in `Employee`.
  - **Constable**: cases of own station (`Unit`) only; caste/religion columns masked.
  - **Inspector/IO**: own district, full person detail, graph access.
  - **SP**: district-wide aggregates and trends.
- Masking of DPDP-sensitive fields (`CasteID`, `ReligionID` on complainants) enforced in the serving Function, not the UI.
- **Audit**: every query → append-only Data Store table (who, role, question, generated SQL, CrimeNos returned, timestamp) + a simple viewer page.

### 1.6 Kannada bridge, voice & conversation features

- **Translate–reason–translate**: the Translation Agent detects language, pivots to English for specialist reasoning, and renders verified output back in Kannada; names and CrimeNos are preserved verbatim.
- **Voice interaction**: browser-native Web Speech API (`SpeechRecognition`/`SpeechSynthesis`) converts voice↔text at the client; after that it enters the Supervisor Agent as a normal request. Spike Kannada coverage in-browser early; fall back to a Zia/STT service, then to typed-only (cut line).
- **Context-aware conversations**: Catalyst Cache keyed by session holds active filters and the prior verified task context. The Supervisor reads it before building the next task graph, so "now just the two-wheelers" narrows the previous result.
- **PDF export of conversation history**: transcript + citations already exist in Cache/audit; a SmartBrowz Function renders them to PDF on request. No new data path.

### 1.7 Analytics & prediction layer

All of these are supervisor-dispatched specialist tasks over tables already
being built. Long-running or proactive tasks use Catalyst Circuits/Cron; short
tasks use Catalyst Functions. No non-Catalyst service is introduced.

| Capability | Implementation |
|---|---|
| **Crime pattern discovery** (GraphRAG, Regime B) | GraphRAG fusion: structured filter → graph expansion over shared persons/sections/geo → `BriefFacts` semantic rerank → composed pattern with citations. Complemented by DBSCAN spatial clusters; repeat patterns fall out of the entity-resolution graph. |
| **Trend detection** | Group-by roll-ups over `CrimeRegisteredDate` × `CrimeSubHeadID` × `PoliceStationID`; QuickML time-series for smoothing/seasonality. |
| **Hotspot map** | DBSCAN clusters rendered on a map view in the UI. |
| **Predictive analytics & early warnings** | QuickML time-series/anomaly forecast of next-period case counts per station × crime type; alert when actual or forecast crosses threshold vs. historical baseline. **Geographic/temporal only — never a per-person risk score.** |
| **Criminal network analysis** (GraphRAG, Regime B) | Graph traversal (k-hop, path) **plus community detection and centrality**, run as a Function (NetworkX or equivalent) over a snapshot of the edge tables — surfaces rings and brokers; GraphRAG composes the finding into a cited narrative. |
| **Network visualization** | Function returns the subgraph for a person/case; frontend renders with a lightweight force-directed component. |
| **Socio-demographic insights** | NL→SQL aggregates over `ComplainantDetails`/`Victim`/`Accused` demographics (age, gender, occupation; religion/caste only as aggregates to analyst/SP roles). **Guardrail: caste/religion are never features in any predictive or scoring model.** |
| **Behavioral profiling** | Per `PersonNode`: assemble all linked cases (sections, times, geo, `BriefFacts`), Qwen composes a cited narrative profile — "common thread" summary, not a black-box score. |
| **Proactive prevention intelligence** | Synthesis briefing for command roles: rising-trend hotspots joined with active repeat offenders nearby ("burglaries in this cluster 40% above baseline; 2 repeat offenders with cases in range"). Decision-support only, fully logged, never an automated trigger. |
| **Cross-jurisdiction silent-match alerts** | Post-ingestion or Cron creates a supervisor task; structured, identity, graph, and cross-lingual MO agents run in parallel; `SilentMatchAgent` scores bounded evidence, deduplicates by alert type + unordered case pair, routes to authorized case owners and district command, and exposes the same durable alert in inbox/chat. |
| **Statutory deadline risk** | Reserved `Legal Deadline Agent` contract for BNSS 60/90-day calculations; not in the current committed feature set until its own legal/data spec is approved. Missing dates/classification must yield `unknown`, never a guessed deadline. |

### 1.8 Capability data-flow diagrams

Each capability is a supervisor task graph. Independent evidence producers run
in parallel, return typed `EvidenceBundle`s, and converge at the same
verification/citation gate. All read from the same Data Store tables, derived
edges, MO index, and operational alert tables (§1.1-§1.3).

**Crime pattern discovery**

```mermaid
flowchart LR
  Q["NL question<br/>(pattern/trend)"] --> SUP["Supervisor<br/>task graph"]
  SUP -. parallel .-> SQL["Structured Query Agent<br/>filter + aggregates"]
  SUP -. parallel .-> GRAPH["Graph Agent<br/>edges + neighbourhood"]
  SUP -. parallel .-> MO["Narrative Retrieval Agent<br/>BriefFacts + MO matcher"]
  SUP -. parallel .-> HOT["Analytics Agent<br/>DBSCAN clusters"]
  SQL & GRAPH & MO & HOT --> ENV["EvidenceBundles"]
  ENV --> VERIFY["Verification + Citation<br/>conflict/RBAC gate"]
  VERIFY --> COMP["Composition Agent"]
  COMP --> OUT["Answer + CrimeNo/edge citations"]
```

**Criminal network analysis**

```mermaid
flowchart LR
  Q["NL question<br/>(link/network)"] --> SUP["Supervisor"]
  SUP -. parallel .-> RES["Entity Resolution Agent<br/>PersonNode candidates"]
  SUP -. parallel .-> EDGES["Graph Agent<br/>k-hop + paths"]
  SUP -. parallel .-> COMM["Graph Analytics Agent<br/>community + centrality"]
  RES & EDGES & COMM --> VERIFY["Verification + Citation<br/>edge/RBAC gate"]
  VERIFY --> COMP["Composition Agent"]
  COMP --> VIZ["Subgraph response<br/>for frontend visualization"]
  COMP --> CITE["CrimeNo + edge citations"]
```

**Socio-demographic insights**

```mermaid
flowchart LR
  Q["NL question<br/>(demographic aggregate)"] --> SUP["Supervisor<br/>RBAC + task graph"]
  SUP --> SQLQ["Structured Query Agent<br/>NL→SQL"]
  SQLQ --> VALID["Validate against<br/>table/column allowlist"]
  VALID --> MASK{"Caller rank ≥<br/>threshold?"}
  MASK -- no --> AGGONLY["Force aggregate-only query<br/>(no row-level caste/religion)"]
  MASK -- yes --> FULLQ["Aggregate query incl.<br/>masked fields for authorised roles"]
  AGGONLY --> RUN
  FULLQ --> RUN["Execute group-by<br/>ComplainantDetails/Victim/Accused<br/>× CrimeHead/District (Data Store)"]
  RUN --> GUARD["Guardrail check:<br/>no individual identification,<br/>never feeds a scoring model"]
  GUARD --> COMP["Composition Agent<br/>descriptive summary"]
  COMP --> OUT["Answer + filter citation"]
```

**Behavioral profiling**

```mermaid
flowchart LR
  Q["NL question<br/>('profile this accused')"] --> SUP["Supervisor"]
  SUP -. parallel .-> RES["Entity Resolution Agent<br/>PersonNode"]
  SUP -. parallel .-> LINK["Graph Agent<br/>linked cases"]
  SUP -. parallel .-> TEXT["Narrative Retrieval Agent<br/>BriefFacts + MO"]
  RES & LINK & TEXT --> COMMON["EvidenceBundles<br/>common sections/time/MO"]
  COMMON --> VERIFY["Verification + Citation"]
  VERIFY --> COMP["Composition Agent<br/>cited narrative profile"]
  COMP --> FLAG["Tag: decision-support summary,<br/>not a risk score"]
  FLAG --> OUT["Profile + CrimeNo citations<br/>per linked case"]
```

**Proactive crime prevention intelligence**

```mermaid
flowchart LR
  TRIG["Trigger:<br/>Cron or on-demand"] --> SUP["Supervisor<br/>proactive task graph"]
  SUP -. parallel .-> TREND["Analytics Agent<br/>forecast + anomaly"]
  SUP -. parallel .-> HOT["Analytics Agent<br/>DBSCAN hotspot"]
  SUP -. parallel .-> NET["Graph Agent<br/>nearby repeat offenders"]
  TREND & HOT & NET --> THRESH{"Actual/forecast ><br/>baseline threshold?"}
  THRESH -- no --> IDLE["No alert"]
  THRESH -- yes --> MERGE["EvidenceBundles<br/>trend + hotspot + network"]
  MERGE --> RBACG["RBAC gate:<br/>command roles only (SP/Crime Branch)"]
  RBACG --> COMP["Verification + Composition Agents"]
  COMP --> LOG["Log to audit<br/>(Data Store)"]
  COMP --> OUT["Briefing card / PDF<br/>(SmartBrowz)"]
```

**Cross-lingual MO matching and silent-match alerts**

```mermaid
flowchart LR
  TRIG["Completed FIR event<br/>or Cron date window"] --> SUP["Supervisor<br/>proactive task graph"]
  SUP -. parallel .-> STRUCT["Structured Query Agent<br/>candidate cases"]
  SUP -. parallel .-> ID["Entity Resolution Agent<br/>name/age/gender"]
  SUP -. parallel .-> MO["Narrative Retrieval Agent<br/>Kannada-English MO matcher"]
  SUP -. optional .-> GRAPH["Graph Agent<br/>derived edge enrichment"]
  STRUCT & ID & MO & GRAPH --> SCORE["Silent-Match Agent<br/>bounded weighted scorer"]
  SCORE --> DEDUP["Alert repository<br/>upsert + evidence history"]
  DEDUP --> ROUTE["Recipient routing<br/>case owners + command"]
  ROUTE --> SURFACE["Durable inbox + shared chat card"]
  SCORE --> CITE["CrimeNo + evidence citations"]
 ```

---

## 2. Scope & cut lines

**Committed (must demo):**

*Multi-agent execution foundation*
0. Supervisor Agent with typed `TaskContext`/`EvidenceBundle`, capability-based parallel fan-out, verification/citation gate, bounded retries, and backward-compatible response shaping

*Core conversational platform*
1. NL question → cited answer (NL→SQL + validation + CrimeNo citations), English + Kannada, through the Supervisor Agent
2. Voice-enabled interaction (Web Speech API entering the supervised task graph)
3. Context-aware multi-turn conversations (Catalyst Cache session state)
4. PDF export of conversation history (SmartBrowz)
5. Explainable answers + immutable audit trail
6. RBAC by rank (Catalyst Auth + `Rank`/`Unit` scoping, DPDP field masking)

*Analytics & intelligence (§1.7)*
7. Crime pattern discovery (SQL aggregates + MO similarity + DBSCAN clusters)
8. Criminal network analysis + visualization (traversal, community detection, centrality; GraphRAG fusion for link questions)
9. Hidden-link discovery (entity-resolution graph)
10. Crime trend & hotspot detection (roll-ups + DBSCAN map)
11. Predictive analytics & early warnings (station × crime-type forecasts, threshold alerts — geographic only)
12. Socio-demographic insights (demographic aggregates, guardrailed)
13. Behavioral profiling (cited per-person narrative from linked cases)
14. Proactive prevention briefing (trend + network synthesis for command roles)
15. Cross-lingual Kannada-English MO matching for similar-case search and alert evidence
16. Cross-jurisdiction silent-match alerts with batch replay and post-ingestion live scan

**Cut lines (pre-agreed degradations, invoke without debate if a feature is at risk of not being demo-ready):**
| Feature at risk | Degrade to |
|---|---|
| Voice input | Typed Kannada only |
| Fuzzy entity resolution | Exact normalised-name match (synthetic data guarantees matches) |
| Multi-agent fusion into one answer | Return the strongest verified specialist result with explicit limitations |
| Community detection / centrality | k-hop traversal + path-finding only |
| Predictive forecasts | Descriptive trend charts (actuals vs. baseline, no forecast) |
| Prevention briefing | Two separate views (hotspot map + repeat-offender list) instead of one synthesis |
| Behavioral profile | Raw linked-case list without the composed narrative |
| Cross-lingual MO index | Structured candidate matching plus same-language lexical evidence; no semantic alert contribution |
| Live silent-match trigger | Nightly/replayable batch scan using the same scanner contract |
| PDF export | Print-to-PDF from the browser |

---

## 3. Risk register

| Risk | Likelihood | Trigger | Mitigation / fallback |
|---|---|---|---|
| ZCQL can't express needed joins/aggregates | Med | Early Catalyst capability check | Precomputed denormalised views at ingestion; Functions-side join composition |
| NL→SQL hallucinates columns/values | High | Eval failures | Allowlist validation + re-prompt; lookup values in prompt; SELECT-only |
| Entity-resolution false positives | Med | Wrong links in rehearsal | Curated seeds guarantee true positives; confidence shown on every link; cut line → exact match |
| Qwen Kannada generation weak | High (known) | Kannada answers garbled | English-pivot bridge is the design; names/IDs passed through verbatim |
| QuickML RAG has no chat history | Certain (known) | — | Multi-turn context is app-layer by design: session state in Catalyst Cache (§1.6) |
| QuickML quotas/latency too tight for live demo | Med | Early Catalyst capability check | Cache pre-staged demo queries; trim dataset; recorded backup |
| Specialist fan-out exceeds latency or Catalyst concurrency limits | Med | p95 task latency or throttling during rehearsal | Capability-based dispatch, per-agent deadlines, bounded parallelism, Cache for repeated evidence, Circuits for durable retries, and a verified partial-result policy |
| Specialist evidence conflicts | Med | SQL, graph, or narrative bundles disagree | Typed EvidenceBundle conflict detection; verifier rejects unsupported claims and exposes limitations |
| Agent boundary leaks sensitive fields | Med | Privacy regression tests or audit review | RBAC at dispatch and merge; caste/religion exclusion tests; no free-form agent-to-agent state |
| Live and batch silent-match paths diverge | Med | Same fixture produces different alert score | One SilentMatchScanner contract; parity test runs both `date_window` and `anchor_case_id` modes |
| Demo-day connectivity failure | Low | — | Recorded backup demo (mandatory) |
| Synthetic data looks fake to jury | Med | Q&A | Schema is the *official* one; say so — "runs unchanged on real CCTNS rows" |
| Web Speech API lacks Kannada STT in target browser | Med | Voice spike | Zia/STT service fallback; cut line → typed Kannada |
| Forecasts meaningless on synthetic data | High | Eval | Seed the generator with deliberate trends/seasonality so forecasts have signal; present as capability demo, not validated prediction |
| 16 committed features overload the team | High | Any checkpoint slip | Cut lines above are per-feature and pre-agreed; supervisor foundation and core platform (items 0–6) outrank analytics and proactive intelligence (7–16) |
| Profiling/demographics read as discriminatory | Med | Jury Q&A | Guardrails are in the design (§1.7): no person risk scores, caste/religion never model features, aggregates only — say so proactively |

---

## 4. Demo runbook (8 beats) & metrics

**Beats — every query pre-staged against known synthetic records:**
1. **Kannada voice question, cited answer** — constable login asks *by voice* in Kannada: "ಕಳೆದ 6 ತಿಂಗಳಲ್ಲಿ ಬೆಂಗಳೂರು ಪೂರ್ವದಲ್ಲಿ ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು?" → spoken + written Kannada answer with CrimeNo citations.
2. **Context follow-up** — "ಅದರಲ್ಲಿ ದ್ವಿಚಕ್ರ ವಾಹನ ಕಳ್ಳತನ ಮಾತ್ರ" ("only the two-wheeler ones") → system narrows the previous result using session memory.
3. **RBAC made visible** — switch to Inspector login, same question → richer rows (demographics unmasked, more stations); say the sentence: "same engine, role-scoped."
4. **Hidden link + network** — "Is the accused in FIR X connected to any other cases?" → graph lights up: *Ravi Kumar / Ravi K, 4 FIRs, 3 stations*, with match confidence; zoom out to the community view showing the wider ring and its most-connected node.
5. **Pattern → prediction** — SP login: hotspot map with a cluster trending above baseline → early-warning card → prevention briefing naming the repeat offenders active near it.
6. **Behavioral profile** — click a repeat offender → cited narrative profile: preferred sections, time-of-day, MO summary from `BriefFacts`.
7. **Explainability** — click any citation → the exact CaseMaster row and BriefFacts excerpt.
8. **Audit + export** — open the audit viewer (every query logged), then one click → PDF of the whole conversation.
9. **Cross-jurisdiction silent match** — replay a completed bilingual FIR, show parallel structured/entity/MO evidence, deliver one deduplicated alert to both authorized case sides, and mark it `Linked` with a note.

**Metrics (report §12 trimmed to what 2 weeks can prove, shown as a slide + live eval script):**
- SQL correctness on the 30-question labelled set (target ≥ 85%)
- Hallucination rate: % of answer claims not traceable to a CrimeNo (target ~0 — the headline number)
- Recall@5 for similar-case retrieval on seeded MO pairs
- p95 end-to-end latency (target < 8 s)
- Kannada parity spot-check: 10 paired KN/EN questions, same answers
- Specialist bundle completion rate and p95 supervisor latency
- Evidence conflict rate and unsupported-claim rejection rate
- Batch/live silent-match parity on seeded case pairs
- Alert deduplication rate under repeated live events

---

## 5. Definition of done

- Supervisor dispatch, typed evidence envelopes, verification, and backward-compatible responses pass contract and failure-path tests.
- All 16 committed features pass in a full run-through **on Catalyst, not localhost** (cut-line degradations count as passing if invoked per §2).
- Batch and post-ingestion live silent-match scans produce identical evidence for identical fixtures and do not duplicate alerts.
- Cross-lingual MO matches return original Kannada/English excerpts, both `CrimeNo`s, and model/index version.
- Recorded backup demo exists.
- Eval numbers computed and on the slide.
- Every table/column referenced in code exists in [Police_FIR_ER_Diagram.md](Police_FIR_ER_Diagram.md) — no invented schema.
