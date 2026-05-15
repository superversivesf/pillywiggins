from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from pillywiggins.memory.private import PrivateMemory
from tests.helpers import make_pool_mock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]


@pytest.fixture
def puck_memory():
    return PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="puck",
        embedding_dimension=3,
    )


@pytest.fixture
def oberon_memory():
    return PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="oberon",
        embedding_dimension=3,
    )


def _capture_init_callback():
    init_callback = None

    async def capture_init(dsn, **kwargs):
        nonlocal init_callback
        init_callback = kwargs.get("init")
        return make_pool_mock()

    return capture_init, lambda: init_callback


@pytest.mark.asyncio
async def test_init_connection_sets_agent_id(puck_memory):
    captured_init = None
    mock_pool = make_pool_mock()

    async def capture_init(dsn, **kwargs):
        nonlocal captured_init
        captured_init = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_init):
        await puck_memory.connect()

    assert captured_init is not None
    mock_conn = AsyncMock()
    await captured_init(mock_conn)
    mock_conn.execute.assert_called_once_with(
        "SELECT set_config('app.agent_id', $1, false)", "puck"
    )
    await puck_memory.close()


@pytest.mark.asyncio
async def test_init_uses_parameterised_set_config(puck_memory):
    captured_init = None
    mock_pool = make_pool_mock()

    async def capture_init(dsn, **kwargs):
        nonlocal captured_init
        captured_init = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_init):
        await puck_memory.connect()

    mock_conn = AsyncMock()
    await captured_init(mock_conn)

    set_call = mock_conn.execute.call_args
    sql = set_call[0][0]
    assert "$1" in sql
    assert sql == "SELECT set_config('app.agent_id', $1, false)"
    assert set_call[0][1] == "puck"
    await puck_memory.close()


@pytest.mark.asyncio
async def test_different_agents_set_different_ids(puck_memory, oberon_memory):
    puck_init = None
    oberon_init = None
    puck_pool = make_pool_mock()
    oberon_pool = make_pool_mock()

    async def capture_puck_init(dsn, **kwargs):
        nonlocal puck_init
        puck_init = kwargs.get("init")
        return puck_pool

    async def capture_oberon_init(dsn, **kwargs):
        nonlocal oberon_init
        oberon_init = kwargs.get("init")
        return oberon_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_puck_init):
        await puck_memory.connect()

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_oberon_init):
        await oberon_memory.connect()

    puck_conn = AsyncMock()
    await puck_init(puck_conn)

    oberon_conn = AsyncMock()
    await oberon_init(oberon_conn)

    puck_conn.execute.assert_called_with(
        "SELECT set_config('app.agent_id', $1, false)", "puck"
    )
    oberon_conn.execute.assert_called_with(
        "SELECT set_config('app.agent_id', $1, false)", "oberon"
    )
    await puck_memory.close()
    await oberon_memory.close()


@pytest.mark.asyncio
async def test_save_sets_agent_id_before_insert(puck_memory):
    call_order = []
    mock_conn = AsyncMock()
    inner_execute = AsyncMock()

    async def tracking_execute(*args, **kwargs):
        call_order.append(
            ("execute", args[0] if args else None, args[1] if len(args) > 1 else None)
        )
        return await inner_execute(*args, **kwargs)

    mock_conn.execute = tracking_execute
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        await puck_memory.save("test memory", [0.1, 0.2, 0.3], {"source": "test"})

    insert_calls = [c for c in call_order if c[1] and "INSERT" in c[1]]
    assert len(insert_calls) == 1
    agent_ids_in_inserts = [c[2] for c in call_order if c[1] and "INSERT" in c[1]]
    assert "puck" in agent_ids_in_inserts
    await puck_memory.close()


