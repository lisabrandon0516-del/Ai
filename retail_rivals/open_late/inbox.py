"""Inbox notes stored on the save."""

from __future__ import annotations

from open_late.models import Choice, GameState, InboxMessage


def add(
    state: GameState,
    *,
    kind: str,
    title: str,
    body: str,
    urgent: bool = False,
    choices: list[Choice] | None = None,
) -> InboxMessage:
    message = InboxMessage(
        id=f"m{state.next_message_id}",
        day=state.day,
        kind=kind,
        title=title,
        body=body,
        urgent=urgent,
        choices=choices or [],
    )
    state.next_message_id += 1
    state.inbox.append(message)
    return message


def trim(state: GameState, limit: int = 80) -> None:
    if len(state.inbox) <= limit:
        return
    resolved = [message for message in state.inbox if message.resolved]
    pending = [message for message in state.inbox if not message.resolved]
    state.inbox = resolved[-40:] + pending
