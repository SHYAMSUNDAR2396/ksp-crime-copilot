"""Two backends, one surface. SqliteDB for dev/test/eval, ZcqlDB for Catalyst.

The backend is chosen once, in main.py. Nothing here reads the environment.
"""
import sqlite3

from . import catalog
from .rbac import Caller


class DBError(Exception):
    """Raised when a query is refused or the backend fails."""


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
        rows = self.execute_raw(
            'SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, '
            'Rank.Hierarchy AS RankHierarchy '
            'FROM "Employee" JOIN "Rank" ON Employee.RankID = Rank.RankID '
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
        self._conn.execute(
            'INSERT INTO "{0}" ({1}) VALUES ({2})'.format(
                catalog.AUDIT_TABLE, quoted, placeholders
            ),
            values,
        )
        self._conn.commit()

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
        rows = self.execute_raw(
            "SELECT Unit.UnitID FROM Unit WHERE Unit.DistrictID = {0}".format(
                int(district_id)
            )
        )
        return sorted(row["UnitID"] for row in rows)

    def lookup(self, table, column):
        rows = self.execute_raw(
            "SELECT {0}.{1} FROM {0}".format(table, column)
        )
        values = {row[column] for row in rows if row.get(column) is not None}
        return sorted(values)

    def caller_for(self, employee_id):
        rows = self.execute_raw(
            "SELECT Employee.EmployeeID, Employee.UnitID, Employee.DistrictID, "
            "Rank.Hierarchy FROM Employee "
            "LEFT JOIN Rank ON Employee.RankID = Rank.RankID "
            "WHERE Employee.EmployeeID = {0}".format(int(employee_id))
        )
        if not rows:
            return None
        row = rows[0]
        return Caller(
            employee_id=row["EmployeeID"],
            unit_id=row["UnitID"],
            district_id=row["DistrictID"],
            rank_hierarchy=row["Hierarchy"],
        )

    def append_audit(self, **fields):
        # Data Store row insert, not ZCQL: ZCQL is SELECT-only on Catalyst too.
        try:
            self._datastore.table(catalog.AUDIT_TABLE).insert_row(fields)
        except Exception as err:
            raise DBError("audit write failed: {0}".format(err))

    def close(self):
        pass
