"""Fixed-query persistence for operational silent-match tables."""
import json


class SilentMatchRepository:
    def __init__(self, db):
        self.db = db

    def upsert_alert(self, score, anchor, candidate, run_id, now):
        first, second = sorted((int(anchor["CaseMasterID"]), int(candidate["CaseMasterID"])))
        existing = self.db.execute_raw(
            'SELECT * FROM "SilentMatchAlert" WHERE AlertType = ? AND AnchorCaseID = ? AND MatchedCaseID = ?',
            (score.alert_type, first, second),
        )
        evidence = json.dumps(dict(score.evidence), sort_keys=True)
        if existing:
            row = existing[0]
            self.append_action(row["AlertID"], "evidence_updated", evidence, 0, now)
            self.db.execute_write(
                'UPDATE "SilentMatchAlert" SET Score = ?, ConfidenceBand = ?, EvidenceJSON = ?, '
                'EvidenceSnapshotJSON = ?, SourceRunID = ?, UpdatedAt = ? WHERE AlertID = ?',
                (score.score, score.confidence_band, evidence, evidence, run_id, now, row["AlertID"]),
            )
            return self.get_alert(row["AlertID"])
        alert_id = self.db.execute_write(
            'INSERT INTO "SilentMatchAlert" '
            '(AlertType, AnchorCaseID, MatchedCaseID, AnchorCrimeNo, MatchedCrimeNo, Score, ConfidenceBand, Status, EvidenceJSON, EvidenceSnapshotJSON, SourceRunID, CreatedAt, UpdatedAt) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (score.alert_type, first, second, anchor["CrimeNo"], candidate["CrimeNo"], score.score,
             score.confidence_band, "New", evidence, evidence, run_id, now, now),
        )
        return self.get_alert(alert_id)

    def append_action(self, alert_id, action, note, employee_id, now):
        self.db.execute_write(
            'INSERT INTO "SilentMatchAction" (AlertID, Action, Note, EmployeeID, CreatedAt) VALUES (?, ?, ?, ?, ?)',
            (alert_id, action, note, employee_id, now),
        )
        if action in ("Seen", "Linked", "Dismissed"):
            current = self.get_alert(alert_id)
            if current and current["Status"] not in ("Linked", "Dismissed"):
                self.db.execute_write('UPDATE "SilentMatchAlert" SET Status = ?, UpdatedAt = ? WHERE AlertID = ?', (action, now, alert_id))
        return self.get_alert(alert_id)

    def list_alerts(self, status=None):
        if status is None:
            return self.db.execute_raw('SELECT * FROM "SilentMatchAlert" ORDER BY UpdatedAt DESC, AlertID DESC')
        return self.db.execute_raw('SELECT * FROM "SilentMatchAlert" WHERE Status = ? ORDER BY UpdatedAt DESC, AlertID DESC', (status,))

    def get_alert(self, alert_id):
        rows = self.db.execute_raw('SELECT * FROM "SilentMatchAlert" WHERE AlertID = ?', (alert_id,))
        return rows[0] if rows else None
