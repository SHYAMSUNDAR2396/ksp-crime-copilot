import datetime as dt
import sqlite3

from functions.crime_query import catalog, db as db_module
from functions.crime_query.silent_match_repository import SilentMatchRepository
from functions.crime_query.silent_match_scoring import score_candidate


def _case(case_id, name, unit):
    return {
        "CaseMasterID": case_id, "CrimeNo": str(case_id).zfill(18),
        "PoliceStationID": unit, "DistrictID": 1, "AccusedName": name,
        "AgeYear": 30, "GenderID": 1, "CrimeSubHeadID": 6,
        "SectionCodes": ("IPC:379",), "CrimeRegisteredDate": dt.date(2026, 6, 1),
        "latitude": 12.9716, "longitude": 77.5946,
    }


def test_repository_deduplicates_unordered_pairs_and_preserves_dispositions(tmp_path):
    path = tmp_path / "alerts.db"
    conn = sqlite3.connect(path)
    conn.executescript(catalog.sqlite_ddl())
    conn.commit(); conn.close()
    db = db_module.SqliteDB(str(path))
    repo = SilentMatchRepository(db)
    anchor, candidate = _case(1, "Ravi Kumar", 1), _case(2, "Ravi K", 2)
    score = score_candidate(anchor, candidate)
    first = repo.upsert_alert(score, anchor, candidate, "run-1", "2026-07-22T10:00:00Z")
    repo.append_action(first["AlertID"], "Linked", "confirmed by investigator", 9, "2026-07-22T10:01:00Z")
    second = repo.upsert_alert(score, candidate, anchor, "run-2", "2026-07-22T11:00:00Z")
    assert second["AlertID"] == first["AlertID"]
    assert repo.get_alert(first["AlertID"])["Status"] == "Linked"
    assert len(repo.list_alerts()) == 1
    assert len(db.execute_raw('SELECT * FROM "SilentMatchAction"')) == 2
    db.close()


def test_operational_tables_are_fixed_reads_not_nl_catalog():
    assert "SilentMatchAlert" in catalog.OPERATIONAL_TABLES
    assert "SilentMatchAlert" not in catalog.TABLES


def test_evidence_update_keeps_previous_snapshot_and_score(tmp_path):
    path = tmp_path / "history.db"
    conn = sqlite3.connect(path)
    conn.executescript(catalog.sqlite_ddl())
    conn.commit(); conn.close()
    db = db_module.SqliteDB(str(path))
    repo = SilentMatchRepository(db)
    anchor, candidate = _case(1, "Ravi Kumar", 1), _case(2, "Ravi K", 2)
    score = score_candidate(anchor, candidate)
    first = repo.upsert_alert(score, anchor, candidate, "run-1", "now")
    repo.upsert_alert(score, candidate, anchor, "run-2", "later")
    action = db.execute_raw('SELECT * FROM "SilentMatchAction" ORDER BY ActionID DESC')[0]
    assert action["ActionType"] == "evidence_updated"
    assert action["PreviousScore"] == first["Score"]
    assert action["PreviousConfidenceBand"] == first["ConfidenceBand"]
    assert action["EvidenceSnapshotJSON"]


def test_run_and_recipient_records_are_idempotent(tmp_path):
    path = tmp_path / "runs.db"
    conn = sqlite3.connect(path)
    conn.executescript(catalog.sqlite_ddl())
    conn.commit(); conn.close()
    db = db_module.SqliteDB(str(path))
    repo = SilentMatchRepository(db)
    repo.create_run("run-1", "live", "start")
    repo.ensure_recipient(3, 9)
    repo.ensure_recipient(3, 9)
    assert len(db.execute_raw('SELECT * FROM "SilentMatchRecipient"')) == 1
