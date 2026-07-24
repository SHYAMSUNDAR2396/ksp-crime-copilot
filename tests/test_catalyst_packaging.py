from pathlib import Path
import os
import shutil
import subprocess
import sys

from tools.prepare_catalyst_deploy import SHARED_MODULES, prepare


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_vendors_silent_match_shared_runtime_modules(tmp_path):
    destination = tmp_path / "functions/silent_match"
    destination.mkdir(parents=True)

    result = prepare(ROOT, destination=destination)

    assert result["modules"] == SHARED_MODULES
    vendor = destination / "_vendor"
    assert (vendor / ".ksp-vendored").exists()
    assert {path.name for path in vendor.glob("*.py")} == set(SHARED_MODULES)
    assert all((vendor / name).read_text(encoding="utf-8") for name in SHARED_MODULES)


def test_vendored_silent_match_runtime_imports_without_repository_package(tmp_path):
    destination = tmp_path / "functions/silent_match"
    destination.mkdir(parents=True)
    prepare(ROOT, destination=destination)
    for name in ("main.py", "runtime.py", "index_cases.py", "job_contracts.py"):
        shutil.copy2(ROOT / "functions/silent_match" / name, destination / name)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(destination / "_vendor"), str(destination)))
    result = subprocess.run(
        [sys.executable, "-c", "import runtime; print(runtime.CatalystCaseLoader.__name__)"],
        cwd=str(destination), env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CatalystCaseLoader"
