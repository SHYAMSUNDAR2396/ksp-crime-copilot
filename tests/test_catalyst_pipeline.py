from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_catalyst_pipeline_has_a_safe_verification_stage():
    manifest = yaml.safe_load((ROOT / "catalyst-pipelines.yaml").read_text(encoding="utf-8"))

    assert manifest["version"] == 1
    assert [stage["name"] for stage in manifest["stages"]] == ["verify"]
    assert manifest["stages"][0]["jobs"] == ["offline_verification"]
    steps = manifest["jobs"]["offline_verification"]["steps"]
    assert any("pytest" in step for step in steps)
    assert any("catalyst_preflight" in step for step in steps)
    assert any("demo_replay" in step for step in steps)
    assert all("--require-live" not in step for step in steps)
