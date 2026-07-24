"""Schema-grounded derived graph and network analysis.

The source schema has no cross-case person key, so links are derived from
Accused name, age band, and gender. Sensitive demographic fields are never
read by this module.
"""
import datetime as dt
import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonNode:
    node_id: str
    normalized_name: str
    age_band: int
    gender_id: object
    confidence: float


@dataclass(frozen=True)
class DerivedEdge:
    edge_type: str
    source: str
    target: str
    confidence: float
    citations: tuple
    attributes: tuple = ()


def normalize_person_name(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def person_resolution_key(value):
    """Create a cautious key that makes full names and initials comparable."""
    normalized = normalize_person_name(value)
    tokens = normalized.split()
    if len(tokens) <= 1:
        return normalized
    return "{} {}".format(tokens[0], " ".join(token[0] for token in tokens[1:]))


def _age_band(value):
    try:
        return int(value) // 3
    except (TypeError, ValueError):
        return -1


def _node_id(name, age_band, gender_id):
    raw = "{}|{}|{}".format(name, age_band, gender_id or "")
    return "person:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def person_node_id(value, age, gender_id):
    """Return the stable identifier used by the persisted graph projection."""
    return _node_id(person_resolution_key(value), _age_band(age), gender_id)


def resolve_person_nodes(accused_rows):
    """Return deterministic nodes and accused-to-node membership edges."""
    nodes = {}
    edges = []
    for row in accused_rows or ():
        profiles = row.get("PersonProfiles") or row.get("AccusedProfiles") or ()
        if not profiles and row.get("AccusedName"):
            profiles = ((row.get("AccusedName"), row.get("AgeYear"), row.get("GenderID")),)
        for profile in profiles:
            if len(profile) == 4:
                name_value, age_value, gender, role = profile
            else:
                name_value, age_value, gender = profile
                role = "accused"
            name = normalize_person_name(name_value)
            if not name:
                continue
            age_band = _age_band(age_value)
            resolution_name = person_resolution_key(name)
            node_id = _node_id(resolution_name, age_band, gender)
            confidence = 1.0 if resolution_name == name else 0.85
            prior = nodes.get(node_id)
            if prior is None or confidence < prior.confidence:
                nodes[node_id] = PersonNode(
                    node_id, resolution_name, age_band, gender, confidence,
                )
            case_id = row.get("CaseMasterID")
            if case_id is not None:
                edge_confidence = nodes[node_id].confidence
                edges.append(DerivedEdge(
                    "same_person_in", node_id, "case:{}".format(case_id), edge_confidence,
                    (str(row.get("CrimeNo", "")),) if row.get("CrimeNo") else (),
                    (("role", str(role)),),
                ))
    return tuple(nodes.values()), tuple(edges)


def _date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _distance_km(left, right):
    try:
        lat1, lon1 = float(left["latitude"]), float(left["longitude"])
        lat2, lon2 = float(right["latitude"]), float(right["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def build_derived_edges(cases, accused_rows=(), arrest_rows=(), section_rows=(),
                        near_radius_km=0.5, near_days=30):
    """Build explainable graph edges from schema-shaped dictionaries."""
    if near_radius_km <= 0 or near_days < 1:
        raise ValueError("near radius and date window must be positive")
    cases = list(cases or ())
    nodes, person_edges = resolve_person_nodes(accused_rows)
    edges = list(person_edges)
    for row in arrest_rows or ():
        case_id, employee_id = row.get("CaseMasterID"), row.get("IOID")
        if case_id is not None and employee_id is not None:
            edges.append(DerivedEdge("investigated_by", "case:{}".format(case_id),
                                     "employee:{}".format(employee_id), 1.0,
                                     (str(row.get("CrimeNo")),) if row.get("CrimeNo") else (),
                                     (("role", str(row.get("Role", "investigating_officer"))),)))
    for row in section_rows or ():
        case_id = row.get("CaseMasterID")
        section = row.get("SectionID", row.get("SectionCode"))
        if case_id is not None and section is not None:
            edges.append(DerivedEdge("charged_under", "case:{}".format(case_id),
                                     "section:{}".format(section), 1.0,
                                     (str(row.get("CrimeNo")),) if row.get("CrimeNo") else (),
                                     (("role", "charged_under"),)))

    # Spatial and temporal buckets avoid comparing every case to every other
    # case. Neighboring buckets are sufficient because a bucket is smaller
    # than the configured radius and date window; the exact Haversine/date
    # checks below remain authoritative.
    cell_size = max(near_radius_km / 100.0, 0.000001)
    buckets = {}
    dated_points = []
    for index, row in enumerate(cases):
        try:
            latitude, longitude = float(row["latitude"]), float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        case_date = _date(row.get("CrimeRegisteredDate"))
        if case_date is None:
            continue
        bucket = (
            math.floor(latitude / cell_size),
            math.floor(longitude / cell_size),
            case_date.toordinal() // near_days,
        )
        buckets.setdefault(bucket, []).append(index)
        dated_points.append((index, latitude, longitude, case_date))

    near_edges = []
    seen_pairs = set()
    for left_index, _latitude, _longitude, left_date in dated_points:
        left = cases[left_index]
        left_bucket = (
            math.floor(float(left["latitude"]) / cell_size),
            math.floor(float(left["longitude"]) / cell_size),
            left_date.toordinal() // near_days,
        )
        for lat_bucket in range(left_bucket[0] - 1, left_bucket[0] + 2):
            for lon_bucket in range(left_bucket[1] - 1, left_bucket[1] + 2):
                for date_bucket in range(left_bucket[2] - 1, left_bucket[2] + 2):
                    for right_index in buckets.get((lat_bucket, lon_bucket, date_bucket), ()):
                        if right_index <= left_index or (left_index, right_index) in seen_pairs:
                            continue
                        seen_pairs.add((left_index, right_index))
                        right = cases[right_index]
                        distance = _distance_km(left, right)
                        right_date = _date(right.get("CrimeRegisteredDate"))
                        if (distance is None or right_date is None
                                or distance > near_radius_km
                                or abs((left_date - right_date).days) > near_days):
                            continue
                        citations = tuple(
                            value for value in (left.get("CrimeNo"), right.get("CrimeNo"))
                            if value
                        )
                        confidence = round(
                            max(0.0, 1.0 - distance / max(near_radius_km, 0.001)), 3
                        )
                        near_edges.append(DerivedEdge(
                            "near", "case:{}".format(left["CaseMasterID"]),
                            "case:{}".format(right["CaseMasterID"]), confidence,
                            citations, (("distance_km", round(distance, 3)),),
                        ))
    edges.extend(near_edges)
    return nodes, tuple(edges)


def traverse(start, edges, hops=2, visible=None):
    """Return a bounded undirected neighborhood with original edge citations."""
    if hops < 0:
        raise ValueError("hops must be non-negative")
    visible = visible or (lambda edge: True)
    adjacency = {}
    for edge in edges:
        if not visible(edge):
            continue
        adjacency.setdefault(edge.source, []).append(edge)
        adjacency.setdefault(edge.target, []).append(edge)
    seen = {start}
    frontier = {start}
    selected = []
    for _ in range(hops):
        next_frontier = set()
        for node in frontier:
            for edge in adjacency.get(node, ()):
                if edge not in selected:
                    selected.append(edge)
                other = edge.target if edge.source == node else edge.source
                if other not in seen:
                    seen.add(other)
                    next_frontier.add(other)
        frontier = next_frontier
    return tuple(sorted(seen)), tuple(selected)


def network_metrics(nodes, edges):
    """Compute explainable degree, connected community, and centrality data."""
    adjacency = {node: set() for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
        adjacency.setdefault(edge.target, set()).add(edge.source)
    communities = []
    remaining = set(adjacency)
    while remaining:
        root = min(remaining)
        component, stack = set(), [root]
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(adjacency.get(node, ()) - component)
        remaining -= component
        communities.append(tuple(sorted(component)))
    community_for = {node: index for index, group in enumerate(communities) for node in group}
    return {
        "degree": {node: len(neighbors) for node, neighbors in adjacency.items()},
        "centrality": {
            node: round(len(neighbors) / max(1, len(adjacency) - 1), 6)
            for node, neighbors in adjacency.items()
        },
        "community": community_for,
        "communities": tuple(communities),
    }
