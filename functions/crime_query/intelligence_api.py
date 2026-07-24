"""Authenticated application boundary for graph and analytics views."""
import datetime as dt
from dataclasses import asdict, is_dataclass

try:
    from . import access, policy_audit, supervisor, supervisor_runtime
    from .db import DBError
    from .demographics import demographic_aggregate
    from .evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
    from .intelligence import analytics_view, network_view
    from .graph import normalize_person_name, person_resolution_key
    from .graph_projection import GraphProjectionReader
    from .profile import behavioral_profile
except ImportError:  # pragma: no cover
    import access, policy_audit, supervisor, supervisor_runtime
    from db import DBError
    from demographics import demographic_aggregate
    from evidence import EvidenceBundle, filter_visible_bundle, merge_bundles
    from intelligence import analytics_view, network_view
    from graph import normalize_person_name, person_resolution_key
    from graph_projection import GraphProjectionReader
    from profile import behavioral_profile


CASE_PROJECTION = (
    "SELECT CaseMaster.CaseMasterID, CaseMaster.CrimeNo, "
    "CaseMaster.CrimeRegisteredDate, CaseMaster.IncidentFromDate, "
        "Unit.UnitID AS PoliceStationID, Employee.EmployeeID AS PolicePersonID, "
        "ArrestEmployee.EmployeeID AS ArrestIOID, "
        "CrimeHead.CrimeHeadID AS CrimeMajorHeadID, "
        "CrimeSubHead.CrimeSubHeadID AS CrimeMinorHeadID, CaseMaster.BriefFacts, "
    "CaseMaster.latitude, CaseMaster.longitude, District.DistrictID AS DistrictID, "
    "Accused.AccusedName, Accused.AgeYear, Accused.GenderID, "
    "Section.SectionCode AS SectionID "
    "FROM CaseMaster "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
        "JOIN District ON Unit.DistrictID = District.ROWID "
        "LEFT JOIN Employee ON CaseMaster.PolicePersonID = Employee.ROWID "
        "LEFT JOIN ArrestSurrender ON ArrestSurrender.CaseMasterID = CaseMaster.ROWID "
        "LEFT JOIN Employee AS ArrestEmployee ON ArrestSurrender.IOID = ArrestEmployee.ROWID "
        "LEFT JOIN CrimeSubHead ON CaseMaster.CrimeMinorHeadID = CrimeSubHead.ROWID "
        "LEFT JOIN CrimeHead ON CaseMaster.CrimeMajorHeadID = CrimeHead.ROWID "
    "LEFT JOIN Accused ON Accused.CaseMasterID = CaseMaster.ROWID "
    "LEFT JOIN ActSectionAssociation "
    "ON ActSectionAssociation.CaseMasterID = CaseMaster.ROWID "
    "LEFT JOIN Section ON ActSectionAssociation.SectionID = Section.ROWID"
)

COMPLAINANT_PERSON_PROJECTION = (
    "SELECT ComplainantDetails.CaseMasterID, "
    "ComplainantDetails.ComplainantName AS PersonName, "
    "ComplainantDetails.AgeYear, ComplainantDetails.GenderID, "
    "Unit.UnitID AS PoliceStationID, District.DistrictID AS DistrictID "
    "FROM ComplainantDetails "
    "JOIN CaseMaster ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
    "JOIN District ON Unit.DistrictID = District.ROWID"
)

VICTIM_PERSON_PROJECTION = (
    "SELECT Victim.CaseMasterID, Victim.VictimName AS PersonName, "
    "Victim.AgeYear, Victim.GenderID, Unit.UnitID AS PoliceStationID, "
    "District.DistrictID AS DistrictID FROM Victim "
    "JOIN CaseMaster ON Victim.CaseMasterID = CaseMaster.ROWID "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
    "JOIN District ON Unit.DistrictID = District.ROWID"
)

