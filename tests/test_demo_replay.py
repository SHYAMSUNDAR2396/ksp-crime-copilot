import json

from tools.demo_replay import build_replay


def test_demo_replay_exercises_all_nine_beats(tmp_path):
    output = build_replay(tmp_path / "crime.db")

    assert output["synthetic_data"] is True
    assert output["summary"] == {"passed": 9, "failed": 0}
    assert [beat["id"] for beat in output["beats"]] == list(range(1, 10))
    assert all(beat["ok"] for beat in output["beats"])
    assert output["beats"][0]["details"]["citations_match"] is True
    assert output["beats"][8]["details"]["status"] == "Linked"


def test_demo_replay_can_be_serialised_without_runtime_objects(tmp_path):
    output = build_replay(tmp_path / "crime.db")

    encoded = json.dumps(output, ensure_ascii=False)
    assert "<sqlite3" not in encoded
    assert "provider" not in encoded.lower()
    assert "secret" not in encoded.lower()
