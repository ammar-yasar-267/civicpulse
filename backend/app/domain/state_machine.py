"""Complaint status state machine.

Deliberately an explicit transition table rather than a chain of ifs (§2.2): the legal
graph is data you can read, test and print, and adding a status is a one-line change
that cannot silently forget a branch.

    open -> in_progress -> resolved
    open -> rejected
    in_progress -> rejected
    resolved, rejected are terminal
"""

from app.domain.enums import Status

TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.OPEN: frozenset({Status.IN_PROGRESS, Status.REJECTED}),
    Status.IN_PROGRESS: frozenset({Status.RESOLVED, Status.REJECTED}),
    Status.RESOLVED: frozenset(),
    Status.REJECTED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when a caller attempts a transition the table does not permit.

    Carries both states so the route can return a 409 that names the attempted
    transition instead of a generic error (§2.2 API contract).
    """

    def __init__(self, current: Status, requested: Status) -> None:
        self.current = current
        self.requested = requested
        super().__init__(self.message)

    @property
    def message(self) -> str:
        allowed = sorted(TRANSITIONS[self.current])
        if not allowed:
            return (
                f"Invalid transition {self.current.value} -> {self.requested.value}: "
                f"{self.current.value} is a terminal status."
            )
        return (
            f"Invalid transition {self.current.value} -> {self.requested.value}. "
            f"Allowed from {self.current.value}: {', '.join(s.value for s in allowed)}."
        )


def can_transition(current: Status, requested: Status) -> bool:
    return requested in TRANSITIONS[current]


def assert_transition(current: Status, requested: Status) -> None:
    """Raise InvalidTransition unless the move is legal. No-op self-transitions are
    also rejected — re-sending 'open' on an open complaint is a caller bug, not a win."""
    if not can_transition(current, requested):
        raise InvalidTransition(current, requested)


def terminal_statuses() -> frozenset[Status]:
    return frozenset(s for s, allowed in TRANSITIONS.items() if not allowed)
