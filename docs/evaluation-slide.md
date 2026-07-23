# KSP Crime Copilot — evaluation slide

## Offline synthetic contract baseline

This slide is generated from the labelled synthetic dataset and deterministic
local adapters. It verifies application execution and evidence contracts; it
does **not** claim live GLM-4.7 model quality. Live Catalyst values remain
pending an authenticated project run.

| Metric | Measured | Target | Status |
|---|---:|---:|---|
| SQL execution accuracy (30 labelled questions) | 100.0% | ≥ 85% | PASS |
| Unsupported CrimeNo hallucination rate | 0.0% | 0% | PASS |
| Local p95 end-to-end latency | 0.020s | < 8s | PASS |
| Backup replay beats | 9/9 | 9/9 | PASS |

## Live measurement gate

- QuickML GLM-4.7 SQL/composition quality: pending authenticated Catalyst run.
- Kannada/English parity and real speech recognition: pending live voice test.
- Live p95 latency, specialist completion, and alert deduplication: pending
  Catalyst Job Scheduling and smoke execution.
- The checked-in deployment configuration intentionally leaves the RAG and
  multilingual embedding endpoints blank until the account-side endpoints
  are provisioned.
