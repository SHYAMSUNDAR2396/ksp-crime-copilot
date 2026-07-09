"""Role scoping and DPDP masking, applied to a validated AST.

Scope is a PoliceStationID IN (...) predicate ANDed onto the query. Sensitive
columns are rejected outside the projection and masked inside it, unless the
caller is senior enough and the query is an aggregate.
"""
from dataclasses import dataclass

from sqlglot import exp

from . import catalog
from .validate import table_aliases

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
        return db.units_in_district(caller.district_id)
    return [caller.unit_id]


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
    return "{0}.{1}".format(aliases[column.table], column.name)


def _output_key(projection):
    """The dict key a row will carry for this projection."""
    if isinstance(projection, exp.Alias):
        return projection.alias
    return projection.name


def _sensitive_policy(select, caller, aliases):
    """Return the list of output keys to redact, or raise RbacError."""
    projection_nodes = _projection_column_nodes(select)
    group_nodes = _group_column_nodes(select)
    is_grouped = select.args.get("group") is not None
    authorised = caller.rank_hierarchy <= SENSITIVE_MAX_HIERARCHY and is_grouped

    for column in select.find_all(exp.Column):
        if _dotted(column, aliases) not in catalog.SENSITIVE_COLUMNS:
            continue
        if id(column) in projection_nodes:
            continue
        if id(column) in group_nodes:
            continue
        raise RbacError(
            "caste and religion may only appear in the selected columns of an "
            "aggregate query; {0} was used to filter or sort".format(
                _dotted(column, aliases)
            )
        )

    if authorised:
        return []

    redact = []
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            if _dotted(column, aliases) in catalog.SENSITIVE_COLUMNS:
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
