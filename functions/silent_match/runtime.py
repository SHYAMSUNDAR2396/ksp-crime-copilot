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
    from .index_cases import IndexJob, OperationalIndexStatusStore
    from ..crime_query.graph_projection import GraphProjectionJob
except ImportError:  # pragma: no cover
    from functions.crime_query import access
    from functions.crime_query.db import ZcqlDB
    from functions.crime_query.mo_embeddings import QuickMLMultilingualProvider
    from functions.crime_query.mo_index import OperationalMoIndex
    from functions.crime_query.mo_matcher import MoMatcher
    from functions.crime_query.silent_match_api import SilentMatchAPI
    from functions.crime_query.silent_match_repository import SilentMatchRepository
    from functions.crime_query.silent_match_scanner import SilentMatchScanner
    from functions.silent_match.index_cases import IndexJob, OperationalIndexStatusStore
    from functions.crime_query.graph_projection import GraphProjectionJob


class CatalystCaseLoader:
    """Fixed ZCQL case projection used by similar-case and scan paths."""

    DEFAULT_CANDIDATE_LOOKBACK_DAYS = 365

    CASE_SQL = (
        "SELECT CaseMaster.CaseMasterID, CaseMaster.CrimeNo, "
        "CaseMaster.CrimeRegisteredDate, Unit.UnitID AS PoliceStationID, "
        "Employee.EmployeeID AS PolicePersonID, "
        "ArrestEmployee.EmployeeID AS ArrestIOID, "
        "CrimeSubHead.CrimeSubHeadID AS CrimeMinorHeadID, "
        "CaseMaster.BriefFacts, CaseMaster.latitude, CaseMaster.longitude, "
        "District.DistrictID AS DistrictID, Accused.AccusedName, "
        "Accused.AgeYear, Accused.GenderID, Section.SectionCode AS SectionID "
        "FROM CaseMaster "
        "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
        "JOIN District ON Unit.DistrictID = District.ROWID "
        "LEFT JOIN Employee ON CaseMaster.PolicePersonID = Employee.ROWID "
        "LEFT JOIN ArrestSurrender ON ArrestSurrender.CaseMasterID = CaseMaster.ROWID "
        "LEFT JOIN Employee AS ArrestEmployee ON ArrestSurrender.IOID = ArrestEmployee.ROWID "
        "LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.ROWID "
        "LEFT JOIN Accused ON Accused.CaseMasterID = CaseMaster.ROWID "
        "LEFT JOIN ActSectionAssociation ON ActSectionAssociation.CaseMasterID = CaseMaster.ROWID "
        "LEFT JOIN Section ON ActSectionAssociation.SectionID = Section.ROWID"
    )

    def __init__(self, db, candidate_lookback_days=None):
        self.db = db
        raw_lookback = candidate_lookback_days
        if raw_lookback is None:
            raw_lookback = os.environ.get(
                "KSP_SILENT_MATCH_LOOKBACK_DAYS",
                self.DEFAULT_CANDIDATE_LOOKBACK_DAYS,
            )
        try:
            self.candidate_lookback_days = int(raw_lookback)
        except (TypeError, ValueError):
            raise ValueError("candidate lookback must be an integer")
        if self.candidate_lookback_days < 1:
            raise ValueError("candidate lookback must be positive")

    def _rows(self, where=""):
        return self.db.execute_raw(self.CASE_SQL + where)

    def load_index_cases(self, case_ids=None):
        """Load only cases with narrative text for the versioned index job."""
        if case_ids:
            values = []
            for value in case_ids:
                try:
                    values.append(int(value))
                except (TypeError, ValueError):
                    raise ValueError("case IDs must be integers")
            if not values:
                return []
            where = " WHERE CaseMaster.CaseMasterID IN ({})".format(
                ",".join(str(value) for value in sorted(set(values)))
            )
            rows = self._merge(self._rows(where))
        else:
            rows = self._merge(self._rows())
        return [row for row in rows if str(row.get("BriefFacts") or "").strip()]

    def load_graph_cases(self, case_ids=None):
        """Load all schema-shaped cases for the relationship projection."""
        if case_ids:
            values = []
            for value in case_ids:
                try:
                    values.append(int(value))
                except (TypeError, ValueError):
                    raise ValueError("case IDs must be integers")
            if not values:
                return []
            where = " WHERE CaseMaster.CaseMasterID IN ({})".format(
                ",".join(str(value) for value in sorted(set(values)))
            )
            return self._merge(self._rows(where))
        return self._merge(self._rows())

    @staticmethod
    def _case_date(value):
        if isinstance(value, dt.datetime):
            return value.date()
        if isinstance(value, dt.date):
            return value
        try:
            return dt.date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _date_window(cls, date_window):
        if not date_window or len(date_window) != 2:
            raise ValueError("date window must contain start and end dates")
        start, end = (cls._case_date(value) for value in date_window)
        if start is None or end is None or start > end:
            raise ValueError("date window must contain valid ordered ISO dates")
        return start, end

    @staticmethod
    def _date_predicate(start, end):
        # Dates are parsed before interpolation; this is intentionally not a
        # general-purpose SQL builder.
        return (
            " WHERE CaseMaster.CrimeRegisteredDate >= '{}'"
            " AND CaseMaster.CrimeRegisteredDate <= '{}'"
        ).format(start.isoformat(), end.isoformat())

    @classmethod
    def _within(cls, rows, start, end):
        return [
            row for row in rows
            if (case_date := cls._case_date(row.get("CrimeRegisteredDate")))
            and start <= case_date <= end
        ]

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
            case.setdefault("_accused_profiles", set())
            case.setdefault("_arrest_ioids", set())
            if row.get("SectionID") is not None:
                case["_sections"].add(str(row["SectionID"]))
            for key in ("PoliceStationID", "DistrictID", "AgeYear", "GenderID", "PolicePersonID"):
                if case.get(key) is not None:
                    try:
                        case[key] = int(case[key])
                    except (TypeError, ValueError):
                        pass
            if row.get("ArrestIOID") is not None:
                try:
                    case["_arrest_ioids"].add(int(row["ArrestIOID"]))
                except (TypeError, ValueError):
                    pass
            case["CaseMasterID"] = case_id
            for key in ("latitude", "longitude"):
                if case.get(key) is not None:
                    try:
                        case[key] = float(case[key])
                    except (TypeError, ValueError):
                        pass
            if row.get("AccusedName"):
                case["_accused_profiles"].add((
                    str(row["AccusedName"]), str(row.get("AgeYear") or ""),
                    str(row.get("GenderID") or ""),
                ))
                case.setdefault("AccusedName", row["AccusedName"])
                case.setdefault("AgeYear", row.get("AgeYear"))
                case.setdefault("GenderID", row.get("GenderID"))
        for case in cases.values():
            case["SectionCodes"] = tuple(sorted(case.pop("_sections", set())))
            case["AccusedProfiles"] = tuple(sorted(case.pop("_accused_profiles", set())))
            case["AccusedNames"] = tuple(profile[0] for profile in case["AccusedProfiles"])
            case["ArrestIOIDs"] = tuple(sorted(case.pop("_arrest_ioids", set())))
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
            if not anchor:
                return [], []
            anchor_date = self._case_date(anchor.get("CrimeRegisteredDate"))
            if anchor_date is None:
                return [anchor], []
            start = anchor_date - dt.timedelta(days=self.candidate_lookback_days)
            candidates = self._merge(self._rows(self._date_predicate(start, anchor_date)))
            candidates = self._within(candidates, start, anchor_date)
            return [anchor], [
                row for row in candidates
                if int(row.get("CaseMasterID")) != int(anchor["CaseMasterID"])
            ]
        start, end = self._date_window(date_window)
        candidate_start = start - dt.timedelta(days=self.candidate_lookback_days)
        anchors = self._merge(self._rows(self._date_predicate(start, end)))
        anchors = self._within(anchors, start, end)
        candidates = self._merge(self._rows(self._date_predicate(candidate_start, end)))
        candidates = self._within(candidates, candidate_start, end)
        anchor_ids = {int(row["CaseMasterID"]) for row in anchors}
        return anchors, [
            row for row in candidates
            if int(row.get("CaseMasterID")) not in anchor_ids
        ]


