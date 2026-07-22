"""Provider-neutral voice request/response contract."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class VoiceRequest:
    employee_id: int
    session_id: str
    turn_id: int
    transcript: str
    response_language: str
    input_mode: str = "voice"
    language_segments: Tuple[dict, ...] = ()


def validate_voice_request(payload):
    required = ("employee_id", "session_id", "turn_id", "transcript", "response_language")
    if any(key not in payload for key in required):
        raise ValueError("voice request is missing required fields")
    try:
        employee_id, turn_id = int(payload["employee_id"]), int(payload["turn_id"])
    except (TypeError, ValueError):
        raise ValueError("employee_id and turn_id must be integers")
    if employee_id < 1 or turn_id < 0:
        raise ValueError("employee_id and turn_id must be positive")
    if not str(payload["session_id"]).strip() or not str(payload["transcript"]).strip():
        raise ValueError("session_id and transcript must be non-empty")
    language = str(payload["response_language"]).lower()
    if language not in ("en", "kn"):
        raise ValueError("response_language must be en or kn")
    return VoiceRequest(
        employee_id, str(payload["session_id"]), turn_id, str(payload["transcript"]),
        language, str(payload.get("input_mode", "voice")),
        tuple(payload.get("language_segments") or ()),
    )


def voice_response(request, query_result, speak=True):
    return {
        "turn_id": request.turn_id,
        "refused": bool(query_result.get("refused")),
        "answer": query_result.get("answer", ""),
        "language": query_result.get("language", request.response_language),
        "citations": list(query_result.get("citations", ())),
        "voice": {
            "speak": bool(speak and not query_result.get("refused")),
            "text": query_result.get("answer", ""),
            "language": "kn-IN" if request.response_language == "kn" else "en-IN",
        },
    }


def accept_turn(response, current_turn_id):
    """Client-side stale-response guard represented as a testable primitive."""
    return int(response.get("turn_id", -1)) == int(current_turn_id)
