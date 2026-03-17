import logging
import json

from app.integrations.queue.base import QueueMessage
from app.integrations.queue.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class NoopQueuePublisher:
    async def publish(self, message: QueueMessage) -> None:
        logger.info(
            "Queue backend is disabled; message accepted as no-op.",
            extra={"topic": message.topic},
        )


class CeleryQueuePublisher:
    async def publish(self, message: QueueMessage) -> None:
        logger.info(
            "Celery adapter placeholder received a message.",
            extra={"topic": message.topic, "payload": message.payload},
        )


class DramatiqQueuePublisher:
    async def publish(self, message: QueueMessage) -> None:
        logger.info(
            "Dramatiq adapter placeholder received a message.",
            extra={"topic": message.topic, "payload": message.payload},
        )


class RedisListQueuePublisher:
    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name

    async def publish(self, message: QueueMessage) -> None:
        client = get_redis_client()
        await client.rpush(self.queue_name, json.dumps(message.payload, ensure_ascii=True))
        logger.info("Message pushed to Redis queue list.", extra={"topic": message.topic})