DEMOGRAPHIC_PROJECTION = (
    "SELECT ComplainantDetails.CaseMasterID, "
    "ComplainantDetails.AgeYear, ComplainantDetails.GenderID, "
    "ComplainantDetails.OccupationID, ComplainantDetails.CasteID, "
    "ComplainantDetails.ReligionID, Unit.UnitID AS PoliceStationID, "
    "District.DistrictID AS DistrictID FROM ComplainantDetails "
    "JOIN CaseMaster ON ComplainantDetails.CaseMasterID = CaseMaster.ROWID "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
    "JOIN District ON Unit.DistrictID = District.ROWID"
)

VICTIM_DEMOGRAPHIC_PROJECTION = (
    "SELECT Victim.CaseMasterID, Victim.AgeYear, Victim.GenderID, "
    "Unit.UnitID AS PoliceStationID, District.DistrictID AS DistrictID FROM Victim "
    "JOIN CaseMaster ON Victim.CaseMasterID = CaseMaster.ROWID "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
    "JOIN District ON Unit.DistrictID = District.ROWID"
)

ACCUSED_DEMOGRAPHIC_PROJECTION = (
    "SELECT Accused.CaseMasterID, Accused.AgeYear, Accused.GenderID, "
    "Unit.UnitID AS PoliceStationID, District.DistrictID AS DistrictID FROM Accused "
    "JOIN CaseMaster ON Accused.CaseMasterID = CaseMaster.ROWID "
    "JOIN Unit ON CaseMaster.PoliceStationID = Unit.ROWID "
    "JOIN District ON Unit.DistrictID = District.ROWID"
)


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _evidence(status, claims=(), rows=(), citations=(), limitations=()):
    bundle = EvidenceBundle(
        agent_name="Intelligence Agent",
        status=status,
        claims=tuple(claims),
        rows_or_entities=tuple(rows),
        citations=tuple(citations),
        evidence_signals=("fixed_projection", "rbac_scoped_view"),
        confidence=1.0 if status == "ok" else 0.0,
        limitations=tuple(limitations),
        index_or_model_version="intelligence-v1",
        elapsed_ms=0,
    )
    visible = filter_visible_bundle(bundle, lambda row: True)
    merged = merge_bundles((visible,))
    return {
        "status": merged.status,
        "claims": list(merged.claims),
        "citations": list(merged.citations),
        "limitations": list(merged.limitations),
        "version": merged.index_or_model_version,
    }


def _refused(answer, policy_code="CAPABILITY_DENIED", limitations=()):
    return {
        "refused": True,
        "answer": answer,
        "data": {},
        "citations": [],
        "policy_code": policy_code,
        "evidence": _evidence("scope_denied", limitations=limitations),
    }


def _operation_bundle(agent_name, rows, citations, claims, signal, version):
    bundle = EvidenceBundle(
        agent_name=agent_name,
        status="ok",
        claims=tuple(claims),
        rows_or_entities=tuple(rows or ()),
        citations=tuple(citations or ()),
        evidence_signals=(signal,),
        confidence=1.0,
        limitations=(),
        index_or_model_version=version,
        elapsed_ms=0,
    )
    return filter_visible_bundle(bundle, lambda row: True)


def _scope_rows(context, cases):
    result = []
    for row in cases:
        station = row.get("PoliceStationID")
        district = row.get("DistrictID")
        if station is None or district is None:
            continue
        if not access.in_scope(station, context.unit_ids):
            continue
        if not access.in_scope(district, context.district_ids):
            continue
        result.append(row)
    return result


