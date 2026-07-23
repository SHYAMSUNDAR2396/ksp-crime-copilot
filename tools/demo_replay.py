"""Deterministic offline backup replay for the KSP Crime Copilot demo.

The replay uses the same application boundaries as the deployed functions,
but replaces Catalyst services with the repository's SQLite and deterministic
adapters.  It is intentionally a compact contract replay rather than a video:
it can be rerun on a disconnected demo machine and produces a redacted JSON
transcript for the nine beats in ``PLAN.md``.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

from functions.crime_query import audit_api, db as db_module, intelligence_api, main, narrative_api
from functions.crime_query import access, translate
from functions.crime_query.conversation import InMemoryConversationStore
from functions.crime_query.conversation_api import export_session
from functions.crime_query.mo_embeddings import DeterministicEmbeddingProvider
from functions.crime_query.mo_index import SqliteMoIndex
from functions.crime_query.mo_matcher import MoMatcher
from functions.crime_query.silent_match_api import SilentMatchAPI
from functions.crime_query.silent_match_repository import SilentMatchRepository
from functions.crime_query.silent_match_scanner import SilentMatchScanner
from functions.silent_match.index_cases import IndexJob
from functions.silent_match.runtime import CatalystCaseLoader
from tools import gen_data


TODAY = dt.date(2026, 7, 23)
DEMO_INDEX_VERSION = "demo-mo-v1"
CASE_LIST_SQL = (
    "SELECT CaseMaster.CrimeNo FROM CaseMaster "
    "WHERE CaseMaster.PoliceStationID = 1 LIMIT 2"
)
COUNT_SQL = "SELECT COUNT(CaseMaster.CaseMasterID) AS n FROM CaseMaster"


def _fake_query(payload, db, sql, answer, employee_id):
    from functions.crime_query.llm import FakeLLM

    request = dict(payload)
    request["employee_id"] = employee_id
    request.setdefault("question", "demo query")
    return main.handle_question(
        request, db, FakeLLM([sql, answer]), translate.NullTranslator(), TODAY,
    )


def _statewide_employee(db):
    rows = db.execute_raw(
        'SELECT Employee.EmployeeID FROM "Employee" '
        'JOIN "Rank" ON Employee.RankID = Rank.rowid '
        'WHERE Rank.Hierarchy <= 2 ORDER BY Employee.EmployeeID'
    )
    if not rows:
        raise RuntimeError("synthetic data has no statewide command caller")
    return int(rows[0]["EmployeeID"])


def _beat(number, name, details, ok=True):
    return {"id": number, "name": name, "ok": bool(ok), "details": details}


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def build_replay(sqlite_path):
    """Build the synthetic fixture and return the complete nine-beat replay."""
    sqlite_path = Path(sqlite_path)
    if sqlite_path.exists():
        sqlite_path.unlink()
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    gen_data.build(str(sqlite_path))
    db = db_module.SqliteDB(str(sqlite_path))
    beats = []
    try:
        constable_employee = 9
        command_employee = _statewide_employee(db)

        # Beat 1: text and voice enter the same query/evidence contract.
        chat = _fake_query(
            {"question": "show two recent cases", "task_type": "structured_query"},
            db, CASE_LIST_SQL, "Two visible cases found.", constable_employee,
        )
        from functions.crime_query.llm import FakeLLM
        from functions.crime_query import voice

        voice_result = main.handle_voice_question(
            {
                "employee_id": constable_employee,
                "session_id": "demo-voice",
                "turn_id": 1,
                "transcript": "show two recent cases",
                "response_language": "en",
            }, db, FakeLLM([CASE_LIST_SQL, "Two visible cases found."]),
            translate.NullTranslator(), TODAY, InMemoryConversationStore(),
        )
        beats.append(_beat(1, "chat_voice_query_parity", {
            "chat_refused": chat["refused"],
            "voice_refused": voice_result["refused"],
            "citations_match": chat["citations"] == voice_result["citations"],
            "citation_count": len(chat["citations"]),
            "voice_contract": voice.accept_turn(voice_result, 1),
        }, not chat["refused"] and not voice_result["refused"]
           and chat["citations"] == voice_result["citations"]))

        # Beat 2: a typed follow-up is persisted in bounded session context.
        session = InMemoryConversationStore()
        first = main.handle_session_question(
            {"employee_id": constable_employee, "session_id": "demo-session",
             "turn_id": 1, "question": "show two recent cases"}, db,
            FakeLLM([CASE_LIST_SQL, "Two visible cases found."]),
            translate.NullTranslator(), TODAY, session,
        )
        follow_up = main.handle_session_question(
            {"employee_id": constable_employee, "session_id": "demo-session",
             "turn_id": 2, "question": "only the first one"}, db,
            FakeLLM([CASE_LIST_SQL, "The narrowed result is ready."]),
            translate.NullTranslator(), TODAY, session,
        )
        state = session.load("demo-session", constable_employee)
        beats.append(_beat(2, "context_follow_up", {
            "first_turn": first["turn_id"],
            "follow_up_turn": follow_up["turn_id"],
            "stored_turns": len(state.turns),
        }, len(state.turns) == 2 and follow_up["turn_id"] == 2))

        # Beat 3: the identical aggregate is visibly scoped by rank.
        junior = _fake_query({"question": "total cases"}, db, COUNT_SQL,
                              "The scoped count is ready.", constable_employee)
        senior = _fake_query({"question": "total cases"}, db, COUNT_SQL,
                              "The statewide count is ready.", command_employee)
        junior_count = int(junior["rows"][0]["n"])
        senior_count = int(senior["rows"][0]["n"])
        beats.append(_beat(3, "rank_scoped_rbac", {
            "constable_count": junior_count,
            "command_count": senior_count,
            "statewide_scope_wider": senior_count >= junior_count,
        }, not junior["refused"] and not senior["refused"]
           and senior_count >= junior_count))

        # Beat 4: network and entity-resolution view.
        network = intelligence_api.handle_operation(
            {"employee_id": command_employee, "operation": "network",
             "case_master_id": 1}, db, TODAY,
        )
        beats.append(_beat(4, "network_and_hidden_link", {
            "refused": network["refused"],
            "nodes": len(network.get("data", {}).get("nodes", ())),
            "edges": len(network.get("data", {}).get("edges", ())),
            "citations": len(network.get("citations", ())),
        }, not network["refused"] and bool(network.get("data", {}).get("nodes"))))

        # Beat 5: deterministic trend/hotspot/prevention view.
        analytics = intelligence_api.handle_operation(
            {"employee_id": command_employee, "operation": "analytics"}, db, TODAY,
        )
        analytics_data = analytics.get("data", {})
        beats.append(_beat(5, "pattern_hotspot_prevention", {
            "refused": analytics["refused"],
            "trend_points": len(analytics_data.get("trends", ())),
            "hotspots": len(analytics_data.get("hotspots", ())),
            "has_prevention_brief": bool(analytics_data.get("prevention")),
        }, not analytics["refused"] and "trends" in analytics_data))

        # Beat 6: cited behavioral profile, explicitly not a risk score.
        profile = intelligence_api.handle_operation(
            {"employee_id": command_employee, "operation": "profile",
             "case_master_id": 1}, db, TODAY,
        )
        profile_data = profile.get("data", {})
        beats.append(_beat(6, "behavioral_profile", {
            "refused": profile["refused"],
            "linked_cases": len(profile_data.get("linked_case_ids", ())),
            "citations": len(profile.get("citations", ())),
            "decision_support_only": "risk_score" not in profile_data,
        }, not profile["refused"] and bool(profile.get("citations"))))

        # Beat 7: original BriefFacts excerpts remain citation-backed.
        narrative = narrative_api.handle_operation(
            {"employee_id": command_employee,
             "question": "broken lock gold cash", "limit": 3}, db, today=TODAY,
        )
        beats.append(_beat(7, "explainable_narrative_citations", {
            "refused": narrative["refused"],
            "matches": len(narrative.get("data", {}).get("matches", ())),
            "citations": len(narrative.get("citations", ())),
            "local_fallback_marked": narrative.get("data", {}).get("partial") is True,
        }, not narrative["refused"] and bool(narrative.get("citations"))))

        # Beat 8: audit viewer and local HTML export; SmartBrowz is an account
        # gate and is deliberately represented as a fallback in this replay.
        audit = audit_api.handle_operation(
            {"employee_id": command_employee, "operation": "audit"}, db, TODAY,
        )
        exported = export_session(
            {"employee_id": constable_employee, "session_id": "demo-session"},
            db, session, renderer=None, today=TODAY,
        )
        beats.append(_beat(8, "audit_and_conversation_export", {
            "audit_refused": audit["refused"],
            "audit_rows": len(audit.get("data", {}).get("rows", ())),
            "export_code": exported["code"],
            "export_content_type": exported["content_type"],
            "pdf_live_gate": exported["content_type"] == "application/pdf",
        }, not audit["refused"] and exported["code"] == "OK"))

        # Beat 9: one deterministic index/scanner contract for batch and live.
        loader = CatalystCaseLoader(db, candidate_lookback_days=365)
        ravi_ids = tuple(gen_data.DEMO_CASE_IDS["ravi_variants"])
        if len(ravi_ids) < 2:
            raise RuntimeError("synthetic data has no seeded identity pair")
        anchor_id, candidate_id = int(ravi_ids[0]), int(ravi_ids[1])
        anchor, candidate = loader(anchor_id), loader(candidate_id)
        provider = DeterministicEmbeddingProvider()
        index = SqliteMoIndex(db, index_version=DEMO_INDEX_VERSION)
        index_job = IndexJob([anchor, candidate], provider, index, now="demo")
        index_result = index_job.run(DEMO_INDEX_VERSION)
        matcher = MoMatcher(index, provider)
        repository = SilentMatchRepository(db)
        context = access.resolve_access_context(db.caller_for(command_employee), db)

        class ReplayLoader(object):
            def load(self, anchor_case_id=None, date_window=None):
                return [anchor], [candidate]

            def __call__(self, case_id, candidates=False):
                if candidates:
                    return [anchor, candidate]
                return anchor if int(case_id) == anchor_id else candidate

        scanner = SilentMatchScanner(
            ReplayLoader(), matcher, repository, caller=context,
            clock=lambda: "2026-07-23T00:00:00+00:00",
            pair_authorizer=lambda left, right: access.can_read_case_pair(
                context, left, right, "retrieve_similar_cases"
            ),
            recipient_router=lambda _left, _right: (command_employee,),
        )
        batch = scanner.scan(date_window=("2026-06-01", "2026-06-30"), trigger_source="batch")
        live = scanner.scan(anchor_case_id=anchor_id, trigger_source="live")
        alert = repository.list_alerts()[0] if repository.list_alerts() else {}
        api = SilentMatchAPI(
            db.caller_for, lambda _caller: context, ReplayLoader(), matcher,
            scanner, repository,
        )
        transition_status, transition = api.handle(
            "POST", "/alerts/{0}/transition".format(alert.get("AlertID")),
            {"employee_id": command_employee, "to_status": "Linked",
             "note": "Demo evidence reviewed", "now": "2026-07-23T00:00:00+00:00"},
        )
        linked_alert = transition.get("alert", {}) if transition_status == 200 else {}
        batch_score = batch.alerts[0]["Score"] if batch.alerts else None
        live_score = live.alerts[0]["Score"] if live.alerts else None
        beats.append(_beat(9, "cross_jurisdiction_silent_match", {
            "index_version": DEMO_INDEX_VERSION,
            "indexed": index_result.indexed,
            "batch_alerts_created": batch.alerts_created,
            "live_alerts_updated": live.alerts_updated,
            "batch_live_score_parity": batch_score == live_score,
            "recipient_count": len(repository.recipients_for(alert.get("AlertID"))) if alert else 0,
            "status": linked_alert.get("Status", ""),
            "citation_pair": [alert.get("AnchorCrimeNo"), alert.get("MatchedCrimeNo")] if alert else [],
        }, index_result.failures == () and batch_score is not None
           and batch_score == live_score and transition_status == 200
           and linked_alert.get("Status") == "Linked"))
    finally:
        db.close()

    passed = sum(1 for beat in beats if beat["ok"])
    output = {
        "schema_version": "ksp-demo-replay-v1",
        "generated_for": "PLAN.md demo runbook",
        "synthetic_data": True,
        "live_catalyst_executed": False,
        "beats": _jsonable(beats),
        "summary": {"passed": passed, "failed": len(beats) - passed},
    }
    return output


def main_cli(argv=None):
    parser = argparse.ArgumentParser(description="Generate the offline KSP demo replay")
    parser.add_argument("--sqlite", default="build/demo-crime.db")
    parser.add_argument("--output", default="docs/demo-replay.json")
    args = parser.parse_args(argv)
    replay = build_replay(args.sqlite)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(replay, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(replay["summary"], sort_keys=True))
    return 0 if replay["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
