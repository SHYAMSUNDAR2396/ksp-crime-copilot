from tools import demo_check


def test_demo_check_combines_replay_and_catalyst_artifact_status(tmp_path, monkeypatch):
    monkeypatch.setattr(
        demo_check,
        "build_replay",
        lambda _path: {"summary": {"passed": 9, "failed": 0}},
    )
    monkeypatch.setattr(
        demo_check,
        "run_preflight",
        lambda _root: {
            "ok": True,
            "live_ready": False,
            "warnings": [{"name": "catalyst_cli"}],
            "failures": [],
        },
    )

    report = demo_check.run_demo_check(tmp_path, tmp_path / "demo.db", tmp_path / "replay.json")

    assert report == {
        "ok": True,
        "demo": {"passed": 9, "failed": 0},
        "catalyst": {
            "artifacts_ok": True,
            "live_ready": False,
            "warnings": ["catalyst_cli"],
            "failures": [],
        },
    }
