"""Shared, replayable orchestration for live and batch silent-match scans."""
import datetime as dt
import uuid

try:
    from .silent_match_models import ScanResult
    from .silent_match_scoring import score_candidate
except ImportError:  # pragma: no cover
    from silent_match_models import ScanResult
    from silent_match_scoring import score_candidate


class SilentMatchScanner:
    """Coordinate matching without coupling the scan to a storage implementation.

    ``loader`` exposes ``load(anchor_case_id=None, date_window=None)`` and
    returns ``(anchor_cases, candidate_cases)``.  The repository only needs
    ``upsert_alert`` and may optionally expose ``list_alerts``.
    """

    def __init__(self, loader, matcher, repository, caller=None, clock=None):
        self.loader = loader
        self.matcher = matcher
        self.repository = repository
        self.caller = caller
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    def scan(self, date_window=None, anchor_case_id=None, trigger_source="batch"):
        if (date_window is None) == (anchor_case_id is None):
            raise ValueError("provide exactly one of date_window or anchor_case_id")
        if trigger_source not in ("batch", "live"):
            raise ValueError("unsupported trigger source")
        run_id = uuid.uuid4().hex
        anchors, candidates = self.loader.load(
            anchor_case_id=anchor_case_id, date_window=date_window,
        )
        anchors, candidates = list(anchors or ()), list(candidates or ())
        alerts, failures, skipped = [], [], []
        created = updated = 0
        seen = set()
        for anchor in anchors:
            if trigger_source == "live" and not anchor.get("completed", True):
                skipped.append({"case_id": anchor.get("CaseMasterID"), "reason": "pending_enrichment"})
                continue
            try:
                semantic = self.matcher.similar_cases(
                    anchor, candidates, self.caller, limit=max(10, len(candidates)),
                )
            except Exception as exc:
                failures.append("semantic retrieval failed")
                semantic = ()
            by_case = {int(item.matched_case_id): item for item in semantic}
            for candidate in candidates:
                if int(candidate.get("CaseMasterID")) == int(anchor.get("CaseMasterID")):
                    continue
                pair = (min(int(anchor["CaseMasterID"]), int(candidate["CaseMasterID"])),
                        max(int(anchor["CaseMasterID"]), int(candidate["CaseMasterID"])))
                if pair in seen:
                    continue
                seen.add(pair)
                result = score_candidate(anchor, candidate, by_case.get(int(candidate["CaseMasterID"])))
                if not result.persistable:
                    continue
                before = self._existing(result.alert_type, pair)
                alert = self.repository.upsert_alert(
                    result, anchor, candidate, run_id, self.clock(),
                )
                alerts.append(alert)
                if before:
                    updated += 1
                else:
                    created += 1
        return ScanResult(
            run_id=run_id, trigger_source=trigger_source,
            anchors_seen=len(anchors), candidates_seen=len(candidates),
            alerts=tuple(alerts), alerts_created=created, alerts_updated=updated,
            skipped_cases=tuple(skipped), failures=tuple(failures),
        )

    def _existing(self, alert_type, pair):
        for row in getattr(self.repository, "list_alerts", lambda: ())():
            if row.get("AlertType") == alert_type and {
                int(row.get("AnchorCaseID")), int(row.get("MatchedCaseID"))
            } == set(pair):
                return row
        return None