def _case_rows(db):
    rows = db.execute_raw(CASE_PROJECTION)
    cases = {}
    for row in rows:
        case_id = int(row["CaseMasterID"])
        case = cases.setdefault(case_id, {
            key: row.get(key) for key in (
                "CaseMasterID", "CrimeNo", "CrimeRegisteredDate", "IncidentFromDate",
                "PoliceStationID", "PolicePersonID", "CrimeMajorHeadID", "CrimeMinorHeadID", "BriefFacts",
                "latitude", "longitude", "DistrictID",
            )
        })
        case.setdefault("_sections", set())
        case.setdefault("_accused_profiles", set())
        case.setdefault("_person_profiles", set())
        case.setdefault("_arrest_ioids", set())
        if row.get("ArrestIOID") is not None:
            try:
                case["_arrest_ioids"].add(int(row["ArrestIOID"]))
            except (TypeError, ValueError):
                pass
        if row.get("AccusedName"):
            profile = (
                str(row["AccusedName"]), str(row.get("AgeYear") or ""),
                str(row.get("GenderID") or ""),
            )
            case["_accused_profiles"].add(profile)
            case["_person_profiles"].add(profile + ("accused",))
            case.setdefault("AccusedName", row.get("AccusedName"))
            case.setdefault("AgeYear", row.get("AgeYear"))
            case.setdefault("GenderID", row.get("GenderID"))
        if row.get("SectionID") is not None:
            case["_sections"].add(str(row["SectionID"]))
    for query, role in (
        (COMPLAINANT_PERSON_PROJECTION, "complainant"),
        (VICTIM_PERSON_PROJECTION, "victim"),
    ):
        for row in db.execute_raw(query):
            case = cases.get(int(row["CaseMasterID"]))
            if case is None or not row.get("PersonName"):
                continue
            case["_person_profiles"].add((
                str(row["PersonName"]), str(row.get("AgeYear") or ""),
                str(row.get("GenderID") or ""), role,
            ))
    for case in cases.values():
        case["SectionCodes"] = tuple(sorted(case.pop("_sections", set())))
        case["AccusedProfiles"] = tuple(sorted(case.pop("_accused_profiles", set())))
        case["AccusedNames"] = tuple(profile[0] for profile in case["AccusedProfiles"])
        case["PersonProfiles"] = tuple(sorted(case.pop("_person_profiles", set())))
        case["ArrestIOIDs"] = tuple(sorted(case.pop("_arrest_ioids", set())))
    return list(cases.values())


def _demographic_rows(db):
    rows = db.execute_raw(DEMOGRAPHIC_PROJECTION)
    rows.extend(db.execute_raw(VICTIM_DEMOGRAPHIC_PROJECTION))
    rows.extend(db.execute_raw(ACCUSED_DEMOGRAPHIC_PROJECTION))
    return rows


def _profile_keys(row):
    profiles = row.get("AccusedProfiles") or ()
    if not profiles and row.get("AccusedName"):
        profiles = ((row.get("AccusedName"), row.get("AgeYear"), row.get("GenderID")),)
    keys = set()
    for name, age, gender in profiles:
        try:
            age_band = int(age) // 3
        except (TypeError, ValueError):
            age_band = -1
        keys.add((person_resolution_key(name), age_band, str(gender or "")))
    return keys


