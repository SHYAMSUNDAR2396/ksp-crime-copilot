"""Typed values shared by the multilingual MO pipeline."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class NormalizedNarrative:
    original: str
    normalized: str
    language_flags: Tuple[str, ...]
    concepts: Tuple[str, ...]
    normalization_version: str = "mo-normalize-v1"


@dataclass(frozen=True)
class CaseBundle:
    case_id: int
    crime_no: str
    narrative: NormalizedNarrative
    station_id: int
    district_id: int
    crime_subhead_id: int
    section_codes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticMatch:
    source_case_id: int
    matched_case_id: int
    source_crime_no: str
    matched_crime_no: str
    similarity: float
    similarity_band: str
    shared_concepts: Tuple[str, ...]
    source_excerpt: str
    matched_excerpt: str
    index_version: str
