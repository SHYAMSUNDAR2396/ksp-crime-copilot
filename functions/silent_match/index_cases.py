"""Build the MO index from approved CaseMaster.BriefFacts rows."""
from dataclasses import dataclass
import datetime as dt

try:
    from ..crime_query.mo_normalize import normalize_narrative
except ImportError:  # pragma: no cover
    try:
        from functions.crime_query.mo_normalize import normalize_narrative
    except ImportError:
        from mo_normalize import normalize_narrative


@dataclass(frozen=True)
class EmbeddingRecord:
    case_id: int
    crime_no: str
    vector: tuple
    provider: str
    updated_at: str


@dataclass(frozen=True)
class IndexJobResult:
    index_version: str
    indexed: int
    skipped_current: int
    retried_failed: int
    failures: tuple


class OperationalIndexStatusStore:
    """Persistent case/version status backed by fixed operational queries."""

    def __init__(self, db, index_version, clock=None):
        self.db = db
        self.index_version = index_version
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    def get(self, case_id, default=None):
        rows = self.db.read_operational(
            "MoEmbeddingJobState",
            {"CaseMasterID": int(case_id), "IndexVersion": self.index_version},
        )
        if rows:
            row = rows[0]
            try:
                return {
                    "status": row.get("Status", ""),
                    "index_version": row.get("IndexVersion", self.index_version),
                    "failure_count": int(row.get("FailureCount") or 0),
                }
            except (TypeError, ValueError):
                return default or {}
        # Backfill idempotency for records created before the state table was
        # introduced; this avoids re-embedding a verified current version.
        records = self.db.read_operational(
            "MoEmbeddingRecord",
            {"CaseMasterID": int(case_id), "IndexVersion": self.index_version},
        )
        if records and (records[0].get("Status") in (None, "", "indexed")):
            return {"status": "indexed", "index_version": self.index_version,
                    "failure_count": 0}
        return default or {}

    def set(self, case_id, state):
        filters = {"CaseMasterID": int(case_id), "IndexVersion": self.index_version}
        row = {
            "CaseMasterID": int(case_id), "IndexVersion": self.index_version,
            "Status": str(state.get("status") or ""),
            "FailureCount": int(state.get("failure_count") or 0),
            "UpdatedAt": self.clock(), "LastError": "",
        }
        existing = self.db.read_operational("MoEmbeddingJobState", filters)
        if existing:
            self.db.update_operational("MoEmbeddingJobState", existing[0]["ROWID"], row)
        else:
            self.db.insert_operational("MoEmbeddingJobState", row)


class IndexJob:
    """Idempotent, version-aware indexing contract for Catalyst Jobs.

    ``status`` is injectable. Catalyst deployments can back it with an
    operational Data Store reader/writer, while local tests use a dictionary.
    Failure messages are never returned or persisted because they may contain
    provider details or narrative data.
    """

    def __init__(self, cases, provider, index, status=None,
                 provider_name="quickml", now=None):
        self.cases = tuple(cases or ())
        self.provider = provider
        self.index = index
        self.status = status if status is not None else {}
        self.provider_name = provider_name
        self.now = now

    def run(self, index_version=None):
        version = index_version or getattr(self.index, "index_version", "")
        if not version:
            raise ValueError("index version is required")
        configured = getattr(self.index, "index_version", version)
        if configured != version:
            raise ValueError("index version does not match the index adapter")

        indexed = skipped = retried = 0
        failures = []
        pending = []
        for case in self.cases:
            case_id = int(case["CaseMasterID"])
            state = self.status.get(case_id, {})
            if (state.get("status") == "indexed"
                    and state.get("index_version") == version):
                skipped += 1
                continue
            if state.get("status") == "failed":
                retried += 1
            self._set_status(case_id, {
                "status": "indexing",
                "index_version": version,
                "failure_count": int(state.get("failure_count", 0)),
            })
            pending.append((case, state))

        try:
            batch_size = int(getattr(self.provider, "batch_size", 1))
        except (TypeError, ValueError):
            batch_size = 1
        batch_size = max(1, batch_size)
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset:offset + batch_size]
            cases = [item[0] for item in batch]
            try:
                index_cases(
                    cases, self.provider, self.index,
                    provider_name=self.provider_name, now=self.now,
                )
            except Exception:
                # A batch failure must not mark every case as permanently
                # failed: retry each case once so one malformed narrative or
                # transient provider response cannot hide healthy records.
                for case, state in batch:
                    case_id = int(case["CaseMasterID"])
                    try:
                        index_cases(
                            [case], self.provider, self.index,
                            provider_name=self.provider_name, now=self.now,
                        )
                    except Exception:
                        failures.append(case_id)
                        self._set_status(case_id, {
                            "status": "failed",
                            "index_version": version,
                            "failure_count": int(state.get("failure_count", 0)) + 1,
                        })
                        continue
                    self._mark_indexed(case_id, version)
                    indexed += 1
                continue
            for case, _state in batch:
                self._mark_indexed(int(case["CaseMasterID"]), version)
                indexed += 1
        return IndexJobResult(
            index_version=version,
            indexed=indexed,
            skipped_current=skipped,
            retried_failed=retried,
            failures=tuple(failures),
        )

    def _mark_indexed(self, case_id, version):
        self._set_status(case_id, {
            "status": "indexed",
            "index_version": version,
            "failure_count": 0,
        })

    def _set_status(self, case_id, state):
        setter = getattr(self.status, "set", None)
        if setter is not None:
            setter(case_id, state)
        else:
            self.status[case_id] = state


def index_cases(cases, provider, index, provider_name="quickml", now=None):
    rows = list(cases or ())
    texts = [normalize_narrative(row.get("BriefFacts", "")).normalized for row in rows]
    vectors = provider.embed_documents(texts) if texts else []
    try:
        vector_count = len(vectors)
    except TypeError:
        raise ValueError("embedding vector count is invalid")
    if vector_count != len(rows):
        raise ValueError("embedding vector count mismatch")
    timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat()
    records = [EmbeddingRecord(
        case_id=int(row["CaseMasterID"]), crime_no=row["CrimeNo"],
        vector=tuple(vector), provider=provider_name, updated_at=timestamp,
    ) for row, vector in zip(rows, vectors)]
    index.upsert(records)
    return {"indexed": len(records), "provider": provider_name}
