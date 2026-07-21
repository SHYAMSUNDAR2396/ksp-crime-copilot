# Cross-Lingual MO Matching + Silent-Match Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready Kannada-English MO matching service and connect it to one deterministic silent-match engine supporting replayable batch scans and post-ingestion single-case scans.

**Architecture:** MoMatcher is isolated behind provider-neutral embedding and index interfaces. QuickML is the production provider; a deterministic local adapter supports tests and demos. SilentMatchScanner owns anchor selection, structured candidate filtering, scoring, deduplicated persistence, retries, and recipient routing for both batch and live triggers.

**Tech Stack:** Python 3.9, Zoho Catalyst Data Store/ZCQL/Cron/Advanced I/O/QuickML, SQLite, requests, pytest. No external vector database, graph database, or frontend framework is introduced in this repository.

## Global Constraints

- Use Zoho Catalyst for production services; do not replace Catalyst capabilities with third-party services.
- Use only existing CaseMaster.BriefFacts for narrative input.
- Initial language scope is Kannada, English, and mixed Kannada-English BriefFacts.
- Original narratives and excerpts are authoritative; never show generated paraphrases as evidence.
- QuickML is the production embedding/index provider; a deterministic local provider is required for offline tests.
- mo_similarity contributes at most 10 points and cannot create an alert by itself.
- Persist scores >= 60; Medium is 60-79; High is >= 80.
- Initial weights: identity 50, shared crime subhead 15, shared act/section 15, date proximity 10, geography within 5 km 10, MO similarity 10.
- Exclude caste and religion from candidate selection, text processing, scoring, evidence, summaries, and logs.
- Apply RBAC before retrieval results, alert evidence, and excerpts are returned.
- Every visible match cites both CrimeNos.
- Use one scanner contract: scan(date_window | anchor_case_id).
- Live scanning starts after required FIR-side records exist; incomplete enrichment is retried and audited.
- Deduplicate by AlertType plus unordered case pair.
- Evidence re-evaluation preserves the old snapshot in append-only action history and does not silently reopen Linked or Dismissed.
- Operational tables are excluded from the NL-to-SQL allowlist.
- ZCQL joins use parent ROWID, not business primary keys.
- Preserve Python 3.9 compatibility and the deployed absolute-import fallback pattern.
- This repository has no React frontend. This plan defines stable backend contracts and fixtures; the dashboard/chat client is a separate frontend plan.

---

## File Structure

Create:

~~~
functions/crime_query/
  mo_models.py
  mo_normalize.py
  mo_embeddings.py
  mo_index.py
  mo_matcher.py
  silent_match_models.py
  silent_match_scoring.py
  silent_match_repository.py
  silent_match_scanner.py
  silent_match_api.py

functions/silent_match/
  main.py
  index_cases.py
  run_scan.py
  catalyst-config.json

docs/
  silent-match-alerts-ddl.sql
  cross-lingual-embedding-findings.md
  silent-match-production-runbook.md

tools/probe_embeddings.py

tests/
  test_mo_normalize.py
  test_mo_embeddings.py
  test_mo_index.py
  test_mo_matcher.py
  test_silent_match_scoring.py
  test_silent_match_repository.py
  test_silent_match_scanner.py
  test_silent_match_api.py
~~~

Modify existing catalog.py, db.py, rbac.py, tools/gen_data.py, and the matching
tests only where the tasks below say so. Do not add operational tables to the
frozen ER catalog.

## Shared Interfaces

~~~
class EmbeddingProvider(object):
    def embed_documents(self, texts):
        # returns List[List[float]]
        raise NotImplementedError

class MoIndex(object):
    def upsert(self, records):
        raise NotImplementedError

    def search(self, query_vector, limit, excluded_case_id=None):
        # returns List[IndexHit]
        raise NotImplementedError

class MoMatcher(object):
    def similar_cases(self, source_case, candidates, caller, limit=10):
        # returns List[SemanticMatch]
        raise NotImplementedError

