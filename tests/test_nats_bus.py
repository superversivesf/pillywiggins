import pytest


@pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
class TestNatsBusConnect:
    @pytest.mark.asyncio
    async def test_connect_creates_nats_connection(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_connect_creates_jetstream(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_connect_adds_pillywiggins_stream(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_close_drains_connection(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
class TestNatsBusPublish:
    @pytest.mark.asyncio
    async def test_publish_to_council_broadcast(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_publish_to_direct_agent(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    def test_publish_skill_deployed_message_format(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
class TestNatsBusSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_to_council_broadcast(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_subscribe_to_direct_messages(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_subscription_receives_published_message(self):
        ...


@pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
class TestNatsBusReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_on_connection_drop(self):
        ...

    @pytest.mark.skip(reason="Module pillywiggins.messaging.nats_bus not yet implemented")
    @pytest.mark.asyncio
    async def test_durable_subscription_survives_disconnect(self):
        ...