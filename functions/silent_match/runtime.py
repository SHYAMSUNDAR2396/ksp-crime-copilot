"""Catalyst dependency construction for the silent-match function."""
import datetime as dt
import os

try:
    from ..crime_query import access
    from ..crime_query.db import ZcqlDB
    from ..crime_query.mo_embeddings import QuickMLMultilingualProvider
    from ..crime_query.mo_index import OperationalMoIndex
    from ..crime_query.mo_matcher import MoMatcher
    from ..crime_query.silent_match_api import SilentMatchAPI
    from ..crime_query.silent_match_repository import SilentMatchRepository
    from ..crime_query.silent_match_scanner import SilentMatchScanner
except ImportError:  # pragma: no cover
    from functions.crime_query import access
    from functions.crime_query.db import ZcqlDB
    from functions.crime_query.mo_embeddings import QuickMLMultilingualProvider
    from functions.crime_query.mo_index import OperationalMoIndex
    from functions.crime_query.mo_matcher import MoMatcher
    from functions.crime_query.silent_match_api import SilentMatchAPI
    from functions.crime_query.silent_match_repository import SilentMatchRepository
    from functions.crime_query.silent_match_scanner import SilentMatchScanner


class CatalystCaseLoader:
    """Fixed ZCQL case projection used by similar-case and scan paths."""

    CASE_SQL = (
        "SELECT CaseMaster.CaseMasterID, CaseMaster.CrimeNo, "
        "CaseMaster.CrimeRegisteredDate, CaseMaster.PoliceStationID, "
        "CaseMaster.PolicePersonID, CaseMaster.CrimeMinorHeadID, "
        "CaseMaster.BriefFacts, CaseMaster.latitude, CaseMaster.longitude, "
        "Unit.DistrictID, Accused.AccusedName, Accused.AgeYear, Accused.GenderID, "
        "ActSectionAssociation.SectionID "
        "FROM CaseMaster "
        "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
        "LEFT JOIN Accused ON Accused.CaseMasterID = CaseMaster.ROWID "
        "LEFT JOIN ActSectionAssociation ON ActSectionAssociation.CaseMasterID = CaseMaster.ROWID"
    )

    def __init__(self, db):
        self.db = db

    def _rows(self, where=""):
        return self.db.execute_raw(self.CASE_SQL + where)

    @staticmethod
    def _merge(rows):
        cases = {}
        for row in rows:
            case_id = int(row["CaseMasterID"])
            case = cases.setdefault(case_id, {
                key: row.get(key) for key in (
                    "CaseMasterID", "CrimeNo", "CrimeRegisteredDate",
                    "PoliceStationID", "DistrictID", "BriefFacts",
                    "latitude", "longitude", "PolicePersonID",
                    "CrimeMinorHeadID",
                )
            })
            case.setdefault("_sections", set())
            if row.get("SectionID") is not None:
                case["_sections"].add(str(row["SectionID"]))
            for key in ("PoliceStationID", "DistrictID", "AgeYear", "GenderID", "PolicePersonID"):
                if case.get(key) is not None:
                    try:
                        case[key] = int(case[key])
                    except (TypeError, ValueError):
                        pass
            case["CaseMasterID"] = case_id
            for key in ("latitude", "longitude"):
                if case.get(key) is not None:
                    try:
                        case[key] = float(case[key])
                    except (TypeError, ValueError):
                        pass
            if row.get("AccusedName") and "AccusedName" not in case:
                case["AccusedName"] = row["AccusedName"]
                case["AgeYear"] = row.get("AgeYear")
                case["GenderID"] = row.get("GenderID")
        for case in cases.values():
            case["SectionCodes"] = tuple(sorted(case.pop("_sections", set())))
        return list(cases.values())

    def __call__(self, case_id, candidates=False):
        if candidates:
            return self._merge(self._rows())
        rows = self._rows(" WHERE CaseMaster.CaseMasterID = {}".format(int(case_id)))
        merged = self._merge(rows)
        return merged[0] if merged else None

    def load(self, anchor_case_id=None, date_window=None):
        if anchor_case_id is not None:
            anchor = self(anchor_case_id)
            return ([anchor] if anchor else []), self(None, candidates=True)
        rows = self._merge(self._rows())
        if date_window:
            start, end = date_window
            rows = [
                row for row in rows
                if start <= str(row.get("CrimeRegisteredDate")) <= end
            ]
        return rows, rows


def _token(app):
    value = app.credential.token()
    return value[1] if isinstance(value, tuple) else value


def build_api(app):
    db = ZcqlDB(app)
    loader = CatalystCaseLoader(db)
    provider = QuickMLMultilingualProvider(
        endpoint=os.environ["QUICKML_EMBEDDINGS_ENDPOINT"],
        token=_token(app),
        org_id=os.environ["QUICKML_ORG_ID"],
        model=os.environ.get("QUICKML_EMBEDDINGS_MODEL", "multilingual-v1"),
        timeout=float(os.environ.get("QUICKML_EMBEDDINGS_TIMEOUT", "10")),
        batch_size=int(os.environ.get("QUICKML_EMBEDDINGS_BATCH_SIZE", "32")),
    )
    matcher = MoMatcher(OperationalMoIndex(db), provider)
    repository = SilentMatchRepository(db)

    def context_for(caller):
        return access.resolve_access_context(caller, db)

    def scanner_for(context):
        return SilentMatchScanner(
            loader, matcher, repository, caller=context,
            recipient_router=lambda anchor, candidate: tuple(
                value for value in (
                    anchor.get("PolicePersonID"), candidate.get("PolicePersonID")
                ) if value is not None
            ),
        )

    return SilentMatchAPI(
        caller_loader=db.caller_for,
        access_resolver=context_for,
        case_loader=loader,
        matcher=matcher,
        scanner=None,
        repository=repository,
        scanner_factory=scanner_for,
    )