class SilentMatchScanner(object):
    def scan(self, date_window=None, anchor_case_id=None,
             trigger_source="batch"):
        # returns ScanResult
        raise NotImplementedError
~~~

SemanticMatch contains source_case_id, matched_case_id, similarity,
similarity_band, shared_concepts, source_excerpt, matched_excerpt, both
CrimeNos, and index_version. ScanResult contains run_id, trigger_source,
anchors_seen, candidates_seen, alerts, alerts_created, alerts_updated,
skipped_cases, and failures.

### Task 1: Confirm the production QuickML embedding contract

**Files:**
- Create: docs/cross-lingual-embedding-findings.md
- Create: tools/probe_embeddings.py
- Modify: functions/crime_query/catalyst-config.json
- Test: tests/test_mo_embeddings.py

**Interfaces:**
- Consumes: existing Catalyst credentials and QuickML organization settings.
- Produces: the documented request/response contract used by
  QuickMLMultilingualProvider: endpoint, vector shape, batch limit, timeout,
  model version, and index version.

- [ ] Step 1: Write failing provider contract tests.

~~~python
def test_provider_normalizes_batch_response():
    transport = FakeTransport({
        "embeddings": [[0.1, 0.2], [0.3, 0.4]],
        "model": "multilingual-v1",
    })
    provider = QuickMLMultilingualProvider(
        endpoint="url", token="token", org_id="org",
        transport=transport,
    )
    assert provider.embed_documents(["ಕಳ್ಳತನ", "theft"]) == [
        [0.1, 0.2], [0.3, 0.4]
    ]

def test_provider_rejects_vector_count_mismatch():
    provider = QuickMLMultilingualProvider(
        "url", "token", "org",
        FakeTransport({"embeddings": [[0.1, 0.2]]}),
    )
    with pytest.raises(EmbeddingProviderError, match="vector count"):
        provider.embed_documents(["kn", "en"])
~~~

- [ ] Step 2: Run the focused tests.

Run: python -m pytest tests/test_mo_embeddings.py -q

Expected: FAIL because mo_embeddings.py and the adapter do not exist.

- [ ] Step 3: Run the live capability probe with two fixed, non-sensitive
  Kannada/English strings. Record the exact successful request/response shape,
  model, dimension, batch limit, and latency in the findings document. Never
  record tokens or database text.

Run: python -m tools.probe_embeddings --language-fixture

Expected: a redacted status=ok report with a positive dimension. A failed
probe blocks production QuickML deployment but not local tests.

- [ ] Step 4: Add only non-secret endpoint settings:
  QUICKML_EMBEDDINGS_ENDPOINT, QUICKML_EMBEDDINGS_MODEL,
  QUICKML_EMBEDDINGS_TIMEOUT, and QUICKML_EMBEDDINGS_BATCH_SIZE. Reuse
  app.credential.token() for OAuth.

- [ ] Step 5: Commit.

~~~
git add docs/cross-lingual-embedding-findings.md \
  functions/crime_query/catalyst-config.json tests/test_mo_embeddings.py
git commit -m "feat: define QuickML multilingual embedding contract"
~~~

### Task 2: Add operational DDL and storage boundaries

**Files:**
- Create: docs/silent-match-alerts-ddl.sql
- Modify: functions/crime_query/catalog.py
- Modify: functions/crime_query/db.py
- Test: tests/test_catalog.py
- Test: tests/test_db.py

**Interfaces:**
- Consumes: catalog.TABLES, SqliteDB, ZcqlDB, and Data Store insert/update
  primitives.
- Produces: OPERATIONAL_TABLES, operational_ddl(),
  insert_operational(table, row), update_operational(table, row_id, row),
  and read_operational(table, filters).

Create operational tables SilentMatchAlert, SilentMatchRecipient,
SilentMatchAction, SilentMatchRun, and MoEmbeddingRecord. Keep them out of
catalog.TABLES. SilentMatchAction must contain ActionType, PreviousScore,
PreviousConfidenceBand, and EvidenceSnapshotJSON. Use JSON text for evidence,
snapshots, and vectors. Add indexes for pair lookup, recipient lookup, and
case/index-version lookup.

