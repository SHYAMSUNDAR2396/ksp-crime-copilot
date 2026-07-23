from pathlib import Path


def test_voice_client_sends_backend_transcript_contract():
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "input_mode: inputMode" in source
    assert "transcript: transcript" in source
    assert "response_language:" in source
