from functions.silent_match.index_cases import index_cases
from functions.silent_match.run_scan import run_scan


class Provider:
    def __init__(self):
        self.texts = []

    def embed_documents(self, texts):
        self.texts.extend(texts)
        return [[1.0, 0.0] for _ in texts]


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
