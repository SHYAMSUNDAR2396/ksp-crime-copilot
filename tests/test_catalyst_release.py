from tools import catalyst_release


def _live_report(ok=True):
    return {
        "ok": ok,
        "live_ready": ok,
        "warnings": [] if ok else [{"name": "catalyst_cli"}],
        "failures": [] if ok else [{"name": "catalyst_cli"}],
    }


def test_release_fails_before_packaging_when_live_gate_is_incomplete(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(catalyst_release, "run_preflight", lambda *_args, **_kwargs: _live_report(False))
    monkeypatch.setattr(catalyst_release, "prepare", lambda *_args, **_kwargs: calls.append("prepare"))

    report = catalyst_release.run_release(tmp_path, deploy=True)

    assert report["ok"] is False
    assert report["failures"] == ["catalyst_cli"]
    assert report["deploy_status"] == "not_started"
    assert calls == []


def test_release_check_only_prepares_package_without_deploying(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(catalyst_release, "run_preflight", lambda *_args, **_kwargs: _live_report())
    monkeypatch.setattr(catalyst_release, "prepare", lambda *_args, **_kwargs: calls.append("prepare"))
    runner = lambda *_args, **_kwargs: calls.append("deploy")

    report = catalyst_release.run_release(tmp_path, runner=runner)

    assert report == {
        "ok": True,
        "live_ready": True,
        "prepared": True,
        "deployed": False,
        "deploy_status": "not_requested",
        "failures": [],
    }
    assert calls == ["prepare"]


def test_release_deploys_only_after_preflight_and_packaging(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(catalyst_release, "run_preflight", lambda *_args, **_kwargs: _live_report())
    monkeypatch.setattr(catalyst_release, "prepare", lambda *_args, **_kwargs: calls.append("prepare"))

    class Completed:
        returncode = 0

    def runner(command, **_kwargs):
        calls.append(command)
        return Completed()

    report = catalyst_release.run_release(
        tmp_path, project="crime-copilot", deploy=True, runner=runner,
    )

    assert report["ok"] is True
    assert report["deployed"] is True
    assert report["deploy_status"] == "passed"
    assert calls == [
        "prepare", [
            "catalyst", "--non-interactive", "--project", "crime-copilot", "deploy",
        ],
    ]