- [ ] Step 1: Write failing tests.

~~~python
def test_operational_tables_are_not_queryable(tmp_path):
    assert "SilentMatchAlert" not in catalog.TABLES
    assert "SilentMatchAlert" in catalog.OPERATIONAL_TABLES
    database = SqliteDB(str(tmp_path / "alerts.db"))
    with pytest.raises(db_module.DBError):
        database.execute("SELECT * FROM SilentMatchAlert")

def test_operational_ddl_has_required_columns():
    ddl = catalog.operational_ddl()
    assert 'CREATE TABLE IF NOT EXISTS "SilentMatchAlert"' in ddl
    assert '"EvidenceJSON" TEXT NOT NULL' in ddl
    assert '"ActionType" TEXT NOT NULL' in ddl
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_catalog.py tests/test_db.py -q

Expected: FAIL because the operational constants, DDL, and DB methods do not
exist.

- [ ] Step 3: Implement separate operational DDL and parameterized SQLite
  writes. Implement Catalyst writes through
  app.datastore().table(name).insert_row(row) and the confirmed Data Store
  update operation. Operational reads use fixed repository queries, never
  LLM-generated SQL.

- [ ] Step 4: Run the focused tests.

Run: python -m pytest tests/test_catalog.py tests/test_db.py -q

Expected: PASS with the existing catalog and audit tests unchanged.

- [ ] Step 5: Commit.

~~~
git add docs/silent-match-alerts-ddl.sql functions/crime_query/catalog.py \
  functions/crime_query/db.py tests/test_catalog.py tests/test_db.py
git commit -m "feat: add operational storage for matching alerts"
~~~

### Task 3: Implement bilingual normalization and MO concepts

**Files:**
- Create: functions/crime_query/mo_models.py
- Create: functions/crime_query/mo_normalize.py
- Create: tests/test_mo_normalize.py
- Modify: tools/gen_data.py
- Modify: tests/test_gen_data.py

**Interfaces:**
- Consumes: raw BriefFacts and existing case identifiers.
- Produces normalize_narrative(text) -> NormalizedNarrative,
  split_sentences(text) -> List[str], extract_mo_concepts(text) -> List[str],
  and DTOs CaseBundle, EmbeddingRecord, IndexHit, and SemanticMatch.

Normalize Unicode compatibility forms, whitespace, punctuation boundaries, and
mixed-script spacing while preserving Kannada, English, digits, and original
excerpts. Support Kannada danda and English punctuation. Do not transliterate,
translate, or read caste/religion fields.

Use a versioned bilingual lexicon for entry method, weapon, transport, timing,
concealment, and target type. Concept extraction is deterministic labeling, not
LLM-generated explanation.

- [ ] Step 1: Write failing tests.

~~~python
def test_normalization_preserves_both_scripts():
    value = normalize_narrative("  ಬಾಗಿಲು ಮುರಿದು  stolen phone. ")
    assert "ಬಾಗಿಲು ಮುರಿದು" in value.text
    assert "stolen phone" in value.text
    assert value.version == "mo-normalize-v1"

def test_sentence_split_supports_kannada_danda():
    assert split_sentences("ಮನೆಗೆ ಪ್ರವೇಶಿಸಿದನು। Phone stolen.") == [
        "ಮನೆಗೆ ಪ್ರವೇಶಿಸಿದನು।", "Phone stolen."
    ]

def test_concepts_do_not_include_sensitive_metadata():
    assert "caste" not in extract_mo_concepts("caste mentioned")
    assert "religion" not in extract_mo_concepts("religion mentioned")
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_mo_normalize.py -q

Expected: FAIL because the DTO and normalization functions do not exist.

- [ ] Step 3: Implement standard-library normalization, sentence splitting, and
  the versioned lexicon. Return original and normalized text separately.

- [ ] Step 4: Extend tools/gen_data.py with fixed bilingual fixtures: one
  Kannada/English same-MO pair across districts, one linked-pattern pair
  without identity match, one near miss, and one case whose sensitive metadata
  must not affect matching. Expose a DEMO_CASE_IDS mapping. Preserve the
  existing exact-count and byte-for-byte reproducibility guarantees.

