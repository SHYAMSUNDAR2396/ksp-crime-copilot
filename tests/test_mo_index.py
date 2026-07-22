import sqlite3
from types import SimpleNamespace

from functions.crime_query import catalog, db as db_module
from functions.crime_query.mo_index import OperationalMoIndex, SqliteMoIndex


def test_index_excludes_source_and_orders_hits(tmp_path):
    path = tmp_path / "index.db"
    conn = sqlite3.connect(path); conn.executescript(catalog.sqlite_ddl()); conn.commit(); conn.close()
    db = db_module.SqliteDB(str(path))
    index = SqliteMoIndex(db)
    index.upsert([SimpleNamespace(case_id=1, crime_no="1" * 18, vector=[1.0, 0.0], provider="test", updated_at="now"),
                  SimpleNamespace(case_id=2, crime_no="2" * 18, vector=[0.9, 0.1], provider="test", updated_at="now")])
    hits = index.search([1.0, 0.0], [{"case_id": 1, "crime_no": "1" * 18, "vector": [1.0, 0.0]}, {"case_id": 2, "crime_no": "2" * 18, "vector": [0.9, 0.1]}], 10, 1)
    assert [hit.case_id for hit in hits] == [2]


def test_operational_index_updates_existing_case_record_by_rowid():
    class DB:
        def __init__(self):
            self.rows = [{"ROWID": "row-1", "CaseMasterID": 1}]
            self.updated = []
            self.inserted = []
        def read_operational(self, table, filters):
            return [row for row in self.rows if row["CaseMasterID"] == filters["CaseMasterID"]]
        def update_operational(self, table, row_id, row):
            self.updated.append((row_id, row))
        def insert_operational(self, table, row):
            self.inserted.append(row)

    db = DB()
    OperationalMoIndex(db).upsert([
        SimpleNamespace(case_id=1, crime_no="1" * 18, vector=[1.0, 0.0],
                        provider="test", updated_at="now")
    ])
    assert db.updated[0][0] == "row-1"
    assert db.inserted == []
