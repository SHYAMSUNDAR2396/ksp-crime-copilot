"""Role scoping and DPDP masking, applied to a validated AST.

Scope is a PoliceStationID IN (...) predicate ANDed onto the query. Sensitive
columns are rejected outside the projection and masked inside it, unless the
caller is senior enough and the query is an aggregate.
"""
from dataclasses import dataclass

from sqlglot import exp

try:
    from . import catalog
    from .validate import table_aliases
except ImportError:
    import catalog
    from validate import table_aliases

STATEWIDE_MAX_HIERARCHY = 2   # DGP, IGP
DISTRICT_MAX_HIERARCHY = 4    # SP, Inspector
SENSITIVE_MAX_HIERARCHY = 3   # SP and above
MASK = "[MASKED]"


class RbacError(Exception):
    """Raised when the caller may not run this query at all."""


@dataclass(frozen=True)
class Caller:
    employee_id: int
    unit_id: int
    district_id: int
    rank_hierarchy: int  # lower number = higher authority


def allowed_units(caller, db):
    """Station IDs the caller may see. None means statewide."""
    if caller.rank_hierarchy <= STATEWIDE_MAX_HIERARCHY:
        return None
    if caller.rank_hierarchy <= DISTRICT_MAX_HIERARCHY:
        business_units = db.units_in_district(caller.district_id)
    else:
        business_units = [caller.unit_id]
    # Catalyst FK columns store parent ROWIDs. Fixed application views expose
    # business identifiers, but the generated CaseMaster scope predicate is
    # applied to CaseMaster.PoliceStationID itself, so translate here.
    mapper = getattr(db, "unit_rowids_for_business_ids", None)
    return mapper(business_units) if mapper is not None else business_units


def _projection_column_nodes(select):
    nodes = set()
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            nodes.add(id(column))
    return nodes


def _group_column_nodes(select):
    group = select.args.get("group")
    if group is None:
        return set()
    return {id(column) for column in group.find_all(exp.Column)}


def _dotted(column, aliases):
    # sqlglot represents a validated SELECT-list alias in ORDER BY as an
    # unqualified Column (for example ``ORDER BY n``). It is not a source
    # table field and therefore cannot be a sensitive column reference. Keep
    # it as its bare name so the masking walk remains total instead of
    # raising KeyError after validation has already accepted the query.
    if not column.table:
        return column.name
    return "{0}.{1}".format(aliases[column.table], column.name)


def _output_key(projection):
    """The dict key a row will carry for this projection."""
    if isinstance(projection, exp.Alias):
        return projection.alias
    return projection.name


def _group_by_is_safe_aggregate(select, aliases):
    """True iff every GROUP BY key is sensitive itself or a lookup/dimension
    column (a table outside catalog.CASE_SCOPED_TABLES).

    Caste/religion may be seen in the clear only when the grouping is a
    genuine demographic aggregate (by caste, by religion, by district, by
    crime type). A case-scoped, non-sensitive key (CrimeNo, AgeYear,
    AccusedName, ...) makes each group a single case or person -- a
    row-in-disguise, not an aggregate -- so it must never grant passthrough.
    """
    group = select.args.get("group")
    if group is None:
        return False
    for column in group.find_all(exp.Column):
        if _dotted(column, aliases) in catalog.SENSITIVE_COLUMNS:
            continue
        table = aliases.get(column.table)
        if table is not None and table not in catalog.CASE_SCOPED_TABLES:
            continue
        return False
    return True


def _reject_function_wrapped_sensitive_columns(select, aliases):
    """A sensitive column nested inside any function (MIN/MAX/SUM/AVG/...) in
    the projection is never a legitimate disclosure -- MIN/MAX/SUM/AVG over a
    caste id leaks the value, and sqlite names the output column after the
    expression text (e.g. "MIN(ComplainantDetails.CasteID)"), not an alias we
    could redact by. Reject outright, for every rank including DGP -- there
    is no rank check here on purpose.
    """
    for projection in select.expressions:
        target = projection.this if isinstance(projection, exp.Alias) else projection
        if isinstance(target, exp.Column):
            continue  # bare (optionally aliased) column -- permitted
        for column in target.find_all(exp.Column):
            dotted = _dotted(column, aliases)
            if dotted in catalog.SENSITIVE_COLUMNS:
                raise RbacError(
                    "{0} may not be wrapped in a function or expression; "
                    "only a bare (optionally aliased) column may be "
                    "selected".format(dotted)
                )


