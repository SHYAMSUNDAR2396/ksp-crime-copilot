from functions.crime_query.graph import (
    build_derived_edges,
    network_metrics,
    normalize_person_name,
    traverse,
)


def cases():
    return [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "CrimeRegisteredDate": "2026-06-01", "latitude": 12.9716, "longitude": 77.5946},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "CrimeRegisteredDate": "2026-06-02", "latitude": 12.9718, "longitude": 77.5947},
        {"CaseMasterID": 3, "CrimeNo": "FIR/3", "CrimeRegisteredDate": "2026-06-03", "latitude": 12.9719, "longitude": 77.5948},
    ]


def test_person_resolution_is_deterministic_and_does_not_use_sensitive_fields():
    rows = [{"CaseMasterID": 1, "CrimeNo": "FIR/1", "AccusedName": "Ravi K.", "AgeYear": 30, "GenderID": 1, "CasteID": "secret"},
            {"CaseMasterID": 2, "CrimeNo": "FIR/2", "AccusedName": "Ravi K", "AgeYear": 32, "GenderID": 1, "ReligionID": "secret"}]
    nodes, edges = build_derived_edges(cases()[:2], rows)
    assert normalize_person_name("Ravi K.") == "ravi k"
    assert len(nodes) == 1
    assert all("secret" not in repr(item) for item in nodes + edges)


def test_near_edges_traverse_and_network_metrics_are_cited():
    nodes, edges = build_derived_edges(cases())
    near = [edge for edge in edges if edge.edge_type == "near"]
    assert near and near[0].citations == ("FIR/1", "FIR/2")
    visible_nodes, visible_edges = traverse("case:1", edges, hops=1)
    assert "case:2" in visible_nodes
    metrics = network_metrics(visible_nodes, visible_edges)
    assert metrics["degree"]["case:1"] >= 1
    assert metrics["community"]["case:1"] == metrics["community"]["case:2"]