- [ ] Step 5: Run.

Run: python -m pytest tests/test_mo_normalize.py tests/test_gen_data.py -q

Expected: PASS.

- [ ] Step 6: Commit.

~~~
git add functions/crime_query/mo_models.py functions/crime_query/mo_normalize.py \
  tools/gen_data.py tests/test_mo_normalize.py tests/test_gen_data.py
git commit -m "feat: add bilingual MO normalization and fixtures"
~~~

### Task 4: Implement embedding providers and the replaceable index

**Files:**
- Create: functions/crime_query/mo_embeddings.py
- Create: functions/crime_query/mo_index.py
- Modify: tests/test_mo_embeddings.py
- Create: tests/test_mo_index.py
- Modify: tools/probe_embeddings.py

**Interfaces:**
- Consumes: NormalizedNarrative, EmbeddingRecord, and Task 1's confirmed
  QuickML contract.
- Produces EmbeddingProvider.embed_documents(texts),
  DeterministicEmbeddingProvider, QuickMLMultilingualProvider,
  MoIndex.upsert(records), MoIndex.search(query_vector, limit,
  excluded_case_id=None), and SqliteMoIndex.

The local provider uses stable standard-library Unicode code-point and
whitespace-token features hashed into a fixed dimension, then L2-normalized.
It is for tests and replay, not production quality. QuickML uses requests.Session,
the runtime OAuth token, finite timeout, batch-size enforcement, response
validation, and an exception that omits tokens and narrative content.

SqliteMoIndex stores JSON vectors in MoEmbeddingRecord and ranks with cosine.
Production callers depend only on MoIndex.

- [ ] Step 1: Write tests.

~~~python
def test_local_provider_is_stable():
    provider = DeterministicEmbeddingProvider(dimension=64)
    assert provider.embed_documents(["ಬಾಗಿಲು ಮುರಿದು"]) == \
           provider.embed_documents(["ಬಾಗಿಲು ಮುರಿದು"])

def test_index_excludes_source_and_orders_hits(index):
    index.upsert([record(1, [1.0, 0.0]), record(2, [0.9, 0.1])])
    hits = index.search([1.0, 0.0], 10, excluded_case_id=1)
    assert [hit.case_id for hit in hits] == [2]
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_mo_embeddings.py tests/test_mo_index.py -q

Expected: FAIL because the modules do not exist.

- [ ] Step 3: Implement provider validation, zero-vector rejection, cosine math,
  and index-version metadata. Keep HTTP response parsing inside the QuickML
  adapter.

- [ ] Step 4: Implement the redacted tools/probe_embeddings.py command. It
  prints only status, model, dimension, batch size, and latency, and exits
  non-zero for timeout or malformed response.

- [ ] Step 5: Run offline tests.

Run: python -m pytest tests/test_mo_embeddings.py tests/test_mo_index.py -q

Expected: PASS without network access.

- [ ] Step 6: Commit.

~~~
git add functions/crime_query/mo_embeddings.py functions/crime_query/mo_index.py \
  tools/probe_embeddings.py tests/test_mo_embeddings.py tests/test_mo_index.py
git commit -m "feat: add provider-neutral MO embedding index"
~~~

### Task 5: Implement MoMatcher with RBAC and evidence excerpts

**Files:**
- Create: functions/crime_query/mo_matcher.py
- Modify: functions/crime_query/rbac.py
- Create: tests/test_mo_matcher.py
- Modify: tests/test_rbac.py

**Interfaces:**
- Consumes: MoIndex, EmbeddingProvider, CaseBundle, Caller, and the concept
  extractor.
- Produces MoMatcher.similar_cases(source_case, candidates, caller, limit=10)
  -> List[SemanticMatch].

Apply station/district/state scope before returning retrieval results. Use only
crime sub-head, sections, date, and geography for re-ranking. Select evidence
by comparing sentence-level vectors and return the original sentence pair,
language flags, concepts, similarity band, both CrimeNos, and index version.
Never access caste/religion columns or derived values.

