# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

Planning documents for **Datathon 2026, KSP SCRB Challenge 01** — a conversational AI system for the Karnataka State Police crime database. There is no source code here yet; this is the pre-implementation design phase. The repo has no build system, package manager, or test suite — do not invent one.

## Document map

- **`Police_FIR_ER_Diagram.md`** — the authoritative, provided database schema (26 tables, CCTNS-style, centred on `CaseMaster`). Any code written later must reference only tables/columns that exist in this file; do not invent schema.
- **`PLAN.md`** — the execution plan, schema-grounded. **This supersedes the technical report's §04–§08 architecture wherever the real schema contradicts it.** Treat `PLAN.md` as the current source of truth for architecture, scope, and cut lines.
- **`KSP-Datathon2026-Conversational-AI-Technical-Report.html`** — the earlier strategy document (broader state-of-the-art survey, jury-facing framing). Still useful for problem framing, persona analysis, and evaluation-metric rationale, but its architecture sections are provisional and were narrowed once the real schema arrived.

## Non-negotiable constraints

- **Platform is mandated: Zoho Catalyst.** Every architecture box must map to a real Catalyst service (Data Store, Circuits/Functions, QuickML, Zia, SmartBrowz, Auth, API Gateway, Cache, Stratus, Cron). Third-party substitution where a Catalyst service exists can invalidate the submission — don't suggest e.g. a standalone vector DB or a non-Catalyst LLM host without flagging the tradeoff.
- **Schema reality shapes the design** (`PLAN.md` §1): the only free text is `CaseMaster.BriefFacts`; geo is `latitude`/`longitude`; there are no phone, vehicle, address, or bank-account entities, and no cross-case person ID. Any "hidden link" or graph feature must be *derived* (entity resolution on names/age/gender), not looked up from a master table.
- **Two query regimes** (`PLAN.md` §1.4) — keep these distinct when discussing routing:
  - **Regime A** (everyday Q&A): NL→SQL for aggregate/filter/exact-fact questions, traditional RAG over `BriefFacts` for semantic/narrative questions.
  - **Regime B** (GraphRAG): reserved for link/pattern/network questions; fuses SQL filter → derived-graph expansion → `BriefFacts` semantic rerank → composed, cited answer.
- **Guardrails are part of the design, not an afterthought**: caste/religion (`CasteID`, `ReligionID`) are DPDP-sensitive, masked by rank in the serving layer (not the UI), never used as features in any predictive/scoring model, and exposed only as aggregates to authorised roles. Behavioral profiling and prevention briefings are decision-support narratives, never automated risk scores or triggers.
- **RBAC comes from the schema itself**: `Rank.Hierarchy` + `Employee.UnitID`/`DistrictID` — there is no separate roles table to design.
- **Every structured or semantic answer must cite `CrimeNo`s.** Explainability/citation is the headline differentiator called out in both documents — don't propose an answer path that can't trace back to specific cases.
- **Kannada-first, English-pivot**: detect language → translate to English for reasoning/NL→SQL → render the answer back in the original language, with names/CrimeNos passed through verbatim (never translated/altered).

## Working in this repo

- When extending `PLAN.md`, keep new architecture consistent with the Mermaid diagrams already there (component architecture, request data flow, and the five per-capability pipelines in §1.8) rather than introducing a parallel description.
- Respect the pre-agreed cut lines (`PLAN.md` §2) when scoping work under time pressure — they're meant to be invoked without re-litigating.
- If a future change to the schema file (`Police_FIR_ER_Diagram.md`) occurs, re-check `PLAN.md` §1 for claims ("no phone/vehicle/address entities", "no cross-case person ID") that depend on the schema as currently described, since the whole derived-graph strategy hinges on that absence.
