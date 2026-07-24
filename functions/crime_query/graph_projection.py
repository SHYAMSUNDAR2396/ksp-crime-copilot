"""Versioned persistence for the derived relationship graph.

The authoritative FIR schema remains unchanged.  This projection stores only
derived, explainable relationship records so Catalyst Jobs can rebuild the
graph independently of interactive requests and roll back by version.
"""
import datetime as dt
import re
from dataclasses import dataclass

try:
    from .graph import (
        DerivedEdge,
        build_derived_edges,
        normalize_person_name,
        person_node_id,
        person_resolution_key,
    )
except ImportError:  # pragma: no cover
    from graph import (
        DerivedEdge,
        build_derived_edges,
        normalize_person_name,
        person_node_id,
        person_resolution_key,
    )


VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
PROJECTION_NAME = "relationship_graph"


@dataclass(frozen=True)
class GraphProjectionResult:
    projection_version: str
    nodes_written: int
    members_written: int
    edges_written: int


def _version(value):
    value = str(value or "").strip()
    if not VERSION_RE.fullmatch(value):
        raise ValueError("a valid graph projection version is required")
    return value


def _now(value=None):
    return value or dt.datetime.now(dt.timezone.utc).isoformat()


def _profiles(case):
    profiles = case.get("PersonProfiles") or case.get("AccusedProfiles") or ()
    if profiles:
        return tuple(profiles)
    if case.get("AccusedName"):
        return ((case["AccusedName"], case.get("AgeYear"), case.get("GenderID")),)
    return ()


def _profile_parts(profile):
    if len(profile) == 4:
        name, age, gender, role = profile
    else:
        name, age, gender = profile
        role = "accused"
    return str(name or ""), age, gender, str(role or "accused")


