"""Deterministic Kannada/English narrative normalization and MO concepts."""
import re
import unicodedata

try:
    from .mo_models import NormalizedNarrative
except ImportError:
    from mo_models import NormalizedNarrative


VERSION = "mo-normalize-v1"
_CONCEPTS = {
    "entry_method": ("broken lock", "ಬೀಗ ಮುರಿದು", "ಬಾಗಿಲು ಮುರಿದು", "forced entry"),
    "weapon": ("knife", "ಚಾಕು", "weapon", "sharp object"),
    "transport": ("motorcycle", "motorbike", "ಬೈಕ್", "two-wheeler"),
    "timing": ("night", "midnight", "ರಾತ್ರಿ", "daytime"),
    "concealment": ("cctv", "ಸಿಸಿಟಿವಿ", "covered face", "disguise"),
    "target_type": ("house", "ಮನೆ", "phone", "ಮೊಬೈಲ್", "vehicle", "ವಾಹನ"),
}


def split_sentences(text):
    value = unicodedata.normalize("NFKC", text or "").strip()
    if not value:
        return []
    parts = re.split(r"(?<=[.!?।])\s+", value)
    return [part.strip() for part in parts if part.strip()]


def extract_mo_concepts(text):
    value = unicodedata.normalize("NFKC", text or "")
    folded = value.casefold()
    return [concept for concept, terms in _CONCEPTS.items()
            if any(term.casefold() in folded for term in terms)]


def _language_flags(text):
    flags = []
    if re.search(r"[\u0c80-\u0cff]", text):
        flags.append("kn")
    if re.search(r"[A-Za-z]", text):
        flags.append("en")
    return tuple(flags or ("unknown",))


def normalize_narrative(text):
    original = text or ""
    normalized = unicodedata.normalize("NFKC", original)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\s+([,.!?।])", r"\1", normalized)
    return NormalizedNarrative(
        original=original,
        normalized=normalized,
        language_flags=_language_flags(normalized),
        concepts=tuple(extract_mo_concepts(normalized)),
        normalization_version=VERSION,
    )