def _handle_operation(payload, db, today=None, analytics_provider=None):
    """Dispatch one capability view after the same caller/RBAC gate."""
    payload = payload or {}
    operation = payload.get("operation")
    if not isinstance(operation, str):
        return _refused("That intelligence operation is not available.", "CAPABILITY_DENIED")
    task_type = {
        "network": "graph",
        "analytics": "analytics",
        "profile": "narrative_query",
        "demographics": "structured_query",
        "case_detail": "structured_query",
    }.get(operation)
    if task_type is None:
        return _refused("That intelligence operation is not available.", "CAPABILITY_DENIED")

    employee_id = payload.get("employee_id")
    caller = (
        db.caller_for(employee_id)
        if isinstance(employee_id, int) and not isinstance(employee_id, bool) and employee_id > 0
        else None
    )
    if caller is None:
        return _refused("You are not authorised to view this intelligence.", limitations=("Caller identity was not verified.",))
    context = access.resolve_access_context(caller, db)
    task = supervisor.build_task_context(
        request_id=str(payload.get("request_id") or "intelligence"),
        task_type=task_type,
        access_context=context,
        deadline=supervisor.task_deadline(),
    )
    now = dt.datetime.combine(today or dt.date.today(), dt.time(0, 0))
    selection = policy_audit.record_agent_selection(task, (), outcome="selected")
    policy_audit.persist_record(db, selection, now)
    if task.denials:
        code, capability = task.denials[0]
        denial = policy_audit.record_policy_decision(
            context, capability, task.request_id, task.task_type, False,
            policy_code=code, action="deny_task",
            selected_agents=selection.selected_agents, outcome="refused",
        )
        policy_audit.persist_record(db, denial, now)
        return _refused("I could not answer that safely. Your access level does not allow this request.", denial.policy_code)

    cases = _case_rows(db)
    visible = _scope_rows(context, cases)
    if operation == "case_detail":
        crime_no = payload.get("crime_no")
        case_master_id = payload.get("case_master_id")
        if isinstance(crime_no, str) and crime_no.strip():
            crime_no = crime_no.strip()
            selected = next(
                (row for row in visible if str(row.get("CrimeNo")) == crime_no), None
            )
        elif (
            isinstance(case_master_id, int)
            and not isinstance(case_master_id, bool)
            and case_master_id > 0
        ):
            selected = next(
                (row for row in visible
                 if int(row.get("CaseMasterID")) == case_master_id), None
            )
            crime_no = str(selected.get("CrimeNo")) if selected else ""
        else:
            return _refused("A citation is required for case detail.", "SCOPE_DENIED")
        if selected is None:
            return _refused("That citation is outside your authorised scope.", "SCOPE_DENIED")
        detail_fields = (
            "CaseMasterID", "CrimeNo", "CrimeRegisteredDate", "IncidentFromDate",
            "PoliceStationID", "PolicePersonID", "CrimeMajorHeadID", "CrimeMinorHeadID", "BriefFacts",
            "latitude", "longitude", "DistrictID",
        )
        data = {
            "case": {field: selected.get(field) for field in detail_fields},
            "citations": (crime_no,),
        }
        claims = ("Exact visible CaseMaster evidence was opened for this citation.",)
    elif operation == "network":
        case_id = payload.get("case_master_id")
        if case_id is None:
            return _refused("A case is required for a network view.", "SCOPE_DENIED")
        try:
            case_id = int(case_id)
        except (TypeError, ValueError):
            return _refused("A valid case is required for a network view.", "SCOPE_DENIED")
        if not any(int(row["CaseMasterID"]) == case_id for row in visible):
            return _refused("That case is outside your authorised scope.", "SCOPE_DENIED")
        try:
            hops = min(max(int(payload.get("hops", 2)), 0), 3)
        except (TypeError, ValueError):
            return _refused("The network depth is invalid.", "SCOPE_DENIED")
        data = network_view(
            context, "case:{0}".format(case_id), visible,
            accused_rows=visible,
            arrest_rows=tuple(
                {"CaseMasterID": row["CaseMasterID"], "IOID": employee_id,
                 "Role": role, "CrimeNo": row.get("CrimeNo")}
                for row in visible
                for employee_id, role in (
                    *((row.get("PolicePersonID"), "registering_officer"),),
                    *tuple((ioid, "arrest_io") for ioid in row.get("ArrestIOIDs", ())),
                )
                if employee_id is not None
            ),
            section_rows=tuple(
                {"CaseMasterID": row["CaseMasterID"], "SectionID": section}
                for row in visible for section in row.get("SectionCodes", ())
            ),
            hops=hops,
            derived_edges=GraphProjectionReader(db).load_edges(),
        )
        claims = ("Derived network connections are investigative leads, not proof of guilt.",)
    elif operation == "analytics":
        data = analytics_view(context, visible, analytics_provider=analytics_provider)
        claims = ("Analytics are geographic and temporal decision-support summaries.",)
    elif operation == "profile":
        if payload.get("case_master_id") is None:
            return _refused("A case is required for a profile.", "SCOPE_DENIED")
        selected = visible
        try:
            selected = [row for row in visible if int(row["CaseMasterID"]) == int(payload["case_master_id"])]
        except (TypeError, ValueError):
            return _refused("A valid case is required for a profile.", "SCOPE_DENIED")
        if not selected:
            return _refused("That case is outside your authorised scope.", "SCOPE_DENIED")
        anchor_keys = _profile_keys(selected[0])
        linked = [row for row in visible if anchor_keys.intersection(_profile_keys(row))]
        data = behavioral_profile(linked or selected)
        data["linked_case_ids"] = tuple(row["CaseMasterID"] for row in (linked or selected))
        claims = ("This is a cited decision-support profile, not a person risk score.",)
    else:
        dimension = payload.get("dimension")
        if not isinstance(dimension, str) or dimension not in {
            "AgeYear", "GenderID", "OccupationID", "CasteID", "ReligionID"
        }:
            return _refused("That demographic dimension is not available.", "SCOPE_DENIED")
        demographic_rows = _scope_rows(context, _demographic_rows(db))
        try:
            data = demographic_aggregate(context, demographic_rows, dimension)
        except access.AccessPolicyError as exc:
            return _refused("This demographic view is not permitted for your rank.", exc.code)
        claims = ("Demographics are aggregate-only and never used as a person score.",)

    citations = tuple(data.get("citations", ()))
    evidence_rows = (data["case"],) if operation == "case_detail" else visible

    # The authenticated view is also a supervisor task graph. Domain work is
    # already scoped above; these handlers package its independent evidence
    # producers so the same bounded runtime enforces bundle ownership,
    # required-agent completion, and post-merge composition for every view.
    operation_handlers = {
        "Structured Query Agent": lambda _task, _payload: _operation_bundle(
            "Structured Query Agent", evidence_rows, citations,
            ("RBAC-scoped structured case evidence prepared.",),
            "rbac_scoped_rows", "intelligence-structured-v1",
        ),
        "Narrative Retrieval Agent": lambda _task, _payload: _operation_bundle(
            "Narrative Retrieval Agent", visible, citations,
            ("Visible narrative evidence was included in the view.",),
            "brief_facts_visible", "intelligence-narrative-v1",
        ),
        "Graph Agent": lambda _task, _payload: _operation_bundle(
            "Graph Agent", data.get("edges", ()), citations, claims,
            "derived_graph_edges", "intelligence-graph-v1",
        ),
        "Analytics Agent": lambda _task, _payload: _operation_bundle(
            "Analytics Agent", data.get("trends", ()) + data.get("hotspots", ()),
            citations, claims, "scoped_analytics", "intelligence-analytics-v1",
        ),
        "Graph Agent": lambda _task, _payload: _operation_bundle(
            "Graph Agent",
            data.get("prevention", {}).get("repeat_offender_leads", ()),
            citations,
            ("Command-only repeat-offender leads are investigative leads, not risk scores.",),
            "repeat_offender_graph", "intelligence-prevention-v1",
        ),
    }
    handlers = {
        name: operation_handlers[name]
        for name in task.selected_agents
        if name in operation_handlers
    }
    graph_result = supervisor_runtime.execute_task_graph(
        task, handlers, payload={"operation": operation},
        composer=lambda _merged, _payload: data,
        # SqliteDB is thread-bound; Catalyst ZCQL uses bounded fan-out.
        parallel=supervisor_runtime.parallel_for_backend(db),
    )
    if not graph_result.complete:
        return _refused(
            "The intelligence evidence graph could not complete safely.",
            "SERVICE_UNAVAILABLE",
            graph_result.merged_evidence.limitations,
        )
    merged = graph_result.merged_evidence
    return {
        "refused": False,
        "answer": "Intelligence view ready.",
        "data": _jsonable(data),
        "citations": list(citations),
        "policy_code": "",
        "evidence": {
            "status": merged.status,
            "claims": list(merged.claims),
            "citations": list(merged.citations),
            "limitations": list(merged.limitations),
            "version": merged.index_or_model_version,
        },
    }


def handle_operation(payload, db, today=None, analytics_provider=None):
    """Return a bounded refusal when the Data Store is unavailable."""
    try:
        return _handle_operation(payload, db, today, analytics_provider)
    except DBError:
        return _refused(
            "The intelligence service is temporarily unavailable.",
            "SERVICE_UNAVAILABLE",
            ("The scoped Data Store read could not be completed.",),
        )
