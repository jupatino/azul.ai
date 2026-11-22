from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IncomingMessage:
    channel: str
    sender_id: str
    conversation_id: str
    thread_id: str
    event_id: str
    text: str


@dataclass(frozen=True)
class OutgoingMessage:
    text: str
    thread_id: str | None = None


class ChannelAdapter(Protocol):
    def process(self, message: IncomingMessage) -> OutgoingMessage | None:
        ...