def _group_by_dotted_keys(select, aliases):
    """Dotted RealTable.Column names of every GROUP BY key, for comparing
    against a projection column by identity of what it refers to (the
    projection node and the GROUP BY node are different AST objects even
    when they name the same column)."""
    group = select.args.get("group")
    if group is None:
        return frozenset()
    return frozenset(_dotted(column, aliases) for column in group.find_all(exp.Column))


def _sensitive_policy(select, caller, aliases):
    """Return the list of output keys to redact, or raise RbacError."""
    _reject_function_wrapped_sensitive_columns(select, aliases)

    projection_nodes = _projection_column_nodes(select)
    group_nodes = _group_column_nodes(select)
    senior = caller.rank_hierarchy <= SENSITIVE_MAX_HIERARCHY
    # Shape check only: senior caller AND every GROUP BY key is sensitive-or-
    # lookup. This does NOT by itself clear any column -- it only says the
    # query *could* contain a legitimate demographic aggregate. Leak C: a
    # safe_aggregate shape used to exempt the whole projection, so a second
    # sensitive column riding along in SELECT but absent from GROUP BY (not
    # aggregated, not grouped) leaked one arbitrary row's value in the clear.
    # Per-column exemption below is what actually decides passthrough.
    safe_aggregate = senior and _group_by_is_safe_aggregate(select, aliases)
    group_dotted = _group_by_dotted_keys(select, aliases)

    for column in select.find_all(exp.Column):
        if _dotted(column, aliases) not in catalog.SENSITIVE_COLUMNS:
            continue
        if id(column) in projection_nodes:
            continue
        if id(column) in group_nodes:
            # A senior caller (SP/DGP) may always GROUP BY a sensitive
            # column; the per-column exemption below decides whether the
            # value leaks in the clear or gets redacted. A junior caller may
            # never use caste/religion to group at all -- GROUP BY
            # row-ordering would otherwise let them recover masked values by
            # position (see task-5-report.md).
            if senior:
                continue
            raise RbacError(
                "caste and religion may only appear in the selected columns of an "
                "aggregate query; {0} was used to filter or sort".format(
                    _dotted(column, aliases)
                )
            )
        # WHERE / JOIN ON / ORDER BY / HAVING -- rejected for everyone.
        raise RbacError(
            "caste and religion may only appear in the selected columns of an "
            "aggregate query; {0} was used to filter or sort".format(
                _dotted(column, aliases)
            )
        )

    redact = []
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            dotted = _dotted(column, aliases)
            if dotted not in catalog.SENSITIVE_COLUMNS:
                continue
            # Per-column exemption (Leak C fix): this specific sensitive
            # column is clear only if the query-wide shape is safe AND this
            # column is itself one of the GROUP BY keys -- i.e. it is the
            # aggregate dimension, not a passenger riding along in the
            # projection. A sensitive column outside the GROUP BY is never
            # part of the aggregate, however senior the caller or however
            # safe the rest of the grouping is -- it must be redacted.
            exempt = safe_aggregate and dotted in group_dotted
            if not exempt:
                redact.append(_output_key(projection))
            break
    return redact


def _casemaster_alias(aliases):
    for alias, table in aliases.items():
        if table == "CaseMaster":
            return alias
    return None


def apply(select, caller, units):
    """Rewrite the validated AST for this caller. Returns (sql_text, redact_keys)."""
    aliases = table_aliases(select)
    redact = _sensitive_policy(select, caller, aliases)

    scoped = select
    alias = _casemaster_alias(aliases)
    if alias is not None and units is not None:
        literals = [exp.Literal.number(unit) for unit in units]
        predicate = exp.In(
            this=exp.column("PoliceStationID", table=alias),
            expressions=literals,
        )
        # Select.where() routes through exp.and_, which parenthesises a bare OR
        # on the left. That parenthesisation is the authorisation boundary.
        # Empirically verified against sqlglot 26.33.0 (see task-5-report.md):
        # `WHERE a OR b` + this predicate produces `WHERE (a OR b) AND scope`.
        scoped = select.where(predicate, copy=True)

    return scoped.sql(), redact


def redact_rows(rows, redact_keys):
    """Replace the value of every redacted key. Does not mutate the input."""
    if not redact_keys:
        return rows
    masked = []
    for row in rows:
        copy = dict(row)
        for key in redact_keys:
            if key in copy:
                copy[key] = MASK
        masked.append(copy)
    return masked
