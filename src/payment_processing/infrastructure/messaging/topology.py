from faststream.rabbit import Channel, RabbitBroker, RabbitExchange, RabbitQueue
from faststream.rabbit.schemas.queue import QueueType

PAYMENTS = RabbitExchange("payments", durable=True)
RETRY = RabbitExchange("payments.retry", durable=True)
DEAD = RabbitExchange("payments.dead", durable=True)

NEW_QUEUE = RabbitQueue(
    "payments.new",
    queue_type=QueueType.QUORUM,
    arguments={
        "x-dead-letter-exchange": "payments.dead",
        "x-dead-letter-routing-key": "payments.dlq",
        "x-dead-letter-strategy": "at-least-once",
        "x-overflow": "reject-publish",
    },
)
DLQ = RabbitQueue("payments.dlq", queue_type=QueueType.QUORUM)


def retry_queue(seconds: int) -> RabbitQueue:
    return RabbitQueue(
        f"payments.retry.{seconds}s",
        queue_type=QueueType.QUORUM,
        arguments={
            "x-message-ttl": seconds * 1000,
            "x-dead-letter-exchange": "payments",
            "x-dead-letter-routing-key": "payments.new",
            "x-dead-letter-strategy": "at-least-once",
            "x-overflow": "reject-publish",
        },
    )


RETRY_QUEUES = (retry_queue(2), retry_queue(4))
QUEUES = (NEW_QUEUE, *RETRY_QUEUES, DLQ)


def create_broker(url: str) -> RabbitBroker:
    return RabbitBroker(
        url,
        default_channel=Channel(prefetch_count=1, publisher_confirms=True, on_return_raises=True),
        graceful_timeout=15,
    )


async def declare_topology(broker: RabbitBroker) -> None:
    for exchange in (PAYMENTS, RETRY, DEAD):
        await broker.declare_exchange(exchange)
    for queue, exchange in (
        (NEW_QUEUE, PAYMENTS),
        *((q, RETRY) for q in RETRY_QUEUES),
        (DLQ, DEAD),
    ):
        declared = await broker.declare_queue(queue)
        await declared.bind(exchange.name, routing_key=queue.name)
