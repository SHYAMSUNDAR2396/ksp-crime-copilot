"""Privacy-preserving descriptive demographic aggregates."""
from collections import Counter

try:
    from .access import AccessPolicyError, require_capability
except ImportError:  # pragma: no cover
    from access import AccessPolicyError, require_capability


SENSITIVE_DIMENSIONS = frozenset({"CasteID", "ReligionID"})


def demographic_aggregate(context, rows, dimension):
    require_capability(context, "query_structured_cases")
    if dimension in SENSITIVE_DIMENSIONS and context.rank_hierarchy > 3:
        raise AccessPolicyError(
            "SENSITIVE_FIELD_DENIED",
            "sensitive demographics are restricted to authorised aggregates",
        )
    counts = Counter(row.get(dimension) for row in rows or () if row.get(dimension) is not None)
    return {
        "dimension": dimension,
        "groups": tuple(sorted(
            (str(value), count) for value, count in counts.items()
        )),
        "row_count": sum(counts.values()),
        "aggregate_only": True,
        "citations": (),
    }
