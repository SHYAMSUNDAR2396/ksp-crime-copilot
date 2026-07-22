import json

from tools import probe_embeddings


class Provider:
    model = "test-model"
    batch_size = 2

    def embed_documents(self, texts):
        assert texts == probe_embeddings.FIXTURE
        return [[1.0, 0.0], [0.0, 1.0]]


def test_probe_report_contains_contract_metadata_only(capsys):
    report = probe_embeddings.probe(Provider())
    assert report["status"] == "ok"
    assert report["dimension"] == 2
    assert "theft" not in json.dumps(report)


def test_probe_requires_endpoint(monkeypatch, capsys):
    monkeypatch.delenv("QUICKML_EMBEDDINGS_ENDPOINT", raising=False)
    assert probe_embeddings.main(["--language-fixture"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "error"