Add can_read_case_pair(caller, anchor_case, matched_case, db) -> bool to rbac.py
and use it before returning every match.

- [ ] Step 1: Write failing tests.

~~~python
def test_cross_lingual_match_returns_excerpts_and_concepts():
    result = matcher.similar_cases(english_case, [kannada_case], inspector, 10)
    assert result[0].matched_case_id == kannada_case.case_id
    assert result[0].source_excerpt != result[0].matched_excerpt
    assert "entry_method" in result[0].shared_concepts
    assert result[0].crime_nos == [
        english_case.crime_no, kannada_case.crime_no
    ]

def test_inaccessible_case_is_not_retrievable():
    assert matcher.similar_cases(source_case, [other_district_case], constable) == []

def test_sensitive_fields_never_reach_provider():
    provider = RecordingProvider()
    MoMatcher(index, provider, concept_lexicon).similar_cases(
        source_case, [case_with_sensitive_metadata], inspector
    )
    assert all("religion" not in text.lower() for text in provider.texts)
    assert all("caste" not in text.lower() for text in provider.texts)
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_mo_matcher.py tests/test_rbac.py -q

Expected: FAIL because MoMatcher and the access helper do not exist.

- [ ] Step 3: Implement the matcher and shared RBAC helper. Do not duplicate rank
  logic in the matcher. Return top 10 for search and a bounded larger set only
  when explicitly requested by the scanner.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_mo_matcher.py tests/test_rbac.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~
git add functions/crime_query/mo_matcher.py functions/crime_query/rbac.py \
  tests/test_mo_matcher.py tests/test_rbac.py
git commit -m "feat: add explainable bilingual MO matcher"
~~~

### Task 6: Implement pure silent-match scoring

**Files:**
- Create: functions/crime_query/silent_match_models.py
- Create: functions/crime_query/silent_match_scoring.py
- Create: tests/test_silent_match_scoring.py

**Interfaces:**
- Consumes: two CaseBundle values, accused comparison evidence, structured
  metadata, and optional SemanticMatch.
- Produces score_pair(anchor, matched, semantic_match) -> ScoreResult with
  alert_type, score, confidence_band, summary, evidence, and eligible.

Implement the exact two alert types and thresholds from the spec. Same-person
requires normalized accused-name similarity plus compatible gender and age-band
evidence when present. Linked-pattern requires a strong pattern signal and a
contextual signal. Add each configured signal once; cap MO at 10. Reject a
semantic-only candidate. Keep the scorer pure: no database, network, RBAC, or
mutation. Use careful wording and stable evidence names.

- [ ] Step 1: Write failing tests.

~~~python
def test_high_same_person_match_has_careful_wording():
    result = score_pair(ravi_anchor, ravi_match, semantic_match)
    assert result.alert_type == "possible_same_person"
    assert result.score >= 80
    assert result.confidence_band == "High"
    assert "possible" in result.summary.lower()

def test_semantic_similarity_alone_is_not_eligible():
    result = score_pair(unrelated_a, unrelated_b, strong_semantic_match)
    assert result.eligible is False
    assert result.score <= 10

def test_sensitive_fields_do_not_enter_evidence():
    result = score_pair(case_a, case_b, None)
    serialized = json.dumps(result.evidence).lower()
    assert "caste" not in serialized
    assert "religion" not in serialized
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_silent_match_scoring.py -q

Expected: FAIL because the models and scorer do not exist.

- [ ] Step 3: Implement immutable DTOs and pure scoring.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_silent_match_scoring.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~
git add functions/crime_query/silent_match_models.py \
  functions/crime_query/silent_match_scoring.py \
  tests/test_silent_match_scoring.py
git commit -m "feat: add explainable silent-match scoring policy"
~~~

### Task 7: Implement persistence, deduplication, and append-only history

**Files:**
- Create: functions/crime_query/silent_match_repository.py
- Create: tests/test_silent_match_repository.py
- Modify: functions/crime_query/db.py

