"""Build the MO index from approved CaseMaster.BriefFacts rows."""
from dataclasses import dataclass
import datetime as dt

try:
    from ..crime_query.mo_normalize import normalize_narrative
except ImportError:  # pragma: no cover
    from functions.crime_query.mo_normalize import normalize_narrative


@dataclass(frozen=True)
class EmbeddingRecord:
    case_id: int
    crime_no: str
    vector: tuple
    provider: str
    updated_at: str


def index_cases(cases, provider, index, provider_name="quickml", now=None):
    rows = list(cases or ())
    texts = [normalize_narrative(row.get("BriefFacts", "")).normalized for row in rows]
    vectors = provider.embed_documents(texts) if texts else []
    timestamp = now or dt.datetime.now(dt.timezone.utc).isoformat()
    records = [EmbeddingRecord(
        case_id=int(row["CaseMasterID"]), crime_no=row["CrimeNo"],
        vector=tuple(vector), provider=provider_name, updated_at=timestamp,
    ) for row, vector in zip(rows, vectors)]
    index.upsert(records)
    return {"indexed": len(records), "provider": provider_name}