def recipient_employee_ids(db, anchor, candidate):
    """Build the durable recipient set for one authorized case pair."""
    employee_ids = set()
    districts = set()
    for case in (anchor, candidate):
        if case.get("PolicePersonID") is not None:
            try:
                employee_ids.add(int(case["PolicePersonID"]))
            except (TypeError, ValueError):
                pass
        for value in case.get("ArrestIOIDs", ()) or ():
            try:
                employee_ids.add(int(value))
            except (TypeError, ValueError):
                pass
        if case.get("DistrictID") is not None:
            try:
                districts.add(int(case["DistrictID"]))
            except (TypeError, ValueError):
                pass
    if hasattr(db, "command_employee_ids"):
        employee_ids.update(db.command_employee_ids(districts))
    return tuple(sorted(employee_ids))


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
    active_index_version = os.environ.get(
        "QUICKML_EMBEDDINGS_INDEX_VERSION", "mo-index-v1"
    )
    index = OperationalMoIndex(db, index_version=active_index_version)
    matcher = MoMatcher(
        index,
        provider,
    )
    repository = SilentMatchRepository(db)

    def index_job_for(payload):
        return IndexJob(
            loader.load_index_cases(payload.get("changed_case_ids")),
            provider, index,
            status=OperationalIndexStatusStore(db, active_index_version),
        )

    def graph_projection_job_for(payload):
        version = str(payload.get("projection_version") or "").strip()
        cases = loader.load_graph_cases(payload.get("changed_case_ids"))
        return GraphProjectionJob(db, cases, projection_version=version)

    def context_for(caller):
        return access.resolve_access_context(caller, db)

    def scanner_for(context):
        return SilentMatchScanner(
            loader, matcher, repository, caller=context,
            pair_authorizer=lambda anchor, candidate: access.can_read_case_pair(
                context, anchor, candidate, "retrieve_similar_cases"
            ),
            recipient_router=lambda anchor, candidate: recipient_employee_ids(
                db, anchor, candidate
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
        index_job_factory=index_job_for,
        graph_projection_job_factory=graph_projection_job_for,
    )
