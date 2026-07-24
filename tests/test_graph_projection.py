import datetime as dt

from functions.crime_query import db as db_module
from functions.crime_query.graph_projection import (
    GraphProjectionJob,
    GraphProjectionReader,
    build_projection_records,
)
from tools import gen_data


def _cases():
    return [
        {
            "CaseMasterID": 1,
            "CrimeNo": "FIR/1",
            "CrimeRegisteredDate": "2026-06-01",
            "PolicePersonID": 8,
            "PersonProfiles": (("Ravi Kumar", 30, 1, "accused"),),
            "ArrestIOIDs": (9,),
            "SectionCodes": ("379",),
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        {
            "CaseMasterID": 2,
            "CrimeNo": "FIR/2",
            "CrimeRegisteredDate": "2026-06-10",
            "PolicePersonID": 10,
            "PersonProfiles": (("Ravi K", 31, 1, "accused"),),
            "ArrestIOIDs": (11,),
            "SectionCodes": ("379",),
            "latitude": 12.9717,
            "longitude": 77.5947,
        },
    ]


def test_projection_is_versioned_and_preserves_provenance():
    projection = build_projection_records(_cases(), "graph-v1", "2026-07-23T00:00:00Z")

    assert len(projection["nodes"]) == 1
    assert len(projection["members"]) == 2
    assert projection["nodes"][0]["ResolutionVersion"] == "graph-v1"
    assert projection["edges"]["EdgePersonCase"][0]["SourceCrimeNo"] in {"FIR/1", "FIR/2"}
    assert projection["edges"]["EdgeCaseEmployee"]
    assert projection["edges"]["EdgeCaseSection"]
    assert projection["edges"]["EdgeCaseNear"][0]["SourceCrimeNos"] == "FIR/1,FIR/2"


def test_projection_job_is_idempotent_and_rolls_forward_versions(tmp_path):
    path = tmp_path / "crime.db"
    gen_data.build(str(path))
    db = db_module.SqliteDB(str(path))
    try:
        first = GraphProjectionJob(
            db, _cases(), "graph-v1",
            clock=lambda: "2026-07-23T00:00:00Z",
        ).run()
        second = GraphProjectionJob(
            db, _cases(), "graph-v1",
            clock=lambda: "2026-07-23T00:00:01Z",
        ).run()
        rolled = GraphProjectionJob(
            db, _cases(), "graph-v2",
            clock=lambda: "2026-07-23T00:00:02Z",
        ).run()

        assert first.nodes_written == second.nodes_written == 1
        assert first.members_written == second.members_written == 2
        assert rolled.projection_version == "graph-v2"
        assert len(db.read_operational("PersonNode", {"ResolutionVersion": "graph-v1"})) == 1
        assert len(db.read_operational("PersonNode", {"ResolutionVersion": "graph-v2"})) == 1
        state = db.read_operational("GraphProjectionState", {"ProjectionName": "relationship_graph"})
        assert state[0]["ActiveVersion"] == "graph-v2"
        edges = GraphProjectionReader(db).load_edges()
        assert edges
        assert any(edge.edge_type == "same_person_in" for edge in edges)
        assert all(edge.citations for edge in edges if edge.edge_type != "investigated_by")
    finally:
        db.close()


def test_projection_rejects_unsafe_version():
    try:
        build_projection_records(_cases(), "graph v1")
    except ValueError as exc:
        assert "version" in str(exc)
    else:
        raise AssertionError("unsafe projection version was accepted")
