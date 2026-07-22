"""Two backends, one surface. SqliteDB for dev/test/eval, ZcqlDB for Catalyst.

The backend is chosen once, in main.py. Nothing here reads the environment.
"""
import sqlite3

try:
    from . import catalog
    from .rbac import Caller
except ImportError:
    import catalog
    from rbac import Caller


class DBError(Exception):
    """Raised when a query is refused or the backend fails."""


# Deliberately a substring match on the raw SQL text, not a parsed table
# reference: over-broad defense-in-depth that fails closed. Do not "fix" this
# into a precise AST check -- a precise check can be fooled by an alias or
# a table name it doesn't recognise; this can only ever over-reject.
def _reject_audit_table(sql):
    if catalog.AUDIT_TABLE.lower() in sql.lower():
        raise DBError(
            "{0} is not queryable through execute()".format(catalog.AUDIT_TABLE)
        )


class SqliteDB(object):
    """Local backend. Also used by the eval harness."""

    def __init__(self, path):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql):
        _reject_audit_table(sql)
        return self.execute_raw(sql)

    def execute_raw(self, sql, params=()):
        try:
            cursor = self._conn.execute(sql, params)
        except sqlite3.Error as err:
            raise DBError(str(err))
        return [dict(row) for row in cursor.fetchall()]

    def execute_write(self, sql, params=()):
        try:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor.lastrowid
        except sqlite3.Error as err:
            raise DBError(str(err))

    def units_in_district(self, district_id):
        rows = self.execute_raw(
            'SELECT UnitID FROM "Unit" WHERE DistrictID = ? ORDER BY UnitID',
            (district_id,),
        )
        return [row["UnitID"] for row in rows]

    def lookup(self, table, column):
        rows = self.execute_raw(
            'SELECT DISTINCT "{0}" AS v FROM "{1}" ORDER BY "{0}"'.format(column, table)
        )
        return [row["v"] for row in rows if row["v"] is not None]

    def caller_for(self, employee_id):
        # gen_data.py's _remap_foreign_keys_to_rowid rewrites Employee.RankID
        # to hold Rank's rowid, not its business RankID, so both backends'
        # join conditions agree (see ZcqlDB.caller_for below).
        rows = self.execute_raw(
            'SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, '
            'Rank.Hierarchy AS RankHierarchy '
            'FROM "Employee" JOIN "Rank" ON Employee.RankID = Rank.rowid '
            'WHERE Employee.EmployeeID = ?',
            (employee_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return Caller(
            employee_id=row["EmployeeID"],
            unit_id=row["UnitID"],
            district_id=row["DistrictID"],
            rank_hierarchy=row["RankHierarchy"],
        )

    def append_audit(self, **fields):
        columns = [c for c in catalog.AUDIT_COLUMNS if c != "AuditID"]
        values = [fields[c] for c in columns]
        placeholders = ",".join("?" for _ in columns)
        quoted = ",".join('"{0}"'.format(c) for c in columns)
        try:
            self._conn.execute(
                'INSERT INTO "{0}" ({1}) VALUES ({2})'.format(
                    catalog.AUDIT_TABLE, quoted, placeholders
                ),
                values,
            )
            self._conn.commit()
        except sqlite3.Error as err:
            raise DBError(str(err))

    def insert_operational(self, table, row):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        columns = list(row)
        quoted = ",".join('"{}"'.format(column) for column in columns)
        placeholders = ",".join("?" for _ in columns)
        return self.execute_write(
            'INSERT INTO "{}" ({}) VALUES ({})'.format(table, quoted, placeholders),
            tuple(row[column] for column in columns),
        )

    def update_operational(self, table, row_id, row):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        assignments = ",".join('"{}" = ?'.format(column) for column in row)
        values = tuple(row[column] for column in row) + (row_id,)
        return self.execute_write(
            'UPDATE "{}" SET {} WHERE ROWID = ?'.format(table, assignments),
            values,
        )

    def read_operational(self, table, filters=None):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        filters = filters or {}
        where = ""
        params = ()
        if filters:
            where = " WHERE " + " AND ".join(
                '"{}" = ?'.format(column) for column in filters
            )
            params = tuple(filters[column] for column in filters)
        return self.execute_raw('SELECT rowid AS ROWID, * FROM "{}"{}'.format(table, where), params)

    def close(self):
        self._conn.close()


class ZcqlDB(object):
    """Catalyst Data Store backend. Call signature confirmed in Task 2's findings."""

    def __init__(self, app):
        self._zcql = app.zcql()
        self._datastore = app.datastore()

    @staticmethod
    def _flatten(rows):
        """ZCQL returns rows keyed by table name; the rest of the code wants flat dicts."""
        flat = []
        for row in rows:
            merged = {}
            for value in row.values():
                merged.update(value)
            flat.append(merged)
        return flat

    def execute(self, sql):
        _reject_audit_table(sql)
        return self.execute_raw(sql)

    def execute_raw(self, sql):
        try:
            return self._flatten(self._zcql.execute_query(sql))
        except Exception as err:
            raise DBError(str(err))

    def units_in_district(self, district_id):
        # Unit.DistrictID is a Foreign Key column (see docs/CATALYST_RUNBOOK.md,
        # "Open gap: ZCQL relationships") and stores District's ROWID, not its
        # business DistrictID -- caller.district_id (from Employee.DistrictID,
        # never converted) is the business key, so join through District to
        # translate it. Comparing Unit.DistrictID against the raw business key
        # directly always returns zero rows, which used to produce an empty
        # `IN ()` predicate downstream -- invalid ZCQL syntax.
        rows = self.execute_raw(
            "SELECT Unit.UnitID FROM Unit "
            "JOIN District ON Unit.DistrictID = District.ROWID "
            "WHERE District.DistrictID = {0}".format(int(district_id))
        )
        # ZCQL returns UnitID as a string; sort numerically, not lexically
        # ("10" < "2"), and convert so the RBAC IN(...) predicate gets ints.
        return sorted(int(row["UnitID"]) for row in rows)

    def lookup(self, table, column):
        rows = self.execute_raw(
            "SELECT {0}.{1} FROM {0}".format(table, column)
        )
        values = {row[column] for row in rows if row.get(column) is not None}
        return sorted(values)

    def caller_for(self, employee_id):
        # ZCQL JOINs require a declared Foreign Key relationship, which
        # points at the parent table's internal ROWID -- not our business
        # key (Rank.RankID). Employee.RankID stores Rank's ROWID here too,
        # matching SqliteDB's join above (both remapped consistently).
        rows = self.execute_raw(
            "SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, "
            "Rank.Hierarchy FROM Employee "
            "LEFT JOIN Rank ON Employee.RankID = Rank.ROWID "
            "WHERE Employee.EmployeeID = {0}".format(int(employee_id))
        )
        if not rows:
            return None
        row = rows[0]
        # ZCQL returns every column as a string regardless of underlying
        # type; Caller's fields are typed int and rbac.py does numeric
        # comparisons (<=) on rank_hierarchy, so convert at this boundary.
        return Caller(
            employee_id=int(row["EmployeeID"]),
            unit_id=int(row["UnitID"]),
            district_id=int(row["DistrictID"]),
            rank_hierarchy=int(row["Hierarchy"]),
        )

    def append_audit(self, **fields):
        # Data Store row insert, not ZCQL: ZCQL is SELECT-only on Catalyst too.
        try:
            self._datastore.table(catalog.AUDIT_TABLE).insert_row(fields)
        except Exception as err:
            raise DBError("audit write failed: {0}".format(err))

    def insert_operational(self, table, row):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        try:
            result = self._datastore.table(table).insert_row(dict(row))
            if isinstance(result, dict):
                return result.get("ROWID")
            return result
        except Exception as err:
            raise DBError("operational insert failed: {0}".format(err))

    def update_operational(self, table, row_id, row):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        try:
            payload = dict(row)
            payload["ROWID"] = str(row_id)
            table_obj = self._datastore.table(table)
            try:
                return table_obj.update_row(payload)
            except TypeError:
                # Compatibility with an older local fake; Catalyst SDK 1.3.0
                # uses the single ROWID-bearing row form above.
                return table_obj.update_row(row_id, dict(row))
        except Exception as err:
            raise DBError("operational update failed: {0}".format(err))

    def read_operational(self, table, filters=None):
        if table not in catalog.OPERATIONAL_TABLES:
            raise DBError("operational table is not allowed")
        filters = filters or {}
        predicates = []
        for column, value in filters.items():
            if isinstance(value, (int, float)):
                predicates.append("{} = {}".format(column, value))
            else:
                escaped = str(value).replace("'", "''")
                predicates.append("{} = '{}'".format(column, escaped))
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        return self.execute_raw("SELECT ROWID, * FROM {}{}".format(table, where))

    def close(self):
        pass
