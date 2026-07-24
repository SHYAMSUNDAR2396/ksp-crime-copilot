"""Capability-gated graph and analytics service boundary."""
import math
from dataclasses import asdict

try:
    from . import access
    from .access import require_capability
    from .analytics import dbscan_hotspots, early_warning, prevention_brief, series_warnings, trend_rollup
    from .graph import build_derived_edges, network_metrics, person_resolution_key, traverse
except ImportError:  # pragma: no cover
    import access
    from access import require_capability
    from analytics import dbscan_hotspots, early_warning, prevention_brief, series_warnings, trend_rollup
    from graph import build_derived_edges, network_metrics, person_resolution_key, traverse


COMMAND_BUCKETS = frozenset(("SP_COMMAND", "DGP_STATEWIDE"))


def _profile_keys(row):
    profiles = row.get("AccusedProfiles") or ()
    if not profiles and row.get("AccusedName"):
        profiles = ((row.get("AccusedName"), row.get("AgeYear"), row.get("GenderID")),)
    keys = set()
    for profile in profiles:
        if len(profile) < 3:
            continue
        name, age, gender = profile[:3]
        try:
            age_band = int(age) // 3
        except (TypeError, ValueError):
            age_band = -1
        keys.add((person_resolution_key(name), age_band, str(gender or "")))
    return keys


def _profile_names(row):
    profiles = row.get("AccusedProfiles") or ()
    if profiles:
        return tuple(str(profile[0]) for profile in profiles if profile and profile[0])
    return (str(row["AccusedName"]),) if row.get("AccusedName") else ()


def _near_hotspot(row, hotspot):
    try:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        hotspot_latitude = float(hotspot.latitude)
        hotspot_longitude = float(hotspot.longitude)
        radius_km = max(0.5, float(hotspot.radius_km))
    except (AttributeError, TypeError, ValueError, KeyError):
        return False
    p1, p2 = math.radians(latitude), math.radians(hotspot_latitude)
    dp = math.radians(hotspot_latitude - latitude)
    dl = math.radians(hotspot_longitude - longitude)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    distance = 6371.0 * 2 * math.atan2(
        math.sqrt(value), math.sqrt(max(0.0, 1 - value))
    )
    return distance <= radius_km


def _repeat_offender_leads(context, visible, hotspots):
    """Return cited repeat-offender leads only to command intelligence roles."""
    if context.access_bucket not in COMMAND_BUCKETS or not context.has("view_graph"):
        return ()
    by_case_id = {
        int(row["CaseMasterID"]): row for row in visible
        if row.get("CaseMasterID") is not None
    }
    profile_keys_by_case = {}
    profile_index = {}
    for row in visible:
        case_id = row.get("CaseMasterID")
        if case_id is None:
            continue
        keys = _profile_keys(row)
        profile_keys_by_case[int(case_id)] = keys
        for profile_key in keys:
            profile_index.setdefault(profile_key, []).append(row)
    leads = {}
    for hotspot in hotspots:
        hotspot_case_ids = tuple(int(case_id) for case_id in hotspot.case_ids)
        for case_id in hotspot_case_ids:
            anchor = by_case_id.get(case_id)
            if anchor is None:
                continue
            for profile_key in profile_keys_by_case.get(case_id, ()):
                matching = tuple(
                    row for row in profile_index.get(profile_key, ())
                    if _near_hotspot(row, hotspot)
                )
                case_ids = tuple(sorted({int(row["CaseMasterID"]) for row in matching}))
                if len(case_ids) < 2:
                    continue
                lead = leads.setdefault(profile_key, {
                    "case_ids": set(), "names": set(), "citations": set(),
                    "hotspot_ids": set(),
                })
                lead["case_ids"].update(case_ids)
                for row in matching:
                    lead["names"].update(_profile_names(row))
                    if row.get("CrimeNo"):
                        lead["citations"].add(str(row["CrimeNo"]))
                lead["hotspot_ids"].add(int(hotspot.cluster_id))
    return tuple(
        {
            "case_ids": tuple(sorted(value["case_ids"])),
            "case_count": len(value["case_ids"]),
            "names": tuple(sorted(value["names"])),
            "citations": tuple(sorted(value["citations"])),
            "hotspot_ids": tuple(sorted(value["hotspot_ids"])),
        }
        for _key, value in sorted(
            leads.items(), key=lambda item: (-len(item[1]["case_ids"]), str(item[0]))
        )
    )


def _case_visible(context, case_rows, case_id):
    row = next((row for row in case_rows if int(row.get("CaseMasterID")) == int(case_id)), None)
    if row is None:
        return False
    station = row.get("PoliceStationID")
    district = row.get("DistrictID")
    return access.in_scope(station, context.unit_ids) and access.in_scope(
        district, context.district_ids
    )


def network_view(context, start_node, cases, accused_rows=(), arrest_rows=(), section_rows=(), hops=2,
                 derived_edges=None):
    require_capability(context, "view_graph")
    if derived_edges is None:
        nodes, edges = build_derived_edges(cases, accused_rows, arrest_rows, section_rows)
    else:
        edges = tuple(derived_edges)
        nodes = tuple(sorted({
            node for edge in edges
            for node in (edge.source, edge.target)
        }))

    def visible(edge):
        case_ids = []
        for value in (edge.source, edge.target):
            if value.startswith("case:"):
                case_ids.append(value.split(":", 1)[1])
        return all(_case_visible(context, cases, case_id) for case_id in case_ids)

    selected_nodes, selected_edges = traverse(start_node, edges, hops=hops, visible=visible)
    metrics = network_metrics(selected_nodes, selected_edges)
    return {
        "nodes": selected_nodes,
        "edges": tuple(asdict(edge) for edge in selected_edges),
        "metrics": metrics,
        "citations": tuple(sorted({
            citation for edge in selected_edges for citation in edge.citations
        })),
        "limitations": ("Derived links are possible investigative connections, not proof of guilt.",),
    }


def analytics_view(context, cases, threshold_ratio=1.25, analytics_provider=None):
    require_capability(context, "query_structured_cases")
    visible = [
        row for row in cases
        if _case_visible(context, cases, row.get("CaseMasterID"))
    ]
    trends = trend_rollup(visible)
    hotspots = dbscan_hotspots(visible)
    warnings = series_warnings(
        trends, threshold_ratio=threshold_ratio, provider=analytics_provider,
    )
    if warnings:
        warning = dict(max(warnings, key=lambda item: item["ratio"]))
        warning["warning"] = any(item["warning"] for item in warnings)
        warning["series"] = warnings
    else:
        warning = early_warning((), threshold_ratio=threshold_ratio)
        warning["series"] = ()
    prevention = dict(prevention_brief(warning, hotspots))
    prevention["repeat_offender_leads"] = _repeat_offender_leads(
        context, visible, hotspots,
    )
    citations = set(
        citation for point in trends for citation in point.citations
    )
    for lead in prevention["repeat_offender_leads"]:
        citations.update(lead["citations"])
    return {
        "trends": tuple(asdict(point) for point in trends),
        "hotspots": tuple(asdict(hotspot) for hotspot in hotspots),
        "warning": warning,
        "prevention": prevention,
        "citations": tuple(sorted(citations)),
    }
