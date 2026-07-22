"""Fixed-query persistence for operational silent-match tables."""
import json


class SilentMatchRepository:
    def __init__(self, db):
        self.db = db

    def _read(self, table, filters=None, fallback_sql=None, params=()):
        if hasattr(self.db, "read_operational"):
            return self.db.read_operational(table, filters or {})
        return self.db.execute_raw(fallback_sql, params)

    def _insert(self, table, row, fallback_sql, params):
        if hasattr(self.db, "insert_operational"):
            return self.db.insert_operational(table, row)
        return self.db.execute_write(fallback_sql, params)

    def _update(self, table, row_id, row, fallback_sql, params):
        if hasattr(self.db, "update_operational"):
            return self.db.update_operational(table, row_id, row)
        return self.db.execute_write(fallback_sql, params)

    def upsert_alert(self, score, anchor, candidate, run_id, now):
        first, second = sorted((int(anchor["CaseMasterID"]), int(candidate["CaseMasterID"])))
        existing = self._read(
            "SilentMatchAlert",
            {"AlertType": score.alert_type, "AnchorCaseID": first, "MatchedCaseID": second},
            'SELECT * FROM "SilentMatchAlert" WHERE AlertType = ? AND AnchorCaseID = ? AND MatchedCaseID = ?',
            (score.alert_type, first, second),
        )
        evidence = json.dumps(dict(score.evidence), sort_keys=True)
        if existing:
            row = existing[0]
            self.append_action(
                row["AlertID"], "evidence_updated", "evidence re-evaluated", 0, now,
                previous_score=row["Score"],
                previous_band=row["ConfidenceBand"],
                evidence_snapshot=row.get("EvidenceSnapshotJSON", "{}"),
            )
            self._update(
                "SilentMatchAlert", row["AlertID"],
                {"Score": score.score, "ConfidenceBand": score.confidence_band,
                 "EvidenceJSON": evidence, "EvidenceSnapshotJSON": evidence,
                 "SourceRunID": run_id, "UpdatedAt": now},
                'UPDATE "SilentMatchAlert" SET Score = ?, ConfidenceBand = ?, EvidenceJSON = ?, '
                'EvidenceSnapshotJSON = ?, SourceRunID = ?, UpdatedAt = ? WHERE AlertID = ?',
                (score.score, score.confidence_band, evidence, evidence, run_id, now, row["AlertID"]),
            )
            return self.get_alert(row["AlertID"])
        alert_id = self._insert(
            "SilentMatchAlert",
            {"AlertType": score.alert_type, "AnchorCaseID": first, "MatchedCaseID": second,
             "AnchorCrimeNo": anchor["CrimeNo"], "MatchedCrimeNo": candidate["CrimeNo"],
             "Score": score.score, "ConfidenceBand": score.confidence_band, "Status": "New",
             "EvidenceJSON": evidence, "EvidenceSnapshotJSON": evidence,
             "SourceRunID": run_id, "CreatedAt": now, "UpdatedAt": now},
            'INSERT INTO "SilentMatchAlert" '
            '(AlertType, AnchorCaseID, MatchedCaseID, AnchorCrimeNo, MatchedCrimeNo, Score, ConfidenceBand, Status, EvidenceJSON, EvidenceSnapshotJSON, SourceRunID, CreatedAt, UpdatedAt) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (score.alert_type, first, second, anchor["CrimeNo"], candidate["CrimeNo"], score.score,
             score.confidence_band, "New", evidence, evidence, run_id, now, now),
        )
        return self.get_alert(alert_id)

    def append_action(self, alert_id, action, note, employee_id, now,
                      previous_score=None, previous_band=None,
                      evidence_snapshot="{}"):
        self._insert(
            "SilentMatchAction",
            {"AlertID": alert_id, "ActionType": action, "Note": note,
             "EmployeeID": employee_id, "CreatedAt": now,
             "PreviousScore": previous_score,
             "PreviousConfidenceBand": previous_band,
             "EvidenceSnapshotJSON": evidence_snapshot},
            'INSERT INTO "SilentMatchAction" '
            '(AlertID, ActionType, Note, EmployeeID, CreatedAt, PreviousScore, '
            'PreviousConfidenceBand, EvidenceSnapshotJSON) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (alert_id, action, note, employee_id, now, previous_score,
             previous_band, evidence_snapshot),
        )
        if action in ("Seen", "Linked", "Dismissed"):
            current = self.get_alert(alert_id)
            if current and current["Status"] not in ("Linked", "Dismissed"):
                self._update(
                    "SilentMatchAlert", alert_id,
                    {"Status": action, "UpdatedAt": now},
                    'UPDATE "SilentMatchAlert" SET Status = ?, UpdatedAt = ? WHERE AlertID = ?',
                    (action, now, alert_id),
                )
        return self.get_alert(alert_id)

    def list_alerts(self, status=None):
        if status is None:
            return self._read("SilentMatchAlert", {})
        return self._read("SilentMatchAlert", {"Status": status})

    def get_alert(self, alert_id):
        rows = self._read("SilentMatchAlert", {"AlertID": alert_id})
        return rows[0] if rows else None