**Interfaces:**
- Consumes: Task 2 DB primitives and Task 6 alert, recipient, action, and run
  DTOs.
- Produces find_alert(alert_type, case_id_a, case_id_b),
  create_alert(alert), update_alert(alert, previous_snapshot),
  ensure_recipient(recipient), append_status_action(action),
  append_evidence_update_action(action), create_run(run), finish_run(run_id,
  result).

Normalize pair ordering only for lookup; preserve the first-produced anchor.
Before every evidence update, insert an evidence_updated action with previous
score, confidence, and full evidence snapshot. Status changes use
status_changed. Linked and Dismissed reject empty notes.

- [ ] Step 1: Write failing tests.

~~~python
def test_unordered_pair_deduplicates(repo):
    first = repo.create_alert(alert("possible_linked_pattern", 10, 20))
    same = repo.find_alert("possible_linked_pattern", 20, 10)
    assert same.alert_id == first.alert_id

def test_evidence_update_preserves_previous_snapshot(repo):
    repo.create_alert(alert("possible_linked_pattern", 10, 20, score=60))
    repo.update_alert(alert("possible_linked_pattern", 10, 20, score=80),
                      previous_snapshot={"Score": 60})
    action = repo.actions_for_alert(1)[-1]
    assert action.action_type == "evidence_updated"
    assert action.previous_score == 60
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_silent_match_repository.py -q

Expected: FAIL because the repository does not exist.

- [ ] Step 3: Implement SQLite transactions and Catalyst Data Store writes.
  Storage errors become OperationalStoreError without case text or credentials
  in messages. Recipient upserts must be idempotent.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_silent_match_repository.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add functions/crime_query/silent_match_repository.py \
  tests/test_silent_match_repository.py functions/crime_query/db.py
git commit -m "feat: persist deduplicated alert history"
~~~

### Task 8: Implement shared batch/live scanning and recipient routing

**Files:**
- Create: functions/crime_query/silent_match_scanner.py
- Create: tests/test_silent_match_scanner.py

**Interfaces:**
- Consumes: MoMatcher, pure scorer, repository, DB reads, caller hierarchy,
  and CaseBundle loader.
- Produces SilentMatchScanner.scan(date_window=None, anchor_case_id=None,
  trigger_source="batch") -> ScanResult.

Load only CaseMaster, Accused, ActSectionAssociation, CrimeSubHead, Unit,
District, Employee, and ArrestSurrender as needed. Exclude the anchor station,
prefer another district, enforce the configured lookback, and never read
sensitive fields.

Require a completed live anchor. Record pending_enrichment and retry with
bounded backoff when related records are missing. Missing BriefFacts,
unavailable embeddings, or graph rebuild failures must not block structured
scoring. Recipient creation retries separately.

Route visible CaseMaster.PolicePersonID, visible ArrestSurrender.IOID, and active
employees with Rank.Hierarchy <= 3 in involved districts. Re-check pair access
before creating or returning recipient-visible evidence.

- [ ] Step 1: Write failing tests.

~~~python
def test_batch_and_live_produce_identical_alerts(scanner, seeded_cases):
    batch = scanner.scan(
        date_window=("2026-06-01", "2026-06-30"),
        trigger_source="batch",
    )
    live = scanner.scan(
        anchor_case_id=seeded_cases.anchor_id,
        trigger_source="live",
    )
    assert live.alerts[0].score == batch.alerts[0].score
    assert live.alerts[0].evidence == batch.alerts[0].evidence

def test_duplicate_live_event_updates_one_alert(scanner, repository):
    first = scanner.scan(anchor_case_id=10, trigger_source="live")
    second = scanner.scan(anchor_case_id=10, trigger_source="live")
    assert second.alerts_created == 0
    assert second.alerts_updated == 1
    assert repository.count_alerts() == 1

def test_incomplete_enrichment_is_audited(scanner, repository):
    result = scanner.scan(anchor_case_id=missing_accused_case,
                          trigger_source="live")
    assert result.skipped_cases[0].reason == "pending_enrichment"
    assert repository.latest_run().source == "live"
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_silent_match_scanner.py -q

