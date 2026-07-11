"""Parse-and-reject validator for LLM-generated SQL.

Never repairs, never rewrites for correctness, never string-matches. Anything
outside the allowlist raises ValidationError whose message is designed to be
fed straight back to the model as a re-prompt hint.
"""
import sqlglot
from sqlglot import exp

try:
    from . import catalog
except ImportError:
    import catalog

MAX_LIMIT = 200

# Node types that are banned wherever they appear inside an otherwise-valid
# SELECT tree (e.g. a subquery hiding in a WHERE clause).
_BANNED_NODES = (
    (exp.Subquery, "subqueries are not allowed"),
    (exp.With, "common table expressions are not allowed"),
    (exp.Window, "window functions are not allowed"),
    # exp.Interval is not an exp.Func subclass, so _check_functions's
    # find_all(exp.Func) never sees it -- it needs its own ban here or date
    # arithmetic like `col + INTERVAL '30' DAY` sails through unnoticed.
    (exp.Interval, "date arithmetic is not allowed; compare against literal 'YYYY-MM-DD' strings"),
)

# Node types that sqlglot parses as the *root* statement rather than as a
# child of a Select (UNION/EXCEPT/INTERSECT combine two SELECTs, so the root
# is the set-operation node, not exp.Select).
_ROOT_REJECT = (
    (exp.Union, "UNION is not allowed"),
    (exp.Except, "EXCEPT is not allowed"),
    (exp.Intersect, "INTERSECT is not allowed"),
)

_ALLOWED_FUNC_TYPES = (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)

# In sqlglot 26.x, boolean connectors are modeled as Func subclasses
# (`class And(Connector, Func)`, likewise Or and Xor), so find_all(exp.Func)
# in _check_functions sees them too. AND/OR are portable to ZCQL and must be
# allowed; XOR is not portable and must stay rejected. Named explicitly here
# (rather than "issubclass(node, exp.Connector)") so a future sqlglot
# release that reclassifies more nodes as Connector/Func doesn't silently
# widen this allowlist -- that would need a deliberate re-check of this set.
_ALLOWED_CONNECTOR_TYPES = (exp.And, exp.Or)


class ValidationError(Exception):
    """Raised when generated SQL leaves the allowlist. Message is a re-prompt hint."""


def _parse(sql):
    try:
        statements = sqlglot.parse(sql)
    except Exception as err:  # sqlglot raises several unrelated types
        raise ValidationError(
            "could not parse SQL (only SELECT statements are allowed): {0}".format(err)
        )
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise ValidationError(
            "exactly one statement is allowed; got {0}".format(len(statements))
        )
    root = statements[0]
    # UNION/EXCEPT/INTERSECT parse with the set-operation node at the root,
    # not as a child of exp.Select, so they need their own check here rather
    # than in _check_banned (which only ever sees a validated exp.Select).
    for node_type, message in _ROOT_REJECT:
        if isinstance(root, node_type):
            raise ValidationError(message)
    if not isinstance(root, exp.Select):
        raise ValidationError(
            "only SELECT statements are allowed; got {0}".format(type(root).__name__.upper())
        )
    return root


def table_aliases(select):
    """Map every alias-or-name used in the query to its real catalog table name."""
    mapping = {}
    for table in select.find_all(exp.Table):
        mapping[table.alias_or_name] = table.name
    return mapping


def _check_banned(select):
    for node_type, message in _BANNED_NODES:
        if select.find(node_type) is not None:
            raise ValidationError(message)
    # WITH sometimes hangs off args["with"] rather than under a traversal
    # find() reaches - belt and braces.
    if select.args.get("with") is not None:
        raise ValidationError("common table expressions are not allowed")


def _check_tables(select):
    for table in select.find_all(exp.Table):
        if table.name not in catalog.TABLES:
            raise ValidationError("unknown table: {0}".format(table.name))


def _projection_aliases(select):
    return {e.alias for e in select.expressions if e.alias}


def _check_columns(select, aliases):
    order_aliases = _projection_aliases(select)
    for column in select.find_all(exp.Column):
        if not column.table:
            # A bare name in ORDER BY that matches a SELECT-list alias is a
            # reference to an already-validated projection, not an invented
            # column - this is standard SQL and sqlglot represents it as an
            # unqualified Column node under the Order clause.
            if column.name in order_aliases and column.find_ancestor(exp.Order) is not None:
                continue
            raise ValidationError(
                "column {0} must be qualified with its table name".format(column.name)
            )
        if column.table not in aliases:
            raise ValidationError(
                "unknown table alias: {0}".format(column.table)
            )
        table = aliases[column.table]
        if column.name not in catalog.TABLES[table]:
            raise ValidationError(
                "unknown column: {0}.{1}".format(table, column.name)
            )


