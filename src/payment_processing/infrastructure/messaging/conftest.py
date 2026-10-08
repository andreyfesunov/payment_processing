import os
import re
from collections.abc import AsyncIterator
from urllib.parse import quote, unquote, urlsplit

import httpx
import pytest
import pytest_asyncio
from faststream.rabbit import RabbitBroker

from payment_processing.infrastructure.messaging.topology import (
    QUEUES,
    create_broker,
    declare_topology,
)


@pytest.fixture(scope="session")
def rabbitmq_url() -> str:
    url = os.environ.get(
        "TEST_RABBITMQ_URL", "amqp://payments:payments@localhost:5673/payments_test"
    )
    parts = urlsplit(url)
    vhost = unquote(parts.path.lstrip("/"))
    if re.fullmatch(r"[a-z_]+_test", vhost) is None:
        raise ValueError("TEST_RABBITMQ_URL must name a vhost ending in _test")
    username = unquote(parts.username or "")
    password = unquote(parts.password or "")
    management = os.environ.get("TEST_RABBITMQ_MANAGEMENT_URL", "http://localhost:15672")
    with httpx.Client(base_url=management, auth=(username, password), timeout=10) as client:
        client.put(f"/api/vhosts/{quote(vhost, safe='')}").raise_for_status()
        client.put(
            f"/api/permissions/{quote(vhost, safe='')}/{quote(username, safe='')}",
            json={"configure": ".*", "write": ".*", "read": ".*"},
        ).raise_for_status()
    return url


@pytest_asyncio.fixture
async def broker(rabbitmq_url: str) -> AsyncIterator[RabbitBroker]:
    instance = create_broker(rabbitmq_url)
    await instance.connect()
    try:
        await declare_topology(instance)
        for queue in QUEUES:
            declared = await instance.declare_queue(queue)
            await declared.purge()
        yield instance
    finally:
        await instance.stop()
