from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class QueueMessage:
    topic: str
    payload: dict


class QueuePublisher(Protocol):
    async def publish(self, message: QueueMessage) -> None:
        ...

