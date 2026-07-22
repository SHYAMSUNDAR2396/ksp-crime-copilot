"""Value objects for deterministic silent-match alerts."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ScoreResult:
    alert_type: str
    score: int
    confidence_band: str
    evidence: Tuple[Tuple[str, float], ...]
    persistable: bool
    limitation: str


@dataclass(frozen=True)
class ScanResult:
    run_id: str
    trigger_source: str
    anchors_seen: int
    candidates_seen: int
    alerts: Tuple[dict, ...]
    alerts_created: int
    alerts_updated: int
    skipped_cases: Tuple[int, ...] = ()
    failures: Tuple[str, ...] = ()
