"""Bounded session context for typed and voice conversations."""
from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class ConversationTurn:
    turn_id: int
    input_mode: str
    transcript: str
    language: str
    citations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ConversationState:
    session_id: str
    employee_id: int
    filters: dict = field(default_factory=dict)
    prior_task: dict = field(default_factory=dict)
    turns: Tuple[ConversationTurn, ...] = ()


class InMemoryConversationStore:
    """Deterministic local adapter; production can replace storage with Cache."""

    def __init__(self, max_turns=20):
        self.max_turns = max_turns
        self._states = {}

    def load(self, session_id, employee_id):
        state = self._states.get(session_id)
        if state is None or state.employee_id != int(employee_id):
            return ConversationState(session_id, int(employee_id))
        return state

    def save(self, state):
        if not state.session_id:
            raise ValueError("session_id is required")
        self._states[state.session_id] = state
        return state

    def append(self, session_id, employee_id, turn, filters=None, prior_task=None):
        state = self.load(session_id, employee_id)
        turns = (state.turns + (turn,))[-self.max_turns:]
        return self.save(ConversationState(
            session_id=state.session_id,
            employee_id=state.employee_id,
            filters=dict(state.filters if filters is None else filters),
            prior_task=dict(state.prior_task if prior_task is None else prior_task),
            turns=turns,
        ))


def merge_follow_up(previous_filters, follow_up_filters):
    """Apply explicit follow-up filters to cached filters without client trust."""
    merged = dict(previous_filters or {})
    for key, value in (follow_up_filters or {}).items():
        if value is not None:
            merged[key] = value
    return merged
