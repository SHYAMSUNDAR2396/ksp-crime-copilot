"""Replaceable semantic index backed by the existing SQLite adapter."""
import json
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class IndexHit:
    case_id: int
    crime_no: str
    similarity: float
    narrative: str
    index_version: str


def _cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


class SqliteMoIndex:
    def __init__(self, db, index_version="mo-index-v1"):
        self.db = db
        self.index_version = index_version

    def upsert(self, records):
        for record in records:
            vector = list(record.vector)
            if not vector or math.sqrt(sum(value * value for value in vector)) == 0:
                raise ValueError("zero vector cannot be indexed")
            self.db.execute_write(
                'INSERT INTO "MoEmbeddingRecord" (CaseMasterID, CrimeNo, IndexVersion, Provider, VectorJSON, UpdatedAt) '
                'VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(CaseMasterID, IndexVersion) DO UPDATE SET CrimeNo=excluded.CrimeNo, '
                'IndexVersion=excluded.IndexVersion, Provider=excluded.Provider, VectorJSON=excluded.VectorJSON, '
                'UpdatedAt=excluded.UpdatedAt, Status="indexed", FailureCount=0, LastError=""',
                (record.case_id, record.crime_no, self.index_version, record.provider,
                 json.dumps(vector), record.updated_at),
            )

    def search(self, query_vector, cases, limit=10, excluded_case_id=None):
        scored = []
        for case in cases:
            case_id = int(case["case_id"])
            if excluded_case_id is not None and case_id == excluded_case_id:
                continue
            score = _cosine(query_vector, case["vector"])
            scored.append((score, case))
        scored.sort(key=lambda item: (-item[0], int(item[1]["case_id"])))
        return [IndexHit(int(case["case_id"]), case["crime_no"], round(score, 6), case.get("narrative", ""), self.index_version)
                for score, case in scored[:limit]]


class OperationalMoIndex:
    """Catalyst Data Store persistence adapter with in-memory search inputs."""

    uses_persisted_vectors = True

    def __init__(self, db, index_version="mo-index-v1"):
        self.db = db
        self.index_version = index_version

    def upsert(self, records):
        for record in records:
            vector = list(record.vector)
            row = {
                "CaseMasterID": record.case_id,
                "CrimeNo": record.crime_no,
                "IndexVersion": self.index_version,
                "Provider": record.provider,
                "VectorJSON": json.dumps(vector),
                "UpdatedAt": record.updated_at,
                "Status": "indexed",
                "FailureCount": 0,
                "LastError": "",
            }
            existing = self.db.read_operational(
                "MoEmbeddingRecord",
                {"CaseMasterID": record.case_id, "IndexVersion": self.index_version},
            )
            if existing:
                self.db.update_operational(
                    "MoEmbeddingRecord",
                    existing[0].get("ROWID", record.case_id),
                    row,
                )
            else:
                self.db.insert_operational("MoEmbeddingRecord", row)

    def search(self, query_vector, cases, limit=10, excluded_case_id=None):
        case_by_id = {int(case["CaseMasterID"]): case for case in cases or ()}
        rows = self.db.read_operational(
            "MoEmbeddingRecord", {"IndexVersion": self.index_version}
        )
        searchable = []
        for row in rows or ():
            try:
                case_id = int(row["CaseMasterID"])
                vector = json.loads(row["VectorJSON"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if case_id not in case_by_id:
                continue
            if row.get("Status") not in (None, "", "indexed"):
                continue
            case = case_by_id[case_id]
            searchable.append({
                "case_id": case_id,
                "crime_no": case["CrimeNo"],
                "vector": vector,
                "narrative": case.get("BriefFacts", ""),
            })
        return SqliteMoIndex(None, self.index_version).search(
            query_vector, searchable, limit, excluded_case_id,
        )