def build_projection_records(cases, projection_version="graph-v1", now=None):
    """Return graph rows ready for a Catalyst/SQLite operational adapter."""
    version = _version(projection_version)
    timestamp = _now(now)
    rows = tuple(cases or ())
    case_by_id = {
        int(case["CaseMasterID"]): case
        for case in rows if case.get("CaseMasterID") is not None
    }
    arrest_rows = tuple(
        {
            "CaseMasterID": case["CaseMasterID"],
            "IOID": employee_id,
            "CrimeNo": case.get("CrimeNo"),
            "Role": role,
        }
        for case in rows
        for employee_id, role in (
            *((case.get("PolicePersonID"), "registering_officer"),),
            *tuple((ioid, "arrest_io") for ioid in case.get("ArrestIOIDs", ()) or ()),
        )
        if employee_id is not None
    )
    section_rows = tuple(
        {
            "CaseMasterID": case["CaseMasterID"],
            "SectionID": section,
            "CrimeNo": case.get("CrimeNo"),
        }
        for case in rows
        for section in case.get("SectionCodes", ()) or ()
    )
    nodes, edges = build_derived_edges(
        rows, accused_rows=rows, arrest_rows=arrest_rows,
        section_rows=section_rows,
    )

    node_rows = []
    for node in nodes:
        node_rows.append({
            "NodeID": node.node_id,
            "NormalizedName": node.normalized_name,
            "AgeBand": node.age_band,
            "GenderID": str(node.gender_id) if node.gender_id is not None else "",
            "Confidence": node.confidence,
            "ResolutionVersion": version,
            "UpdatedAt": timestamp,
        })

    member_rows = []
    seen_members = set()
    for case_id, case in case_by_id.items():
        crime_no = str(case.get("CrimeNo") or "")
        for profile in _profiles(case):
            name, age, gender, role = _profile_parts(profile)
            normalized = normalize_person_name(name)
            if not normalized:
                continue
            node_id = person_node_id(name, age, gender)
            key = (node_id, case_id, role, version)
            if key in seen_members:
                continue
            seen_members.add(key)
            member_rows.append({
                "NodeID": node_id,
                "CaseMasterID": case_id,
                "Role": role,
                "SourceName": name,
                "AgeYear": age,
                "GenderID": str(gender) if gender is not None else "",
                "SourceCrimeNo": crime_no,
                "ResolutionVersion": version,
                "UpdatedAt": timestamp,
            })

    edge_rows = {
        "EdgePersonCase": [],
        "EdgeCaseEmployee": [],
        "EdgeCaseSection": [],
        "EdgeCaseNear": [],
    }
    seen_edges = set()
    for edge in edges:
        attrs = dict(edge.attributes)
        source = str(edge.source)
        target = str(edge.target)
        if edge.edge_type == "same_person_in":
            if not source.startswith("person:") or not target.startswith("case:"):
                continue
            key = (source, int(target.split(":", 1)[1]), attrs.get("role", "accused"), version)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge_rows["EdgePersonCase"].append({
                "NodeID": source,
                "CaseMasterID": key[1],
                "Role": key[2],
                "Confidence": edge.confidence,
                "SourceCrimeNo": edge.citations[0] if edge.citations else str(
                    case_by_id.get(key[1], {}).get("CrimeNo") or ""
                ),
                "ResolutionVersion": version,
                "UpdatedAt": timestamp,
            })
        elif edge.edge_type == "investigated_by":
            if not source.startswith("case:") or not target.startswith("employee:"):
                continue
            case_id = int(source.split(":", 1)[1])
            employee_id = int(target.split(":", 1)[1])
            key = (case_id, employee_id, attrs.get("role", "investigating_officer"), version)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge_rows["EdgeCaseEmployee"].append({
                "CaseMasterID": case_id,
                "EmployeeID": employee_id,
                "Role": key[2],
                "Confidence": edge.confidence,
                "SourceCrimeNo": edge.citations[0] if edge.citations else str(
                    case_by_id.get(case_id, {}).get("CrimeNo") or ""
                ),
                "ResolutionVersion": version,
                "UpdatedAt": timestamp,
            })
        elif edge.edge_type == "charged_under":
            if not source.startswith("case:") or not target.startswith("section:"):
                continue
            case_id = int(source.split(":", 1)[1])
            section_id = target.split(":", 1)[1]
            key = (case_id, section_id, version)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge_rows["EdgeCaseSection"].append({
                "CaseMasterID": case_id,
                "SectionID": section_id,
                "Confidence": edge.confidence,
                "SourceCrimeNo": edge.citations[0] if edge.citations else str(
                    case_by_id.get(case_id, {}).get("CrimeNo") or ""
                ),
                "ResolutionVersion": version,
                "UpdatedAt": timestamp,
            })
        elif edge.edge_type == "near":
            if not source.startswith("case:") or not target.startswith("case:"):
                continue
            left = int(source.split(":", 1)[1])
            right = int(target.split(":", 1)[1])
            key = (min(left, right), max(left, right), version)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge_rows["EdgeCaseNear"].append({
                "CaseMasterID": key[0],
                "RelatedCaseID": key[1],
                "DistanceKm": float(attrs.get("distance_km", 0.0)),
                "Confidence": edge.confidence,
                "SourceCrimeNos": ",".join(str(value) for value in edge.citations),
                "ResolutionVersion": version,
                "UpdatedAt": timestamp,
            })

    return {
        "version": version,
        "nodes": tuple(node_rows),
        "members": tuple(member_rows),
        "edges": {
            table: tuple(values) for table, values in edge_rows.items()
        },
        "timestamp": timestamp,
    }


class GraphProjectionStore:
    """Idempotent versioned writer over the fixed operational DB surface."""

    _TABLE_KEYS = {
        "PersonNode": ("NodeID", "ResolutionVersion"),
        "PersonMember": ("NodeID", "CaseMasterID", "Role", "ResolutionVersion"),
        "EdgePersonCase": ("NodeID", "CaseMasterID", "Role", "ResolutionVersion"),
        "EdgeCaseEmployee": ("CaseMasterID", "EmployeeID", "Role", "ResolutionVersion"),
        "EdgeCaseSection": ("CaseMasterID", "SectionID", "ResolutionVersion"),
        "EdgeCaseNear": ("CaseMasterID", "RelatedCaseID", "ResolutionVersion"),
    }

    def __init__(self, db):
        self.db = db

    def _upsert(self, table, row):
        filters = {key: row[key] for key in self._TABLE_KEYS[table]}
        existing = self.db.read_operational(table, filters)
        if existing:
            self.db.update_operational(table, existing[0]["ROWID"], row)
        else:
            self.db.insert_operational(table, row)
        return 1

    def write(self, projection):
        counts = {
            "PersonNode": sum(self._upsert("PersonNode", row) for row in projection["nodes"]),
            "PersonMember": sum(self._upsert("PersonMember", row) for row in projection["members"]),
        }
        for table, rows in projection["edges"].items():
            counts[table] = sum(self._upsert(table, row) for row in rows)
        state = {
            "ProjectionName": PROJECTION_NAME,
            "ActiveVersion": projection["version"],
            "UpdatedAt": projection["timestamp"],
        }
        existing = self.db.read_operational("GraphProjectionState", {
            "ProjectionName": PROJECTION_NAME,
        })
        if existing:
            self.db.update_operational("GraphProjectionState", existing[0]["ROWID"], state)
        else:
            self.db.insert_operational("GraphProjectionState", state)
        return GraphProjectionResult(
            projection_version=projection["version"],
            nodes_written=counts["PersonNode"],
            members_written=counts["PersonMember"],
            edges_written=sum(counts[table] for table in projection["edges"]),
        )