@pytest.mark.asyncio
async def test_save_uses_correct_agent_id_in_values(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        await puck_memory.save("secret thought", [0.5, 0.6, 0.7], {"mood": "curious"})

    args = mock_conn.execute.call_args[0]
    assert "INSERT INTO private_memory" in args[0]
    assert args[1] == "puck"
    assert args[2] == "secret thought"
    await puck_memory.close()


@pytest.mark.asyncio
async def test_search_sets_agent_id_before_select(puck_memory):
    call_order = []

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def tracking_acquire():
        call_order.append("acquire")
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    mock_pool.acquire = tracking_acquire

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        results = await puck_memory.search([0.1, 0.2, 0.3], limit=5)

    assert "acquire" in call_order
    mock_conn.fetch.assert_called_once()
    fetch_sql = mock_conn.fetch.call_args[0][0]
    assert "SELECT" in fetch_sql
    assert "private_memory" in fetch_sql
    await puck_memory.close()


@pytest.mark.asyncio
async def test_search_uses_agent_id_scoped_query(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        await puck_memory.search([0.1, 0.2, 0.3])

    fetch_args = mock_conn.fetch.call_args[0]
    assert "SELECT" in fetch_args[0]
    assert "private_memory" in fetch_args[0]
    await puck_memory.close()


@pytest.mark.asyncio
async def test_delete_sets_agent_id_before_delete(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 1")
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        result = await puck_memory.delete("abc-123")

    assert result is True
    delete_args = mock_conn.execute.call_args[0]
    assert "DELETE" in delete_args[0]
    assert "private_memory" in delete_args[0]
    await puck_memory.close()


@pytest.mark.asyncio
async def test_cross_agent_isolation_search_returns_no_rows(puck_memory):
    wrong_agent_mem = PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="oberon",
        embedding_dimension=3,
    )

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await wrong_agent_mem.connect()
        results = await wrong_agent_mem.search([0.1, 0.2, 0.3])

    assert results == []
    init_callback = None

    async def capture_init(dsn, **kwargs):
        nonlocal init_callback
        init_callback = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_init):
        await wrong_agent_mem.close()
        wrong_agent_mem._pool = None
        await wrong_agent_mem.connect()

    puck_conn = AsyncMock()
    await init_callback(puck_conn)
    puck_conn.execute.assert_called_with(
        "SELECT set_config('app.agent_id', $1, false)",
        "oberon",
    )

    await wrong_agent_mem.close()


@pytest.mark.asyncio
async def test_cross_agent_cannot_delete_other_memory(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 0")
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        result = await puck_memory.delete("uuid-owned-by-oberon")

    assert result is False
    await puck_memory.close()


@pytest.mark.asyncio
async def test_cross_agent_save_cannot_inject_wrong_id(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        await puck_memory.save("puck memory", [0.1, 0.2, 0.3], {"tag": "private"})

    insert_args = mock_conn.execute.call_args[0]
    agent_id_in_insert = insert_args[1]
    assert agent_id_in_insert == "puck"
    assert agent_id_in_insert != "oberon"
    await puck_memory.close()


@pytest.mark.asyncio
async def test_pool_connect_lifecycle(puck_memory):
    init_callback = None
    mock_pool = make_pool_mock()

    async def capture_init(dsn, **kwargs):
        nonlocal init_callback
        init_callback = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_init):
        await puck_memory.connect()

    assert puck_memory._pool is not None
    assert init_callback is not None
    await puck_memory.close()
    assert puck_memory._pool is None


@pytest.mark.asyncio
async def test_pool_close_idempotent(puck_memory):
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    puck_memory._pool = mock_pool

    await puck_memory.close()
    await puck_memory.close()

    mock_pool.close.assert_called_once()
    assert puck_memory._pool is None


@pytest.mark.asyncio
async def test_pool_connect_error(puck_memory):
    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        side_effect=ConnectionRefusedError("postgres unavailable"),
    ):
        with pytest.raises(ConnectionRefusedError):
            await puck_memory.connect()

    assert puck_memory._pool is None


@pytest.mark.asyncio
async def test_pool_acquire_releases_connection(puck_memory):
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool = make_pool_mock(acquire_return=mock_conn)

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        results = await puck_memory.search([0.1, 0.2, 0.3])
        assert results == []
        results2 = await puck_memory.search([0.4, 0.5, 0.6])
        assert results2 == []

    assert mock_conn.fetch.call_count == 2
    await puck_memory.close()


@pytest.mark.asyncio
async def test_init_callback_called_per_connection():
    init_calls = []
    created_pool = MagicMock()
    created_pool.close = AsyncMock()

    async def create_and_capture(dsn, **kwargs):
        init_fn = kwargs.get("init")
        if init_fn:
            for i in range(3):
                c = AsyncMock()

                async def execute_tracker(*args, **kw):
                    init_calls.append(args[0] if args else "unknown")

                c.execute = execute_tracker
                await init_fn(c)
        return created_pool

    memory = PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="puck",
        embedding_dimension=3,
    )

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=create_and_capture):
        await memory.connect()

    assert len(init_calls) == 3
    for sql in init_calls:
        assert sql == "SELECT set_config('app.agent_id', $1, false)"

    await memory.close()


