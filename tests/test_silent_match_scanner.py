from functions.crime_query.silent_match_scanner import SilentMatchScanner


class Loader:
    def __init__(self, anchor, candidates):
        self.anchor, self.candidates = anchor, candidates

    def load(self, **kwargs):
        return [self.anchor], self.candidates


class Matcher:
    def similar_cases(self, source, candidates, caller, limit=10):
        return []


class CapturingMatcher(Matcher):
    def __init__(self):
        self.candidates = None

    def similar_cases(self, source, candidates, caller, limit=10):
        self.candidates = list(candidates)
        return []


class Repository:
    def __init__(self):
        self.rows = []
        self.runs = []
        self.recipients = []

    def list_alerts(self):
        return self.rows

    def upsert_alert(self, score, anchor, candidate, run_id, now):
        row = {"AlertType": score.alert_type, "AnchorCaseID": anchor["CaseMasterID"],
               "MatchedCaseID": candidate["CaseMasterID"], "Score": score.score,
               "AlertID": len(self.rows) + 1}
        for old in self.rows:
            if {old["AnchorCaseID"], old["MatchedCaseID"]} == {row["AnchorCaseID"], row["MatchedCaseID"]}:
                row["AlertID"] = old["AlertID"]
                old.update(row)
                return old
        self.rows.append(row)
        return row

    def create_run(self, run_id, trigger_source, started_at):
        self.runs.append((run_id, trigger_source))

    def finish_run(self, run_id, result, finished_at):
        return None

    def ensure_recipient(self, alert_id, employee_id):
        if (alert_id, employee_id) not in self.recipients:
            self.recipients.append((alert_id, employee_id))


class FlakyRecipientRepository(Repository):
    def __init__(self, failures_before_success):
        super().__init__()
        self.failures_before_success = failures_before_success
        self.recipient_attempts = 0

    def ensure_recipient(self, alert_id, employee_id):
        self.recipient_attempts += 1
        if self.recipient_attempts <= self.failures_before_success:
            raise RuntimeError("provider-specific recipient failure")
        return super().ensure_recipient(alert_id, employee_id)


def case(case_id, name, station):
    return {"CaseMasterID": case_id, "CrimeNo": "FIR/{}".format(case_id),
            "AccusedName": name, "CrimeSubHeadID": 1, "SectionCodes": ["379"],
            "CrimeRegisteredDate": "2026-06-01", "latitude": 12.9,
            "longitude": 77.6, "StationID": station}


def test_batch_and_live_share_scoring_and_deduplication():
    anchor, candidate = case(1, "Ravi Kumar", 1), case(2, "Ravi Kumar", 2)
    repo = Repository()
    scanner = SilentMatchScanner(Loader(anchor, [candidate]), Matcher(), repo,
                                 recipient_router=lambda left, right: (9,))
    batch = scanner.scan(date_window=("2026-06-01", "2026-06-30"))
    live = scanner.scan(anchor_case_id=1, trigger_source="live")
    assert batch.alerts[0]["Score"] == live.alerts[0]["Score"]
    assert batch.alerts_created == 1
    assert live.alerts_updated == 1
    assert len(repo.rows) == 1
    assert repo.runs and repo.recipients == [(1, 9)]


def test_live_incomplete_anchor_is_skipped():
    anchor = case(1, "Ravi Kumar", 1)
    anchor["completed"] = False
    scanner = SilentMatchScanner(Loader(anchor, [case(2, "Ravi Kumar", 2)]), Matcher(), Repository())
    result = scanner.scan(anchor_case_id=1, trigger_source="live")
    assert result.skipped_cases[0]["reason"] == "pending_enrichment"


def test_scanner_filters_out_of_scope_pairs_before_matching():
    anchor = case(1, "Ravi Kumar", 1)
    candidates = [case(2, "Ravi Kumar", 2), case(3, "Ravi Kumar", 3)]
    matcher = CapturingMatcher()
    scanner = SilentMatchScanner(
        Loader(anchor, candidates), matcher, Repository(),
        pair_authorizer=lambda left, right: int(right["CaseMasterID"]) != 3,
    )
    scanner.scan(anchor_case_id=1, trigger_source="live")
    assert [row["CaseMasterID"] for row in matcher.candidates] == [2]


def test_recipient_delivery_retries_without_losing_durable_alert():
    repo = FlakyRecipientRepository(failures_before_success=1)
    scanner = SilentMatchScanner(
        Loader(case(1, "Ravi Kumar", 1), [case(2, "Ravi Kumar", 2)]),
        Matcher(), repo, recipient_router=lambda left, right: (9,),
        recipient_retry_attempts=2,
    )
    result = scanner.scan(anchor_case_id=1, trigger_source="live")
    assert result.failures == ()
    assert repo.rows and repo.recipients == [(1, 9)]
    assert repo.recipient_attempts == 2


def test_recipient_delivery_failure_is_bounded_and_sanitized():
    repo = FlakyRecipientRepository(failures_before_success=9)
    scanner = SilentMatchScanner(
        Loader(case(1, "Ravi Kumar", 1), [case(2, "Ravi Kumar", 2)]),
        Matcher(), repo, recipient_router=lambda left, right: (9,),
        recipient_retry_attempts=2,
    )
    result = scanner.scan(anchor_case_id=1, trigger_source="live")
    assert repo.rows
    assert repo.recipient_attempts == 2
    assert result.failures == ("recipient delivery failed",)
