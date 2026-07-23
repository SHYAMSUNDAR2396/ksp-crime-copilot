import json
from pathlib import Path

from tools.catalyst_preflight import run_preflight


ROOT = Path(__file__).resolve().parents[1]


def test_local_preflight_passes_structure_and_reports_live_warnings():
    report = run_preflight(ROOT, require_live=False, catalyst_available=False)

    assert report["ok"] is True
    assert report["live_ready"] is False
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
                "KSP_AUTH_EMPLOYEE_MAP": '{"principal-1": 9}',
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
            },
        },
        "execution": {"main": "main.py"},
    }
    (root / "functions/crime_query/catalyst-config.json").write_text(json.dumps(config))
    (root / "functions/silent_match/catalyst-config.json").write_text(json.dumps(silent_config))
    from functions.crime_query.catalog import TABLES
    schema_tables = list(TABLES) + ["AuditLog"]
    (root / "docs/schema-ddl.sql").write_text(
        "\n".join('CREATE TABLE "{}";'.format(name) for name in schema_tables)
    )
    (root / "docs/silent-match-alerts-ddl.sql").write_text(
        "CREATE TABLE SilentMatchAlert; CREATE TABLE MoEmbeddingRecord; "
        "CREATE TABLE MoEmbeddingJobState;"
    )
    (root / "docs/derived-graph-ddl.sql").write_text(
        " ".join("CREATE TABLE {};".format(name) for name in (
            "PersonNode", "PersonMember", "EdgePersonCase", "EdgeCaseEmployee",
            "EdgeCaseSection", "EdgeCaseNear", "GraphProjectionState",
        ))
    )
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

    report = run_preflight(root, require_live=True, catalyst_available=True)
    assert report["ok"] is True
    assert report["live_ready"] is True
    assert report["failures"] == []