def _check_functions(select):
    for node in select.find_all(exp.Func):
        if isinstance(node, _ALLOWED_FUNC_TYPES):
            continue
        if isinstance(node, _ALLOWED_CONNECTOR_TYPES):
            continue
        # For exp.Anonymous nodes, sql_name() returns "ANONYMOUS"; use node.this instead
        if isinstance(node, exp.Anonymous):
            name = node.this
        else:
            name = node.sql_name() if hasattr(node, "sql_name") else type(node).__name__.upper()
        raise ValidationError(
            "function not allowed: {0}; permitted functions are {1}".format(
                name, ", ".join(sorted(catalog.ALLOWED_FUNCTIONS))
            )
        )


def _check_joins(select, aliases):
    # A later task injects a role-scoping predicate onto the single
    # CaseMaster reference. Comma joins / CROSS JOIN and self-joins both
    # defeat that: the first leaves a second table unscoped, the second
    # leaves a second CaseMaster alias unscoped.
    for join in select.args.get("joins") or []:
        if join.args.get("on") is None:
            raise ValidationError(
                "cross joins are not allowed; every JOIN needs an ON condition"
            )
    # Only case-scoped tables (those with case-specific rows) can appear once.
    # Other tables like Employee can be joined multiple times under different
    # aliases without ambiguity in the RBAC scoping.
    seen_tables = set()
    for real_table in aliases.values():
        if real_table in catalog.CASE_SCOPED_TABLES and real_table in seen_tables:
            raise ValidationError(
                "table {0} may only appear once in a query".format(real_table)
            )
        seen_tables.add(real_table)


def _check_anchor(select, aliases):
    used = set(aliases.values())
    if used & catalog.CASE_SCOPED_TABLES and "CaseMaster" not in used:
        raise ValidationError(
            "queries touching case data must include CaseMaster so the result "
            "can be role-scoped; join back to CaseMaster on CaseMasterID"
        )


def _is_aggregate(select):
    if select.args.get("group"):
        return True
    return any(isinstance(node, _ALLOWED_FUNC_TYPES) for node in select.find_all(exp.Func))


def _identifying_projection(select, aliases):
    """First projected column that is a person name or a case narrative, or None.

    Grouping/aggregating by a person's name or by BriefFacts still yields
    identifiable, uncitable rows, so this is checked independently of
    _is_aggregate.
    """
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            if column.table in aliases:
                dotted = "{0}.{1}".format(aliases[column.table], column.name)
                if dotted in catalog.IDENTIFYING_COLUMNS:
                    return dotted
    return None


def _check_citation(select, aliases):
    identifying = _identifying_projection(select, aliases)
    if _is_aggregate(select) and identifying is None:
        return
    used = set(aliases.values())
    if not (used & catalog.CASE_SCOPED_TABLES):
        # Pure lookup query (e.g. SELECT District.DistrictName FROM District)
        # touches no case, so there is nothing to cite.
        return
    for projection in select.expressions:
        for column in projection.find_all(exp.Column):
            if column.table in aliases and aliases[column.table] == "CaseMaster" \
                    and column.name == "CrimeNo":
                return
    if identifying is not None:
        raise ValidationError(
            "query projects {0}, which identifies a person or reproduces case "
            "narrative text; it must also select CaseMaster.CrimeNo so the "
            "answer can be cited".format(identifying)
        )
    raise ValidationError(
        "every row-level query must select CaseMaster.CrimeNo so the answer can be cited"
    )


def _enforce_limit(select):
    limit = select.args.get("limit")
    if limit is None:
        return select.limit(MAX_LIMIT)
    expr = limit.expression
    # Must be a bare non-string numeric literal. Anything else (Neg for a
    # negative literal, Add/arithmetic, a subquery, ...) has a `.name` that
    # silently reflects only part of the expression - e.g. `Neg(Literal(1))`
    # (i.e. "LIMIT -1") reports name "1", which would let an unbounded
    # LIMIT -1 slip through unclamped. Reject anything that isn't a plain
    # literal instead of trusting a partial read of it.
    if not isinstance(expr, exp.Literal) or expr.is_string:
        raise ValidationError("LIMIT must be a plain integer literal")
    try:
        value = int(expr.this)
    except (AttributeError, ValueError):
        raise ValidationError("LIMIT must be a plain integer literal")
    if value < 1 or value > MAX_LIMIT:
        return select.limit(MAX_LIMIT)
    return select


def validate(sql):
    """Return the parsed SELECT with LIMIT enforced, or raise ValidationError."""
    select = _parse(sql)
    _check_banned(select)
    _check_tables(select)
    aliases = table_aliases(select)
    _check_joins(select, aliases)
    _check_columns(select, aliases)
    _check_functions(select)
    _check_anchor(select, aliases)
    _check_citation(select, aliases)
    return _enforce_limit(select)