class GraphProjectionReader:
    """Read the active version without exposing projection internals to NL."""

    def __init__(self, db):
        self.db = db

    def active_version(self):
        rows = self.db.read_operational(
            "GraphProjectionState", {"ProjectionName": PROJECTION_NAME}
        )
        if not rows:
            return None
        value = str(rows[0].get("ActiveVersion") or "").strip()
        return value or None

    def load_edges(self):
        version = self.active_version()
        if not version:
            return None
        edges = []
        for row in self.db.read_operational(
            "EdgePersonCase", {"ResolutionVersion": version}
        ):
            try:
                edges.append({
                    "edge_type": "same_person_in",
                    "source": str(row["NodeID"]),
                    "target": "case:{}".format(int(row["CaseMasterID"])),
                    "confidence": float(row["Confidence"]),
                    "citations": (str(row["SourceCrimeNo"]),) if row.get("SourceCrimeNo") else (),
                    "attributes": (("role", str(row.get("Role") or "accused")),),
                })
            except (KeyError, TypeError, ValueError):
                continue
        for row in self.db.read_operational(
            "EdgeCaseEmployee", {"ResolutionVersion": version}
        ):
            try:
                edges.append({
                    "edge_type": "investigated_by",
                    "source": "case:{}".format(int(row["CaseMasterID"])),
                    "target": "employee:{}".format(int(row["EmployeeID"])),
                    "confidence": float(row["Confidence"]),
                    "citations": (str(row["SourceCrimeNo"]),) if row.get("SourceCrimeNo") else (),
                    "attributes": (("role", str(row.get("Role") or "investigating_officer")),),
                })
            except (KeyError, TypeError, ValueError):
                continue
        for row in self.db.read_operational(
            "EdgeCaseSection", {"ResolutionVersion": version}
        ):
            try:
                edges.append({
                    "edge_type": "charged_under",
                    "source": "case:{}".format(int(row["CaseMasterID"])),
                    "target": "section:{}".format(row["SectionID"]),
                    "confidence": float(row["Confidence"]),
                    "citations": (str(row["SourceCrimeNo"]),) if row.get("SourceCrimeNo") else (),
                    "attributes": (("role", "charged_under"),),
                })
            except (KeyError, TypeError, ValueError):
                continue
        for row in self.db.read_operational(
            "EdgeCaseNear", {"ResolutionVersion": version}
        ):
            try:
                citations = tuple(
                    value for value in str(row.get("SourceCrimeNos") or "").split(",")
                    if value
                )
                edges.append({
                    "edge_type": "near",
                    "source": "case:{}".format(int(row["CaseMasterID"])),
                    "target": "case:{}".format(int(row["RelatedCaseID"])),
                    "confidence": float(row["Confidence"]),
                    "citations": citations,
                    "attributes": (("distance_km", float(row["DistanceKm"])),),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(DerivedEdge(**edge) for edge in edges)


class GraphProjectionJob:
    def __init__(self, db, cases, projection_version="graph-v1", clock=None):
        self.db = db
        self.cases = tuple(cases or ())
        self.projection_version = projection_version
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc).isoformat())

    def run(self):
        projection = build_projection_records(
            self.cases, self.projection_version, self.clock()
        )
        return GraphProjectionStore(self.db).write(projection)
