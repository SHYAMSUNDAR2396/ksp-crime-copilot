import sqlite3

import pytest

from functions.crime_query import catalog, db as db_module
from functions.silent_match.index_cases import (
    IndexJob, OperationalIndexStatusStore, index_cases,
)
from functions.silent_match.run_scan import run_scan


class Provider:
    def __init__(self):
        self.texts = []

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return [[1.0, 0.0] for _ in texts]


class BatchProvider(Provider):
    batch_size = 2

    def __init__(self):
        super().__init__()
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return super().embed_documents(texts)


class Index:
    def __init__(self):
        self.records = []

    def upsert(self, records):
        self.records.extend(records)


class Scanner:
    def scan(self, **kwargs):
        return kwargs


def test_index_job_normalizes_brief_facts_and_writes_records():
    provider, index = Provider(), Index()
    result = index_cases([{"CaseMasterID": 7, "CrimeNo": "FIR/7",
                           "BriefFacts": "  ಬಾಗಿಲು ಮುರಿದು  stolen phone. "}],
                         provider, index, now="2026-07-22T00:00:00Z")
    assert result["indexed"] == 1
    assert provider.texts == ["ಬಾಗಿಲು ಮುರಿದು stolen phone."]
    assert index.records[0].case_id == 7


def test_scan_job_preserves_one_contract_for_live_and_batch():
    scanner = Scanner()
    result = run_scan(scanner, {"anchor_case_id": 7, "trigger_source": "live"})
    assert result == {"date_window": None, "anchor_case_id": 7, "trigger_source": "live"}


def test_index_job_skips_current_version_and_retries_failed():
    class VersionedIndex(Index):
        index_version = "mo-v1"

    provider, index = Provider(), VersionedIndex()
    status = {
        1: {"status": "indexed", "index_version": "mo-v1", "failure_count": 0},
        2: {"status": "failed", "index_version": "mo-v1", "failure_count": 1},
    }
    cases = [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "BriefFacts": "theft"},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "BriefFacts": "theft"},
    ]

    result = IndexJob(cases, provider, index, status=status).run("mo-v1")

    assert result.skipped_current == 1
    assert result.retried_failed == 1
    assert result.indexed == 1
    assert result.failures == ()
    assert status[2]["status"] == "indexed"


def test_index_job_records_failure_without_provider_details():
    class BrokenProvider(Provider):
        def embed_documents(self, texts):
            raise RuntimeError("secret endpoint and narrative should not leak")

    class VersionedIndex(Index):
        index_version = "mo-v1"

    status = {}
    result = IndexJob(
        [{"CaseMasterID": 3, "CrimeNo": "FIR/3", "BriefFacts": "theft"}],
        BrokenProvider(), VersionedIndex(), status=status,
    ).run("mo-v1")

    assert result.failures == (3,)
    assert "secret" not in repr(result)
    assert "secret" not in repr(status)


def test_index_job_batches_provider_requests_using_configured_batch_size():
    provider, index = BatchProvider(), Index()
    cases = [
        {"CaseMasterID": number, "CrimeNo": "FIR/{0}".format(number),
         "BriefFacts": "theft {0}".format(number)}
        for number in range(1, 6)
    ]

    result = IndexJob(cases, provider, index).run("mo-v1")

    assert result.indexed == 5
    assert [len(call) for call in provider.calls] == [2, 2, 1]
    assert len(index.records) == 5


def test_index_cases_rejects_provider_vector_count_mismatch():
    class ShortProvider(Provider):
        def embed_documents(self, texts):
            return [[1.0, 0.0]]

    with pytest.raises(ValueError, match="vector count"):
        index_cases([
            {"CaseMasterID": 1, "CrimeNo": "FIR/1", "BriefFacts": "theft"},
            {"CaseMasterID": 2, "CrimeNo": "FIR/2", "BriefFacts": "burglary"},
        ], ShortProvider(), Index())


def test_failed_batch_retries_cases_individually_without_losing_healthy_rows():
    class BatchFailureProvider(BatchProvider):
        def embed_documents(self, texts):
            self.calls.append(list(texts))
            if len(texts) > 1:
                raise RuntimeError("batch unavailable")
            return [[1.0, 0.0] for _ in texts]

    provider, index = BatchFailureProvider(), Index()
    cases = [
        {"CaseMasterID": number, "CrimeNo": "FIR/{0}".format(number),
         "BriefFacts": "theft {0}".format(number)}
        for number in range(1, 4)
    ]

    result = IndexJob(cases, provider, index).run("mo-v1")

    assert result.indexed == 3
    assert result.failures == ()
    assert [len(call) for call in provider.calls] == [2, 1, 1, 1]


def test_operational_index_status_survives_job_restart(tmp_path):
    path = tmp_path / "index-state.db"
    conn = sqlite3.connect(path)
    conn.executescript(catalog.sqlite_ddl())
    conn.commit()
    conn.close()
    db = db_module.SqliteDB(str(path))
    store = OperationalIndexStatusStore(db, "mo-v1", clock=lambda: "now")
    store.set(7, {"status": "failed", "failure_count": 2})

    restarted = OperationalIndexStatusStore(db, "mo-v1", clock=lambda: "later")

    assert restarted.get(7)["status"] == "failed"
    assert restarted.get(7)["failure_count"] == 2
