import json
import shutil
from types import SimpleNamespace
from pathlib import Path

from tools import catalyst_preflight
from tools.catalyst_preflight import _project_config, _schema_contract, run_preflight


ROOT = Path(__file__).resolve().parents[1]


def test_project_config_rejects_incomplete_web_client(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web/index.html").write_text("<!doctype html>")
    (tmp_path / "catalyst.json").write_text(json.dumps({
        "functions": {"source": "functions", "targets": ["crime_query", "silent_match"]},
        "client": {"source": "web"},
    }))

    ok, detail = _project_config(tmp_path)

    assert ok is False
    assert "client assets" in detail


def test_schema_contract_rejects_missing_operational_column(tmp_path):
    (tmp_path / "docs").mkdir()
    for name in (
        "schema-ddl.sql", "silent-match-alerts-ddl.sql", "derived-graph-ddl.sql",
    ):
        shutil.copy2(ROOT / "docs" / name, tmp_path / "docs" / name)
    operational = tmp_path / "docs/silent-match-alerts-ddl.sql"
    text = operational.read_text(encoding="utf-8")
    operational.write_text(
        text.replace("  Status TEXT NOT NULL DEFAULT 'New',\n", ""),
        encoding="utf-8",
    )

    ok, detail = _schema_contract(tmp_path)

    assert ok is False
    assert "SilentMatchAlert" in detail


def test_python39_syntax_gate_rejects_newer_language_syntax(tmp_path):
    (tmp_path / "functions/crime_query").mkdir(parents=True)
    (tmp_path / "functions/crime_query/new_syntax.py").write_text(
        "match value:\n    case 1:\n        pass\n",
        encoding="utf-8",
    )

    ok, detail = catalyst_preflight._python39_syntax(tmp_path)

    assert ok is False
    assert "new_syntax.py" in detail


def test_local_preflight_passes_structure_and_reports_live_warnings():
    report = run_preflight(ROOT, require_live=False, catalyst_available=False)

    assert report["ok"] is True
    assert report["live_ready"] is False
    assert any(item["name"] == "catalyst_project_config" for item in report["checks"])
    names = {item["name"] for item in report["warnings"]}
    assert "catalyst_cli" in names
    assert any("EMBEDDINGS_ENDPOINT" in name for name in names)
    assert any("AUTH_EMPLOYEE_MAP" in name for name in names)


def test_live_preflight_fails_closed_without_account_side_gates():
    report = run_preflight(ROOT, require_live=True, catalyst_available=False)

    assert report["ok"] is False
    failed = {item["name"] for item in report["failures"]}
    assert "catalyst_cli" in failed
    assert any("EMBEDDINGS_ENDPOINT" in name for name in failed)
    assert any("RAG_ENDPOINT" in name for name in failed)
    assert any("AUTH_EMPLOYEE_MAP" in name for name in failed)


def test_live_preflight_fails_closed_when_catalyst_cli_is_not_authenticated():
    report = run_preflight(
        ROOT,
        require_live=True,
        catalyst_available=True,
        catalyst_authenticated=False,
    )

    assert report["ok"] is False
    assert report["live_ready"] is False
    assert "catalyst_authentication" in {
        item["name"] for item in report["failures"]
    }


def test_catalyst_authentication_handles_cli_zero_exit_login_error(monkeypatch):
    monkeypatch.setattr(
        catalyst_preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="Not logged in yet. To login use catalyst login.",
            stderr="",
        ),
    )
    assert catalyst_preflight._catalyst_authenticated() is False

    monkeypatch.setattr(
        catalyst_preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="authenticated-user@example.invalid",
            stderr="",
        ),
    )
    assert catalyst_preflight._catalyst_authenticated() is True


def test_preflight_does_not_emit_configuration_values(capsys):
    run_preflight(ROOT, require_live=False, catalyst_available=False)
    output = capsys.readouterr().out
    # The library is intentionally silent; CLI serialization is tested through
    # the safe report shape rather than allowing endpoint/config values to leak.
    assert output == ""