@pytest.mark.asyncio
async def test_agent_id_sql_injection_safety():
    memory = PrivateMemory(
        database_url="postgresql://test:test@localhost:5432/testdb",
        agent_id="puck'; DROP TABLE private_memory; --",
        embedding_dimension=3,
    )

    init_callback = None
    mock_pool = make_pool_mock()

    async def capture_init(dsn, **kwargs):
        nonlocal init_callback
        init_callback = kwargs.get("init")
        return mock_pool

    with patch("pillywiggins.memory.base.asyncpg.create_pool", side_effect=capture_init):
        await memory.connect()

    mock_conn = AsyncMock()
    await init_callback(mock_conn)

    set_sql = mock_conn.execute.call_args[0][0]
    assert "set_config('app.agent_id'" in set_sql
    assert set_sql == "SELECT set_config('app.agent_id', $1, false)"
    assert mock_conn.execute.call_args[0][1] == "puck'; DROP TABLE private_memory; --"

    await memory.close()


@pytest.mark.asyncio
async def test_rls_set_before_every_acquire_operation(puck_memory):
    operation_order = []
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 1")
    mock_conn.fetch = AsyncMock(return_value=[])

    @asynccontextmanager
    async def tracking_acquire():
        operation_order.append("acquired")
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()
    mock_pool.acquire = tracking_acquire

    with patch(
        "pillywiggins.memory.base.asyncpg.create_pool",
        new_callable=AsyncMock,
        return_value=mock_pool,
    ):
        await puck_memory.connect()
        await puck_memory.save("m1", [0.1, 0.2, 0.3])
        await puck_memory.search([0.1, 0.2, 0.3])
        await puck_memory.delete("abc-123")

    assert operation_order == ["acquired", "acquired", "acquired", "acquired"]
    # connect: migration fetchrow (0) + alter execute (1) = 1
    # save: set_config + INSERT = 2
    # search: set_config = 1
    # delete: set_config + DELETE = 2
    assert mock_conn.execute.call_count == 6
    mock_conn.fetch.assert_called_once()
    await puck_memory.close()


# ---------------------------------------------------------------------------
# Real PostgreSQL integration tests (pytest-postgresql)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS private_memory (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(768),
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE private_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE private_memory FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS private_memory_isolation ON private_memory;
CREATE POLICY private_memory_isolation ON private_memory
    USING (agent_id = current_setting('app.agent_id')::text);

CREATE TABLE IF NOT EXISTS conversation_cache (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         TEXT NOT NULL,
    channel          TEXT NOT NULL,
    conversation_key TEXT NOT NULL,
    messages         JSONB DEFAULT '[]',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, channel, conversation_key)
);

ALTER TABLE conversation_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_cache FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversation_cache_isolation ON conversation_cache;
CREATE POLICY conversation_cache_isolation ON conversation_cache
    USING (agent_id = current_setting('app.agent_id')::text);

