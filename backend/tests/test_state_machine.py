"""State machine unit tests (§2.2 domain rules).

Tested as a table rather than case by case, so adding a status without deciding its legal
moves fails a test instead of shipping.
"""

import pytest

from app.domain.enums import Status
from app.domain.state_machine import (
    TRANSITIONS,
    InvalidTransition,
    assert_transition,
    can_transition,
    terminal_statuses,
)

LEGAL = [
    (Status.OPEN, Status.IN_PROGRESS),
    (Status.OPEN, Status.REJECTED),
    (Status.IN_PROGRESS, Status.RESOLVED),
    (Status.IN_PROGRESS, Status.REJECTED),
]

ILLEGAL = [
    (Status.OPEN, Status.RESOLVED),  # cannot skip in_progress
    (Status.OPEN, Status.OPEN),  # no-op is a caller bug
    (Status.IN_PROGRESS, Status.OPEN),  # no reopening
    (Status.RESOLVED, Status.IN_PROGRESS),  # terminal
    (Status.RESOLVED, Status.OPEN),
    (Status.RESOLVED, Status.REJECTED),
    (Status.REJECTED, Status.OPEN),
    (Status.REJECTED, Status.IN_PROGRESS),
    (Status.REJECTED, Status.RESOLVED),
]


@pytest.mark.parametrize(("current", "requested"), LEGAL)
def test_legal_transitions_are_permitted(current: Status, requested: Status) -> None:
    assert can_transition(current, requested)
    assert_transition(current, requested)  # must not raise


@pytest.mark.parametrize(("current", "requested"), ILLEGAL)
def test_illegal_transitions_are_refused(current: Status, requested: Status) -> None:
    assert not can_transition(current, requested)
    with pytest.raises(InvalidTransition) as excinfo:
        assert_transition(current, requested)
    # The message must name the attempted transition — it is surfaced verbatim in the UI.
    assert current.value in excinfo.value.message
    assert requested.value in excinfo.value.message


def test_resolved_and_rejected_are_terminal() -> None:
    assert terminal_statuses() == frozenset({Status.RESOLVED, Status.REJECTED})


def test_every_status_appears_in_the_table() -> None:
    """Guards against adding a Status enum member and forgetting its row: a missing key would
    raise KeyError at runtime inside assert_transition."""
    assert set(TRANSITIONS) == set(Status)


def test_terminal_message_explains_why() -> None:
    with pytest.raises(InvalidTransition) as excinfo:
        assert_transition(Status.RESOLVED, Status.OPEN)
    assert "terminal" in excinfo.value.message