def test_preflight_accepts_complete_synthetic_live_configuration(tmp_path):
    root = tmp_path
    (root / "functions/crime_query").mkdir(parents=True)
    (root / "functions/silent_match").mkdir(parents=True)
    (root / "docs").mkdir()
    config = {
        "deployment": {
            "name": "crime_query",
            "stack": "python_3_9",
            "type": "advancedio",
            "env_variables": {
                "QUICKML_ENDPOINT": "https://example.invalid/glm",
                "QUICKML_MODEL": "crm-di-glm47b_30b_it",
                "QUICKML_ORG_ID": "123",
                "SMARTBROWZ_ENDPOINT": "https://example.invalid/pdf",
                "QUICKML_RAG_ENDPOINT": "https://example.invalid/rag",
                "QUICKML_ANALYTICS_ENDPOINT": "https://example.invalid/analytics",
                "KSP_AUTH_EMPLOYEE_MAP": '{"principal-1": 9}',
                "KSP_AUTH_SERVICE_MAP": '{"service-1": 9001}',
            },
        },
        "execution": {"main": "main.py"},
    }
    silent_config = {
        "deployment": {
            "name": "silent_match",
            "stack": "python_3_9",
            "type": "advancedio",
            "env_variables": {
                "QUICKML_ORG_ID": "123",
                "QUICKML_EMBEDDINGS_ENDPOINT": "https://example.invalid/embed",
                "QUICKML_EMBEDDINGS_MODEL": "multilingual-v1",
                "QUICKML_EMBEDDINGS_INDEX_VERSION": "mo-index-v1",
                "KSP_SILENT_MATCH_LOOKBACK_DAYS": "365",
                "KSP_AUTH_EMPLOYEE_MAP": '{"principal-1": 9}',
                "KSP_AUTH_SERVICE_MAP": '{"service-1": 9001}',
            },
        },
        "execution": {"main": "main.py"},
    }
    (root / "functions/crime_query/catalyst-config.json").write_text(json.dumps(config))
    (root / "functions/silent_match/catalyst-config.json").write_text(json.dumps(silent_config))
    (root / "functions/crime_query/requirements.txt").write_text("zcatalyst-sdk==1.3.0\n")
    (root / "functions/silent_match/requirements.txt").write_text("zcatalyst-sdk==1.3.0\n")
    (root / "web").mkdir()
    for asset in ("index.html", "app.js", "styles.css"):
        (root / "web" / asset).write_text("client asset")
    (root / "catalyst.json").write_text(json.dumps({
        "functions": {
            "targets": ["crime_query", "silent_match"],
            "ignore": ["**/__pycache__/**", "*.pyc", ".DS_Store"],
            "source": "functions",
        },
        "client": {"source": "web", "ignore": [".DS_Store"]},
    }))
    for name in (
        "schema-ddl.sql", "silent-match-alerts-ddl.sql", "derived-graph-ddl.sql",
    ):
        shutil.copy2(ROOT / "docs" / name, root / "docs" / name)
    rules = {
        "advancedio": {
            "crime_query": [{".*": {"methods": ["POST"], "authentication": "required"}}],
            "silent_match": [{
                "/similar-cases": {"methods": ["POST"], "authentication": "required"},
                "/alerts": {"methods": ["GET"], "authentication": "required"},
                "/alerts/.*": {"methods": ["GET", "POST"], "authentication": "required"},
                "/scan": {"methods": ["POST"], "authentication": "required"},
                "/index": {"methods": ["POST"], "authentication": "required"},
                "/graph-projection": {"methods": ["POST"], "authentication": "required"},
            }],
        }
    }
    (root / "docs/catalyst-security-rules.json").write_text(json.dumps(rules))
    source_manifest = ROOT / "docs/catalyst-job-contracts.json"
    (root / "docs/catalyst-job-contracts.json").write_text(
        source_manifest.read_text(encoding="utf-8"), encoding="utf-8"
    )

    report = run_preflight(
        root,
        require_live=True,
        catalyst_available=True,
        catalyst_authenticated=True,
    )
    assert report["ok"] is True
    assert report["live_ready"] is True
    assert report["failures"] == []