Expected: FAIL because the scanner and case loader do not exist.

- [ ] Step 3: Implement one orchestration path after anchor selection. Record
  SilentMatchRun before work and finish it with anchor/candidate/alert/skip/
  duration/failure counts. Distinguish no match, not attempted, and incomplete
  evidence.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_silent_match_scanner.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add functions/crime_query/silent_match_scanner.py \
  tests/test_silent_match_scanner.py
git commit -m "feat: add idempotent batch and live alert scans"
~~~

### Task 9: Expose stable search and alert API contracts

**Files:**
- Create: functions/crime_query/silent_match_api.py
- Create: tests/test_silent_match_api.py
- Create: functions/silent_match/main.py
- Create: functions/silent_match/catalyst-config.json

**Interfaces:**
- Consumes: MoMatcher, SilentMatchScanner, repository access checks, and the
  existing Flask handler convention.
- Produces JSON endpoints:

~~~text
POST /similar-cases
request:  {"employee_id": 9, "case_master_id": 123, "limit": 10}
response: {"case_master_id": 123, "matches": [...], "partial": false}

POST /scan
request:  {"employee_id": 97, "anchor_case_id": 123,
           "trigger_source": "live"}
response: {"run_id": "...", "alerts_created": 1, "alerts_updated": 0}

GET /alerts/{alert_id}
response: {"alert": {...}, "recipients": [...], "actions": [...]}

POST /alerts/{alert_id}/transition
request:  {"employee_id": 9, "to_status": "Linked", "note": "..."}
response: {"alert": {...}, "action": {...}}
~~~

Chat and inbox clients must use the same persisted alert detail. The API returns
no alert or excerpt if the caller cannot read both cases. A semantic-index
failure returns partial=true with structured fallback, never fabricated semantic
matches.

- [ ] Step 1: Write failing API contract tests.

~~~python
def test_similar_cases_response_is_cited_and_versioned(client):
    response = client.post(
        "/similar-cases",
        json={"employee_id": 9, "case_master_id": 123},
    )
    assert response.status_code == 200
    assert response.json["matches"][0]["crime_nos"]
    assert response.json["matches"][0]["index_version"]

def test_linked_transition_requires_note(client):
    response = client.post(
        "/alerts/1/transition",
        json={"employee_id": 9, "to_status": "Linked", "note": ""},
    )
    assert response.status_code == 400
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_silent_match_api.py -q

Expected: FAIL because the API module and function do not exist.

- [ ] Step 3: Implement pure request/response shaping. The handler validates
  JSON, invokes services, serializes DTOs, and follows handler(request) ->
  response plus the existing absolute-import fallback. It does not duplicate
  scoring or persistence.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_silent_match_api.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add functions/crime_query/silent_match_api.py \
  functions/silent_match/main.py functions/silent_match/catalyst-config.json \
  tests/test_silent_match_api.py
git commit -m "feat: expose matching and alert APIs"
~~~

### Task 10: Add production index and scan jobs

**Files:**
- Create: functions/silent_match/index_cases.py
- Create: functions/silent_match/run_scan.py
- Modify: functions/silent_match/catalyst-config.json
- Create: docs/silent-match-production-runbook.md
- Modify: docs/CATALYST_RUNBOOK.md
- Test: tests/test_silent_match_scanner.py

**Interfaces:**
- Consumes: MoMatcher, MoIndex, SilentMatchScanner, Cron, and post-ingestion
  payloads.
- Produces: idempotent indexing and scan entrypoints with source values batch
  and live.

The index job processes changed cases, records status/timestamps/failures, and
creates a new index version when model or normalization changes. It must not
overwrite an old version in place. Cron invokes a date-window scan nightly;
post-ingestion invokes a single-anchor scan after enrichment.

- [ ] Step 1: Write failing job idempotency tests.

