# Offline backup demo replay

`docs/demo-replay.json` is the disconnected backup for the nine-beat demo in
[`PLAN.md`](../PLAN.md). It is a replayable synthetic transcript, not a claim
that a live Catalyst account was exercised. It calls the real application
boundaries with SQLite, deterministic local narrative retrieval, and the
provider-neutral silent-match index/scanner.

Run it from the repository root with:

```bash
python -m tools.demo_replay \
  --sqlite build/demo-crime.db \
  --output docs/demo-replay.json
```

The command prints `{"failed": 0, "passed": 9}` when the replay is healthy.
The generated transcript verifies:

1. text/voice citation parity;
2. bounded conversation follow-up state;
3. rank-derived scope widening;
4. graph/entity-resolution evidence;
5. trends, hotspots, and prevention synthesis;
6. cited behavioral profiling;
7. original narrative excerpts;
8. audit visibility and local HTML export fallback; and
9. versioned indexing, batch/live silent-match parity, recipient routing, and
   a note-bearing `Linked` transition.

The local export is HTML because SmartBrowz is an account-side dependency. A
live PDF smoke test remains required before production sign-off. The JSON
contains only synthetic records and summary counts; it must not be replaced
with production case data.
