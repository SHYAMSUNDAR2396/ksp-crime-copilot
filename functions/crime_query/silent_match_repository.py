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
        cases_by_id = {
            int(anchor["CaseMasterID"]): anchor,
            int(candidate["CaseMasterID"]): candidate,
        }
        first_case = cases_by_id[first]
        second_case = cases_by_id[second]
        existing = self._read(
            "SilentMatchAlert",
            {"AlertType": score.alert_type, "AnchorCaseID": first, "MatchedCaseID": second},
            'SELECT * FROM "SilentMatchAlert" WHERE AlertType = ? AND AnchorCaseID = ? AND MatchedCaseID = ?',
            (score.alert_type, first, second),
        )
        evidence = json.dumps(dict(score.evidence), sort_keys=True)
        if existing:
            row = existing[0]
            index_version = score.index_version or row.get("IndexVersion", "")
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
                 "SourceRunID": run_id, "IndexVersion": index_version,
                 "UpdatedAt": now},
                'UPDATE "SilentMatchAlert" SET Score = ?, ConfidenceBand = ?, EvidenceJSON = ?, '
                'EvidenceSnapshotJSON = ?, SourceRunID = ?, IndexVersion = ?, '
                'UpdatedAt = ? WHERE AlertID = ?',
                (score.score, score.confidence_band, evidence, evidence, run_id,
                 index_version, now, row["AlertID"]),
            )
            return self.get_alert(row["AlertID"])
        alert_id = self._insert(
            "SilentMatchAlert",
            {"AlertType": score.alert_type, "AnchorCaseID": first, "MatchedCaseID": second,
             "AnchorCrimeNo": first_case["CrimeNo"], "MatchedCrimeNo": second_case["CrimeNo"],
             "Score": score.score, "ConfidenceBand": score.confidence_band, "Status": "New",
             "EvidenceJSON": evidence, "EvidenceSnapshotJSON": evidence,
             "SourceRunID": run_id, "IndexVersion": score.index_version,
             "CreatedAt": now, "UpdatedAt": now},
            'INSERT INTO "SilentMatchAlert" '
            '(AlertType, AnchorCaseID, MatchedCaseID, AnchorCrimeNo, MatchedCrimeNo, Score, ConfidenceBand, Status, EvidenceJSON, EvidenceSnapshotJSON, SourceRunID, IndexVersion, CreatedAt, UpdatedAt) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (score.alert_type, first, second, first_case["CrimeNo"], second_case["CrimeNo"], score.score,
             score.confidence_band, "New", evidence, evidence, run_id,
             score.index_version, now, now),
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
        if action in ("review", "Seen", "Linked", "Dismissed"):
            current = self.get_alert(alert_id)
            if current and current["Status"] not in ("Linked", "Dismissed"):
                status = "Reviewing" if action == "review" else action
                self._update(
                    "SilentMatchAlert", alert_id,
                    {"Status": status, "UpdatedAt": now},
                    'UPDATE "SilentMatchAlert" SET Status = ?, UpdatedAt = ? WHERE AlertID = ?',
                    (status, now, alert_id),
                )
        return self.get_alert(alert_id)

    def ensure_recipient(self, alert_id, employee_id):
        rows = self._read("SilentMatchRecipient",
                          {"AlertID": alert_id, "EmployeeID": employee_id})
        if rows:
            return rows[0]
        recipient_id = self._insert(
            "SilentMatchRecipient",
            {"AlertID": alert_id, "EmployeeID": employee_id},
            'INSERT INTO "SilentMatchRecipient" (AlertID, EmployeeID) VALUES (?, ?)',
            (alert_id, employee_id),
        )
        rows = self._read("SilentMatchRecipient", {"ROWID": recipient_id})
        return rows[0] if rows else {"RecipientID": recipient_id, "AlertID": alert_id,
                                     "EmployeeID": employee_id}

    def create_run(self, run_id, trigger_source, started_at):
        return self._insert(
            "SilentMatchRun",
            {"RunID": run_id, "TriggerSource": trigger_source, "Status": "running",
             "StartedAt": started_at},
            'INSERT INTO "SilentMatchRun" (RunID, TriggerSource, Status, StartedAt) VALUES (?, ?, ?, ?)',
            (run_id, trigger_source, "running", started_at),
        )

    def finish_run(self, run_id, result, finished_at):
        rows = self._read("SilentMatchRun", {"RunID": run_id})
        row_id = rows[0].get("ROWID", run_id) if rows else run_id
        self._update(
            "SilentMatchRun", row_id,
            {"Status": "failed" if result.failures else "completed",
             "AnchorsSeen": result.anchors_seen,
             "CandidatesSeen": result.candidates_seen,
             "AlertsCreated": result.alerts_created,
             "FinishedAt": finished_at},
            'UPDATE "SilentMatchRun" SET Status = ?, AnchorsSeen = ?, CandidatesSeen = ?, '
            'AlertsCreated = ?, FinishedAt = ? WHERE RunID = ?',
            ("failed" if result.failures else "completed", result.anchors_seen,
             result.candidates_seen, result.alerts_created, finished_at, run_id),
        )

    def list_alerts(self, status=None):
        if status is None:
            return self._read("SilentMatchAlert", {})
        return self._read("SilentMatchAlert", {"Status": status})

    def get_alert(self, alert_id):
        rows = self._read("SilentMatchAlert", {"ROWID": alert_id})
        return rows[0] if rows else None

    def recipients_for(self, alert_id):
        return self._read("SilentMatchRecipient", {"AlertID": int(alert_id)})

    def actions_for(self, alert_id):
        return self._read("SilentMatchAction", {"AlertID": int(alert_id)})
