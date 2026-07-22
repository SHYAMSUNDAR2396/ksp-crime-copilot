import pytest

from functions.crime_query.conversation import (
    CatalystCacheConversationStore,
    ConversationTurn,
    InMemoryConversationStore,
    merge_follow_up,
)
from functions.crime_query.voice import (
    accept_turn,
    validate_voice_request,
    voice_response,
)


def test_session_is_owned_and_bounded():
    store = InMemoryConversationStore(max_turns=2)
    for turn_id in (1, 2, 3):
        store.append("s1", 9, ConversationTurn(turn_id, "text", "q", "en"))
    assert [turn.turn_id for turn in store.load("s1", 9).turns] == [2, 3]
    assert store.load("s1", 10).turns == ()


def test_voice_response_preserves_turn_and_citations():
    request = validate_voice_request({
        "employee_id": 9, "session_id": "s1", "turn_id": 12,
        "transcript": "ಕಳ್ಳತನ ಪ್ರಕರಣಗಳು", "response_language": "kn",
    })
    response = voice_response(request, {
        "refused": False, "answer": "ಉತ್ತರ FIR/1", "language": "kn",
        "citations": ["FIR/1"],
    })
    assert response["turn_id"] == 12
    assert response["voice"]["language"] == "kn-IN"
    assert accept_turn(response, 12)
    assert not accept_turn(response, 11)


def test_follow_up_and_request_validation():
    assert merge_follow_up({"district": 1, "crime": "theft"}, {"crime": "burglary"}) == {
        "district": 1, "crime": "burglary"
    }
    with pytest.raises(ValueError):
        validate_voice_request({"employee_id": 9})


def test_cache_store_round_trips_owned_turns():
    class Cache:
        def __init__(self):
            self.values = {}
        def put(self, key, value):
            self.values[key] = value
        def get(self, key):
            return self.values.get(key)

    store = CatalystCacheConversationStore(Cache())
    store.append("s1", 9, ConversationTurn(1, "voice", "hello", "en", ("FIR/1",)))
    assert store.load("s1", 9).turns[0].citations == ("FIR/1",)
    assert store.load("s1", 10).turns == ()


def test_cache_store_supports_catalyst_segment_shape():
    class Segment:
        def __init__(self):
            self.values = {}
        def put(self, key, value):
            self.values[key] = value
        def get_value(self, key):
            return self.values.get(key)

    class Cache:
        def __init__(self):
            self.segment_value = Segment()
        def segment(self):
            return self.segment_value

    store = CatalystCacheConversationStore(Cache())
    store.append("s2", 9, ConversationTurn(2, "voice", "hello", "en"))
    assert store.load("s2", 9).turns[0].turn_id == 2
