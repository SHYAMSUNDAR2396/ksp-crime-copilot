from pathlib import Path


def test_voice_client_sends_backend_transcript_contract():
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "input_mode: inputMode" in source
    assert "transcript: transcript" in source
    assert "response_language:" in source


def test_browser_client_has_compatible_session_and_auth_contract():
    source = (Path(__file__).parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    assert "function createSessionId()" in source
    assert "crypto.randomUUID" in source
    assert "crypto.getRandomValues" in source
    assert "function setAuthStatus(response)" in source
    assert '"Authenticated officer"' in source
    assert '"Service unavailable"' in source


def test_browser_client_declares_same_origin_content_security_policy():
    source = (Path(__file__).parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    assert 'http-equiv="Content-Security-Policy"' in source
    assert "default-src 'self'" in source
    assert "connect-src 'self'" in source
    assert "script-src 'self'" in source
