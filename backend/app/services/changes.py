"""Module 10 - change request workflow (state machine)."""

from __future__ import annotations

from dataclasses import dataclass

from app.db.base import utcnow
from app.models import ChangeRequest, User


class TransitionError(ValueError):
    pass


@dataclass(frozen=True)
class Transition:
    name: str
    source: tuple[str, ...]
    target: str
    permission: str


TRANSITIONS: dict[str, Transition] = {
    t.name: t
    for t in [
        Transition("submit", ("draft", "rejected"), "pending_approval", "changes:write"),
        Transition("approve", ("pending_approval",), "approved", "changes:approve"),
        Transition("reject", ("pending_approval",), "rejected", "changes:approve"),
        Transition("implement", ("approved",), "implemented", "changes:write"),
        Transition("close", ("implemented",), "closed", "changes:write"),
        Transition("cancel", ("draft", "pending_approval", "approved", "rejected"), "cancelled", "changes:write"),
    ]
}


def apply_transition(cr: ChangeRequest, name: str, actor: User, permissions: set[str]) -> ChangeRequest:
    t = TRANSITIONS.get(name)
    if t is None:
        raise TransitionError(f"unknown transition '{name}'")
    if cr.state not in t.source:
        raise TransitionError(f"cannot {name} a change in state '{cr.state}'")
    if t.permission not in permissions and not actor.is_superuser:
        raise TransitionError(f"'{t.permission}' permission required to {name}")
    if name == "approve" and cr.requested_by == actor.id:
        raise TransitionError("four-eyes principle: requester cannot approve their own change")
    now = utcnow()
    cr.state = t.target
    if name == "approve":
        cr.approved_by, cr.approved_at = actor.id, now
    elif name == "implement":
        cr.implemented_at = now
    elif name == "close":
        cr.closed_at = now
    return cr