~~~python
def test_index_job_skips_current_version_and_retries_failed(indexer):
    result = indexer.run(index_version="mo-v1")
    assert result.skipped_current == 1
    assert result.retried_failed == 1

def test_scan_job_rejects_two_anchor_shapes(scan_job):
    with pytest.raises(ValueError):
        scan_job.run({
            "date_window": ["2026-06-01", "2026-06-30"],
            "anchor_case_id": 123,
        })
~~~

- [ ] Step 2: Run and confirm failure.

Run: python -m pytest tests/test_silent_match_scanner.py -q

Expected: FAIL because the job entrypoints do not exist.

- [ ] Step 3: Implement bounded retries, timeout, batch size, lookback,
  similarity threshold, and index version through non-secret config. Keep
  narratives out of logs. Document the exact Cron schedule and live payload.

- [ ] Step 4: Run.

Run: python -m pytest tests/test_silent_match_scanner.py -q

Expected: PASS.

- [ ] Step 5: Commit.

~~~bash
git add functions/silent_match/index_cases.py functions/silent_match/run_scan.py \
  functions/silent_match/catalyst-config.json \
  docs/silent-match-production-runbook.md docs/CATALYST_RUNBOOK.md \
  tests/test_silent_match_scanner.py
git commit -m "ops: wire production matching jobs"
~~~

### Task 11: Full verification and Catalyst smoke tests

**Files:**
- Modify: docs/silent-match-production-runbook.md
- Modify: docs/cross-lingual-embedding-findings.md

**Interfaces:**
- Consumes: all services and fixtures from Tasks 1-10.
- Produces: a passing offline suite, redacted provider probe, deterministic
  demo evidence, deployment verification, and residual-risk record.

- [ ] Step 1: Run the full offline suite.

Run: python -m pytest -q

Expected: all existing and new tests pass; any existing query, RBAC,
translation, catalog, or generator failure blocks completion.

- [ ] Step 2: Verify deterministic data and scan results.

~~~
python -m tools.gen_data --sqlite /tmp/ksp-crime-a.db --csv /tmp/ksp-crime-a-csv
python -m tools.gen_data --sqlite /tmp/ksp-crime-b.db --csv /tmp/ksp-crime-b-csv
diff -ru /tmp/ksp-crime-a-csv /tmp/ksp-crime-b-csv
~~~

Expected: no diff. Batch and single-anchor scans over the same data must have
identical serialized evidence and scores.

- [ ] Step 3: Run the provider probe.

Run: python -m tools.probe_embeddings --language-fixture

Expected: status=ok, stable positive dimension, no secret or case text in output.

- [ ] Step 4: Deploy and verify Catalyst.

Run: catalyst deploy --only functions:silent_match

Verify operational tables, one fixture index record, one post-ingestion live
alert, one Cron batch run, one deduplicated pair, authorized detail access,
and denied unauthorized detail access.

- [ ] Step 5: Execute the production-shaped demo: register/replay a completed
bilingual FIR, run the live scan, show both authorized inbox recipients,
inspect both CrimeNos and original excerpts, run the batch scan to show zero
duplicates, refresh evidence to show history, and transition to Linked with a
non-empty note.

- [ ] Step 6: Record observed QuickML latency/limits, retry behavior, ZCQL
write behavior, and the explicit missing-frontend boundary in the runbook.

- [ ] Step 7: Commit verification evidence.

~~~bash
git add docs/silent-match-production-runbook.md \
  docs/cross-lingual-embedding-findings.md
git commit -m "docs: verify production matching rollout"
~~~

## Self-Review

Spec coverage is complete: normalization and bilingual scope are Tasks 3-5;
QuickML and versioned indexing are Tasks 1, 4, and 10; search evidence and
citations are Tasks 5 and 9; bounded scoring is Task 6; batch/live scanning,
deduplication, recipients, retries, history, RBAC, fixtures, and deployment
are Tasks 7-11.

No unresolved markers remain in the plan. Later tasks use the
interfaces defined at the top. The only explicit gap is the absent React
frontend, which is recorded as a separate follow-on plan rather than hidden
inside backend work.