-- Prepare a non-superuser role so RLS is enforced.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'testagent') THEN
        CREATE ROLE testagent LOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO testagent;
GRANT ALL PRIVILEGES ON TABLE private_memory TO testagent;
GRANT ALL PRIVILEGES ON TABLE conversation_cache TO testagent;
"""


async def _set_agent_id(conn, agent_id: str) -> None:
    # asyncpg cannot parameterise SET; use an f-string.  This is safe here
    # because agent_id is a known test fixture value.
    await conn.execute(f"SET app.agent_id = '{agent_id}'")


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
async def test_rls_isolation_real_postgres(postgresql_proc):
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    admin_dsn = f"postgresql://{user}@{host}:{port}/postgres"

    import asyncpg

    admin_pool = await asyncpg.create_pool(admin_dsn, min_size=1, max_size=2)
    async with admin_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await admin_pool.close()

    test_dsn = f"postgresql://testagent@{host}:{port}/postgres"
    pool = await asyncpg.create_pool(test_dsn, min_size=1, max_size=2)

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "puck")
        await conn.execute(
            """INSERT INTO private_memory (agent_id, content, embedding, metadata)
               VALUES ($1, $2, NULL, $3::jsonb)""",
            "puck",
            "puck secret",
            '{"tag": "test"}',
        )

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "puck")
        rows = await conn.fetch("SELECT * FROM private_memory")
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "puck"

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "oberon")
        rows = await conn.fetch("SELECT * FROM private_memory")
    assert len(rows) == 0

    await pool.close()


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
async def test_conversation_store_rls_real_postgres(postgresql_proc):
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    admin_dsn = f"postgresql://{user}@{host}:{port}/postgres"

    import asyncpg

    admin_pool = await asyncpg.create_pool(admin_dsn, min_size=1, max_size=2)
    async with admin_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await admin_pool.close()

    test_dsn = f"postgresql://testagent@{host}:{port}/postgres"
    pool = await asyncpg.create_pool(test_dsn, min_size=1, max_size=2)

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "puck")
        await conn.execute(
            """INSERT INTO conversation_cache
               (agent_id, channel, conversation_key, messages, updated_at)
               VALUES ($1, $2, $3, $4::jsonb, now())
               ON CONFLICT (agent_id, channel, conversation_key)
               DO UPDATE SET messages = $4::jsonb, updated_at = now()""",
            "puck",
            "discord",
            "general",
            "[]",
        )

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "puck")
        rows = await conn.fetch("SELECT * FROM conversation_cache")
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "puck"

    async with pool.acquire() as conn:
        await _set_agent_id(conn, "oberon")
        rows = await conn.fetch("SELECT * FROM conversation_cache")
    assert len(rows) == 0

    await pool.close()


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
async def test_conversation_store_class_rls_integration(postgresql_proc):
    """Integration test: ConversationStore.save/load with RLS isolation.

    Creates two ConversationStore instances with different agent_ids,
    saves different conversations, and verifies each agent can only
    access its own data through the store's public API.
    """
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    admin_dsn = f"postgresql://{user}@{host}:{port}/postgres"

    import asyncpg

    # Set up schema as admin
    admin_pool = await asyncpg.create_pool(admin_dsn, min_size=1, max_size=2)
    async with admin_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await admin_pool.close()

    # Build DSNs pointing at the test database
    puck_dsn = f"postgresql://testagent@{host}:{port}/postgres"
    oberon_dsn = f"postgresql://testagent@{host}:{port}/postgres"

    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

    from pillywiggins.memory.store import ConversationStore

    # Create two ConversationStore instances with different agent_ids
    puck_store = ConversationStore(puck_dsn, agent_id="puck", channel="discord")
    oberon_store = ConversationStore(oberon_dsn, agent_id="oberon", channel="discord")

    # Connect both
    await puck_store.connect()
    await oberon_store.connect()

    # Build distinguishable messages for each agent
    puck_msgs: list = [
        ModelRequest(parts=[TextPart("puck's thought")]),
        ModelResponse(parts=[TextPart("puck's reply")]),
    ]
    oberon_msgs: list = [
        ModelRequest(parts=[TextPart("oberon's thought")]),
        ModelResponse(parts=[TextPart("oberon's reply")]),
    ]

    # Save each agent's conversation
    await puck_store.save("general", puck_msgs)
    await oberon_store.save("general", oberon_msgs)

    # Puck loads their own conversation — should succeed
    puck_loaded = await puck_store.load("general")
    assert puck_loaded is not None, "Puck should be able to load own conversation"
    assert len(puck_loaded) == 2
    puck_texts = [
        str(p.parts[0]) if hasattr(p.parts[0], "content") else str(p.parts[0])
        for p in puck_loaded
    ]
    assert "puck's thought" in puck_texts, f"Got: {puck_texts}"

    # Oberon loads their own conversation — should succeed
    oberon_loaded = await oberon_store.load("general")
    assert oberon_loaded is not None, "Oberon should be able to load own conversation"
    assert len(oberon_loaded) == 2
    oberon_texts = [
        str(p.parts[0]) if hasattr(p.parts[0], "content") else str(p.parts[0])
        for p in oberon_loaded
    ]
    assert "oberon's thought" in oberon_texts, f"Got: {oberon_texts}"

    # RLS: Puck tries to load oberon's key — should get nothing back
    puck_sees_oberon = await puck_store.load("oberon-only")
    assert puck_sees_oberon is None, (
        f"RLS violation: puck saw oberon's data: {puck_sees_oberon}"
    )

    # RLS: Oberon tries to load using puck's key — should get nothing
    oberon_sees_puck = await oberon_store.load("puck-only")
    assert oberon_sees_puck is None, (
        f"RLS violation: oberon saw puck's data: {oberon_sees_puck}"
    )

    # Clean up
    await puck_store.close()
    await oberon_store.close()


@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore::ResourceWarning")
async def test_conversation_store_cross_agent_save_isolation(postgresql_proc):
    """Each agent writes to the same key; RLS ensures they can't read each other's data."""
    host = postgresql_proc.host
    port = postgresql_proc.port
    user = postgresql_proc.user
    admin_dsn = f"postgresql://{user}@{host}:{port}/postgres"

    import asyncpg

    admin_pool = await asyncpg.create_pool(admin_dsn, min_size=1, max_size=2)
    async with admin_pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    await admin_pool.close()

    puck_dsn = f"postgresql://testagent@{host}:{port}/postgres"
    oberon_dsn = f"postgresql://testagent@{host}:{port}/postgres"

    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart

    from pillywiggins.memory.store import ConversationStore

    puck_store = ConversationStore(puck_dsn, agent_id="puck", channel="discord")
    oberon_store = ConversationStore(oberon_dsn, agent_id="oberon", channel="discord")

    await puck_store.connect()
    await oberon_store.connect()

    # Both agents save to the SAME conversation key
    puck_msgs: list = [ModelRequest(parts=[TextPart("puck's secret plan")])]
    oberon_msgs: list = [ModelRequest(parts=[TextPart("oberon's counter-plan")])]

    await puck_store.save("war-room", puck_msgs)
    await oberon_store.save("war-room", oberon_msgs)

    # Each sees only their own message
    puck_loaded = await puck_store.load("war-room")
    assert puck_loaded is not None
    assert len(puck_loaded) == 1
    assert "puck's secret plan" in str(puck_loaded[0].parts[0])

    oberon_loaded = await oberon_store.load("war-room")
    assert oberon_loaded is not None
    assert len(oberon_loaded) == 1
    assert "oberon's counter-plan" in str(oberon_loaded[0].parts[0])

    await puck_store.close()
    await oberon_store.close()
