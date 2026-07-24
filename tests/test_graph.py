from functions.crime_query.graph import (
    build_derived_edges,
    network_metrics,
    normalize_person_name,
    person_resolution_key,
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


def test_person_resolution_links_initial_variant_with_cautious_confidence():
    rows = [
        {"CaseMasterID": 1, "CrimeNo": "FIR/1", "AccusedName": "Ravi Kumar",
         "AgeYear": 30, "GenderID": 1},
        {"CaseMasterID": 2, "CrimeNo": "FIR/2", "AccusedName": "Ravi K.",
         "AgeYear": 31, "GenderID": 1},
    ]

    nodes, edges = build_derived_edges(cases()[:2], rows)

    assert person_resolution_key("Ravi Kumar") == person_resolution_key("Ravi K.")
    assert len(nodes) == 1
    assert nodes[0].confidence == 0.85
    assert all(
        edge.confidence == 0.85
        for edge in edges if edge.edge_type == "same_person_in"
    )


def test_near_edge_bucket_index_preserves_exact_radius_and_date_filter():
    rows = [
        dict(cases()[0], CaseMasterID=1, CrimeNo="FIR/1"),
        dict(cases()[1], CaseMasterID=2, CrimeNo="FIR/2"),
        dict(cases()[2], CaseMasterID=3, CrimeNo="FIR/3",
             CrimeRegisteredDate="2027-06-03"),
    ]

    _nodes, edges = build_derived_edges(rows, near_radius_km=0.5, near_days=30)

    assert [(edge.source, edge.target) for edge in edges if edge.edge_type == "near"] == [
        ("case:1", "case:2"),
    ]


def test_near_edges_traverse_and_network_metrics_are_cited():
    nodes, edges = build_derived_edges(cases())
    near = [edge for edge in edges if edge.edge_type == "near"]
    assert near and near[0].citations == ("FIR/1", "FIR/2")
    visible_nodes, visible_edges = traverse("case:1", edges, hops=1)
    assert "case:2" in visible_nodes
    metrics = network_metrics(visible_nodes, visible_edges)
    assert metrics["degree"]["case:1"] >= 1
    assert metrics["community"]["case:1"] == metrics["community"]["case:2"]


def test_person_resolution_preserves_complainant_and_victim_roles():
    rows = [{
        "CaseMasterID": 1,
        "CrimeNo": "FIR/1",
        "PersonProfiles": (
            ("Anita Rao", "31", "2", "complainant"),
            ("Ravi Kumar", "30", "1", "accused"),
        ),
    }]

    _nodes, edges = build_derived_edges(cases()[:1], rows)

    roles = {
        dict(edge.attributes)["role"] for edge in edges
        if edge.edge_type == "same_person_in"
    }
    assert roles == {"complainant", "accused"}
