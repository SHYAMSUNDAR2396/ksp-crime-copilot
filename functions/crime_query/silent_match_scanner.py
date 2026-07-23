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

    def __init__(self, loader, matcher, repository, caller=None, clock=None,
                 recipient_router=None, pair_authorizer=None,
                 recipient_retry_attempts=2):
        self.loader = loader
        self.matcher = matcher
        self.repository = repository
        self.caller = caller
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())
        self.recipient_router = recipient_router or (lambda anchor, candidate: ())
        self.pair_authorizer = pair_authorizer or (lambda anchor, candidate: True)
        try:
            self.recipient_retry_attempts = int(recipient_retry_attempts)
        except (TypeError, ValueError):
            raise ValueError("recipient retry attempts must be an integer")
        if self.recipient_retry_attempts < 1:
            raise ValueError("recipient retry attempts must be positive")

    def scan(self, date_window=None, anchor_case_id=None, trigger_source="batch"):
        if (date_window is None) == (anchor_case_id is None):
            raise ValueError("provide exactly one of date_window or anchor_case_id")
        if trigger_source not in ("batch", "live"):
            raise ValueError("unsupported trigger source")
        run_id = uuid.uuid4().hex
        started_at = self.clock()
        if hasattr(self.repository, "create_run"):
            self.repository.create_run(run_id, trigger_source, started_at)
        anchors, candidates = self.loader.load(
            anchor_case_id=anchor_case_id, date_window=date_window,
        )
        anchors, candidates = list(anchors or ()), list(candidates or ())
        alerts, failures, skipped = [], [], []
        created = updated = 0
        seen = set()
        anchors_seen = 0
        candidates_seen = 0
        for anchor in anchors:
            if trigger_source == "live" and not anchor.get("completed", True):
                skipped.append({"case_id": anchor.get("CaseMasterID"), "reason": "pending_enrichment"})
                continue
            visible_candidates = []
            for candidate in candidates:
                if int(candidate.get("CaseMasterID")) == int(anchor.get("CaseMasterID")):
                    continue
                try:
                    visible = self.pair_authorizer(anchor, candidate)
                except Exception:
                    visible = False
                if visible:
                    visible_candidates.append(candidate)
            anchors_seen += 1
            candidates_seen += len(visible_candidates)
            try:
                semantic = self.matcher.similar_cases(
                    anchor, visible_candidates, self.caller,
                    limit=max(10, len(visible_candidates)),
                )
            except Exception as exc:
                failures.append("semantic retrieval failed")
                semantic = ()
            by_case = {int(item.matched_case_id): item for item in semantic}
            for candidate in visible_candidates:
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
                if alert and hasattr(self.repository, "ensure_recipient"):
                    self._deliver_recipients(
                        alert, anchor, candidate, failures,
                    )
                if before:
                    updated += 1
                else:
                    created += 1
        result = ScanResult(
            run_id=run_id, trigger_source=trigger_source,
            anchors_seen=anchors_seen, candidates_seen=candidates_seen,
            alerts=tuple(alerts), alerts_created=created, alerts_updated=updated,
            skipped_cases=tuple(skipped), failures=tuple(failures),
        )
        if hasattr(self.repository, "finish_run"):
            self.repository.finish_run(run_id, result, self.clock())
        return result

    def _deliver_recipients(self, alert, anchor, candidate, failures):
        try:
            recipients = self.recipient_router(anchor, candidate) or ()
        except Exception:
            recipients = ()
            failures.append("recipient delivery failed")
        for employee_id in recipients:
            delivered = False
            for _attempt in range(self.recipient_retry_attempts):
                try:
                    self.repository.ensure_recipient(alert["AlertID"], employee_id)
                    delivered = True
                    break
                except Exception:
                    # Do not expose provider errors or recipient identifiers in
                    # the scan result. The durable alert remains available for
                    # an independent recipient retry/reconciliation job.
                    continue
            if not delivered and "recipient delivery failed" not in failures:
                failures.append("recipient delivery failed")

    def _existing(self, alert_type, pair):
        for row in getattr(self.repository, "list_alerts", lambda: ())():
            if row.get("AlertType") == alert_type and {
                int(row.get("AnchorCaseID")), int(row.get("MatchedCaseID"))
            } == set(pair):
                return row
        return None
