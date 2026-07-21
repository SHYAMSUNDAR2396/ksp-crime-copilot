# Cross-Lingual Semantic MO Matching Design

Date: 2026-07-21  
Project: KSP Crime Copilot  
Status: Approved for written-spec review

## Goal

Add a Kannada-English semantic matching layer for `CaseMaster.BriefFacts`.
The layer supports similar-case search and enriches the existing
Cross-Jurisdiction Silent-Match Alerts scorer. It must preserve CrimeNo
citations, role-based visibility, deterministic batch replay, and human review
of every alert.

## Product Scope

The first version supports:

- Kannada, English, and mixed Kannada-English `BriefFacts`.
- Similar-case search from a case detail view or conversational request.
- A bounded `mo_similarity` evidence signal for silent-match alerts.
- Cross-language evidence excerpts and shared MO concepts.
- Versioned embeddings, index rebuilds, audit records, and structured fallback.

It does not support additional languages, custom foundation-model training,
automatic alert creation from semantic similarity alone, automatic translation
of evidence, identity resolution, or graph rendering.

## Architecture

Create a `MoMatcher` service with two consumers:

1. `SimilarCaseSearch` returns accessible cases with semantically similar MOs.
2. `SilentMatchScorer` supplies `mo_similarity` to the existing batch alert
   scorer.

The embedding provider is behind a stable interface. Catalyst QuickML is the
production provider and the intended multilingual embedding/index service. A
local deterministic adapter supports development, tests, and replayable demos.
The provider choice must not change the result contract consumed by search or
alerts.

For each eligible `CaseMaster.BriefFacts`:

1. Normalize Kannada and English text while retaining the original narrative.
2. Generate one multilingual document embedding in a shared Kannada-English
   vector space.
3. Generate sentence-level embeddings for evidence selection.
4. Store the embedding with `CaseMasterID`, `CrimeNo`, language metadata, and
   model/index version metadata.
5. Make the case available to semantic retrieval only after indexing succeeds.

The matcher must use the existing relational schema and must not require an
external vector database. The vector index may be implemented by the selected
Catalyst retrieval service; the storage adapter remains replaceable.

## Retrieval and Evidence Flow

For a similar-case request:

1. Authenticate the employee and apply the existing RBAC scope.
2. Load the source case and generate or retrieve its current embedding.
3. Retrieve candidate cases from the vector index, excluding the source case.
4. Apply structured filters and re-ranking using available crime type,
   sections, date window, and geographic distance.
5. Return the top 10 accessible matches.

For each candidate pair, return:

- raw cosine similarity;
- calibrated similarity band;
- matched `CrimeNo` and case identifier;
- shared MO concepts from a controlled bilingual operational lexicon;
- the strongest sentence-level Kannada/English evidence excerpts;
- model and index version.

The original narrative and excerpts are authoritative. The system must not
present an automatically generated paraphrase as evidence.

## Alert Integration

The existing silent-match batch scanner calls `MoMatcher` only after its
structured candidate selection and RBAC checks. The semantic signal is
bounded as follows:

- `mo_similarity` contributes at most 10 points to the existing alert score.
- It may raise confidence only when the alert already has required identity or
  structured pattern evidence.
- It cannot create either `possible_same_person` or
  `possible_linked_pattern` by itself.
- The alert stores the similarity, band, shared concepts, excerpts, and
  model/index version in its existing `EvidenceJSON`.
- The alert still cites both `CrimeNo`s and follows the existing inbox and
  triage lifecycle.

The scorer may inspect a larger candidate set than the search view, but it
persists only the strongest eligible pair for each anchor/matched case pair to
avoid duplicate alerts.

## Indexing and Lifecycle

New or updated cases enter an embedding queue. A case remains available to
structured search while its semantic status is `pending` or `failed`, but it
is excluded from semantic retrieval until indexing succeeds.

Each indexed record includes:

- `CaseMasterID`;
- `CrimeNo`;
- detected language flags for Kannada and/or English;
- normalization version;
- embedding model version;
- index version;
- embedding status and timestamps.

Embedding failures are categorized and retryable. A failed case does not fail
an alert batch. The batch records `mo_similarity_unavailable` and continues
with identity, section, time, geography, and crime-type evidence. If the index
is unavailable, similar-case search returns a structured fallback or an
explicit partial result; it must never fabricate semantic matches.

Changing the model or normalization rules creates a new index version and
requires a controlled rebuild. Re-running a batch with the same source data,
configuration, and index version must produce the same scores and alert
decisions.

## Guardrails and Privacy

- RBAC is applied before retrieval results and excerpts are returned.
- Inaccessible cases must not leak through similarity search, alert evidence,
  or audit output visible to the employee.
- Caste and religion fields are never included in text preparation, features,
  evidence, summaries, or logs.
- The feature does not produce a per-person risk score.
- Semantic matching is decision support and never confirms an offender,
  network, or identity.
- Every semantic lookup and alert enrichment is audit-logged with employee,
  role scope, source case, candidates returned, model/index version, and final
  alert outcome.

## UX Contract

Similar-case results show:

- similarity band and score;
- case type, station, district, and registered date;
- shared MO concepts;
- short source and matched-case excerpts in their original languages;
- clickable citations for both `CrimeNo`s.

The alert inbox uses the same evidence contract. Opening an alert from the
inbox or from a chat push card shows the persisted semantic evidence, rather
than running a second independent match.

## Testing

Fixed fixtures must cover:

- the same MO described in Kannada and English;
- paraphrased narratives in the same language;
- shared crime type with different MO;
- similar wording with different sections, time, and geography;
- mixed Kannada-English narratives;
- empty, missing, and failed embeddings;
- stable results across repeated indexing with one model version;
- RBAC exclusion of inaccessible cases and excerpts;
- regression proving caste and religion never enter processing or logs.

Integration tests must verify that:

1. Case search returns accessible, cited similar cases.
2. Alert scoring receives a bounded `mo_similarity` signal.
3. Semantic similarity alone cannot create an alert.
4. Batch replay is deterministic.
5. Model/index version changes are auditable.
6. Existing alert lifecycle behavior remains unchanged.

## Demo Flow

1. Seed an English case and a Kannada case describing the same operating
   pattern.
2. Open the English case and show the Kannada result with score, concepts,
   excerpts, and both `CrimeNo`s.
3. Run the silent-match batch.
4. Show semantic evidence strengthening an alert that also has structured
   evidence.
5. Show a near match that remains below the alert threshold.
6. Open the alert from the inbox and verify that the chat card exposes the
   same persisted evidence.

## Future Integration Hooks

The matcher returns stable case-pair evidence and versioned signal metadata.
Later graph construction can materialize a semantic-MO edge from the same
result without changing the alert UI, audit contract, or triage workflow.
The entity-resolution feature may add a separate identity signal, but must not
change the meaning or weight limit of `mo_similarity`.
