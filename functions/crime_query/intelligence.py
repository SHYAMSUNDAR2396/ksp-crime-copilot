"""Capability-gated graph and analytics service boundary."""
from dataclasses import asdict

try:
    from .access import require_capability
    from .analytics import dbscan_hotspots, early_warning, prevention_brief, series_warnings, trend_rollup
    from .graph import build_derived_edges, network_metrics, traverse
except ImportError:  # pragma: no cover
    from access import require_capability
    from analytics import dbscan_hotspots, early_warning, prevention_brief, series_warnings, trend_rollup
    from graph import build_derived_edges, network_metrics, traverse


def _case_visible(context, case_rows, case_id):
    row = next((row for row in case_rows if int(row.get("CaseMasterID")) == int(case_id)), None)
    if row is None:
        return False
    station = row.get("PoliceStationID")
    district = row.get("DistrictID")
    return (
        station is not None and district is not None
        and (context.unit_ids is None or station in context.unit_ids)
        and (context.district_ids is None or district in context.district_ids)
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


def analytics_view(context, cases, threshold_ratio=1.25):
    require_capability(context, "query_structured_cases")
    visible = [
        row for row in cases
        if _case_visible(context, cases, row.get("CaseMasterID"))
    ]
    trends = trend_rollup(visible)
    hotspots = dbscan_hotspots(visible)
    warnings = series_warnings(trends, threshold_ratio=threshold_ratio)
    if warnings:
        warning = dict(max(warnings, key=lambda item: item["ratio"]))
        warning["warning"] = any(item["warning"] for item in warnings)
        warning["series"] = warnings
    else:
        warning = early_warning((), threshold_ratio=threshold_ratio)
        warning["series"] = ()
    return {
        "trends": tuple(asdict(point) for point in trends),
        "hotspots": tuple(asdict(hotspot) for hotspot in hotspots),
        "warning": warning,
        "prevention": prevention_brief(warning, hotspots),
        "citations": tuple(sorted({
            citation for point in trends for citation in point.citations
        })),
    }
