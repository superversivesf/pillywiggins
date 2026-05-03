"""Real PostgreSQL + pgvector integration tests using Docker."""

import asyncio
import os
import socket
import subprocess
import time
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("docker_available"),
]

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "init-db.sql")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_pg_ready(dsn: str, timeout: int = 30):
    import asyncpg

    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(dsn)
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5)
    pytest.fail(f"PostgreSQL did not become ready in {timeout}s: {last_err}")


async def _init_schema(admin_dsn: str):
    import asyncpg

    with open(SCHEMA_PATH) as f:
        schema_sql = f.read()

    conn = await asyncpg.connect(admin_dsn)
    await conn.execute(schema_sql)
    # Ensure RLS is enforced even for the table owner.
    await conn.execute("""
        ALTER TABLE private_memory FORCE ROW LEVEL SECURITY;
        ALTER TABLE conversation_cache FORCE ROW LEVEL SECURITY;
    """)
    # Create a non-superuser role so that integration tests exercise real RLS.
    await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'testagent') THEN
                CREATE ROLE testagent LOGIN PASSWORD 'testpass';
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA public TO testagent;
        GRANT ALL PRIVILEGES ON TABLE private_memory TO testagent;
        GRANT ALL PRIVILEGES ON TABLE conversation_cache TO testagent;
        GRANT ALL PRIVILEGES ON TABLE council_memory TO testagent;
    """)
    await conn.close()


@pytest.fixture(scope="module")
def postgres_dsn():
    port = _free_port()
    name = f"pillywiggins-test-pg-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-e",
            "POSTGRES_PASSWORD=testpass",
            "-e",
            "POSTGRES_DB=testdb",
            "-p",
            f"{port}:5432",
            "--name",
            name,
            "pgvector/pgvector:pg17",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    admin_dsn = f"postgresql://postgres:testpass@127.0.0.1:{port}/testdb"
    test_dsn = f"postgresql://testagent:testpass@127.0.0.1:{port}/testdb"
    try:
        asyncio.run(_wait_pg_ready(admin_dsn))
        asyncio.run(_init_schema(admin_dsn))
        yield test_dsn
    finally:
        subprocess.run(["docker", "stop", "-t", "3", name], capture_output=True)


# ---------------------------------------------------------------------------
# RLS isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rls_isolation(postgres_dsn):
    from pillywiggins.memory.private import PrivateMemory

    mem_a = PrivateMemory(database_url=postgres_dsn, agent_id="agent_a")
    mem_b = PrivateMemory(database_url=postgres_dsn, agent_id="agent_b")
    await mem_a.connect()
    await mem_b.connect()

    vec = [1.0] + [0.0] * 767
    await mem_a.save("secret from a", vec, {"tag": "test"})

    results_a = await mem_a.search(vec, limit=5)
    assert len(results_a) == 1
    assert results_a[0]["content"] == "secret from a"

    results_b = await mem_b.search(vec, limit=5)
    assert len(results_b) == 0

    await mem_a.close()
    await mem_b.close()


# ---------------------------------------------------------------------------
# Dimension validation (CouncilMemory)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_council_memory_rejects_wrong_dimension(postgres_dsn):
    from pillywiggins.memory.council import CouncilMemory

    council = CouncilMemory(database_url=postgres_dsn, agent_id="puck")
    await council.connect()

    result = await council.write_entry(
        content="test",
        tags=["general"],
        embedding=[0.1, 0.2, 0.3],
        message_type="insight",
    )
    assert result["success"] is False
    assert "dimension" in result["error"].lower()

    await council.close()


# ---------------------------------------------------------------------------
# Native list vector binding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_binding_roundtrip_as_list(postgres_dsn):
    import asyncpg
    from pgvector.asyncpg import register_vector

    conn = await asyncpg.connect(postgres_dsn)
    await register_vector(conn)
    await conn.execute("SET app.agent_id = 'list_test'")
    vec = [0.1, 0.2, 0.3] + [0.0] * 765
    await conn.execute(
        "INSERT INTO private_memory (agent_id, content, embedding) VALUES ($1, $2, $3)",
        "list_test",
        "list binding",
        vec,
    )
    row = await conn.fetchrow(
        "SELECT embedding FROM private_memory WHERE agent_id = $1",
        "list_test",
    )
    emb = row["embedding"]
    # pgvector may return a numpy array if numpy is installed;
    # coerce to list so the assertion is robust across environments.
    if hasattr(emb, "tolist"):
        emb = emb.tolist()
    assert isinstance(emb, list)
    assert emb[:3] == [pytest.approx(0.1), pytest.approx(0.2), pytest.approx(0.3)]
    await conn.close()


# ---------------------------------------------------------------------------
# Similarity search scores in [0, 1]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_similarity_scores_in_range(postgres_dsn):
    from pillywiggins.memory.private import PrivateMemory

    mem = PrivateMemory(database_url=postgres_dsn, agent_id="sim_agent")
    await mem.connect()

    vec_a = [1.0, 0.0, 0.0] + [0.0] * 765
    vec_b = [0.0, 1.0, 0.0] + [0.0] * 765
    vec_c = [1.0, 0.0, 0.0] + [0.0] * 765

    await mem.save("entry a", vec_a)
    await mem.save("entry b", vec_b)

    results = await mem.search(vec_c, limit=5)
    assert len(results) == 2
    for r in results:
        assert 0.0 <= r["similarity"] <= 1.0

    # vec_c is identical to vec_a, so it should be the top result
    top = max(results, key=lambda x: x["similarity"])
    assert top["content"] == "entry a"
    assert top["similarity"] == pytest.approx(1.0, abs=1e-6)

    await mem.close()


# ---------------------------------------------------------------------------
# Council memory CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_council_memory_write_list_search_delete(postgres_dsn):
    from pillywiggins.memory.council import CouncilMemory

    council = CouncilMemory(database_url=postgres_dsn, agent_id="council_puck")
    await council.connect()

    vec = [0.1] * 768
    write_result = await council.write_entry(
        content="council insight",
        tags=["general", "idea"],
        embedding=vec,
        message_type="insight",
        confidence=0.95,
    )
    assert write_result["success"] is True
    assert write_result["id"] is not None

    listed = await council.list_entries(limit=10)
    assert len(listed) == 1
    assert listed[0]["content"] == "council insight"

    searched = await council.search(vec, limit=5)
    assert len(searched) == 1
    assert searched[0]["content"] == "council insight"
    assert searched[0]["similarity"] == pytest.approx(1.0, abs=1e-6)

    deleted = await council.delete_entry(write_result["id"])
    assert deleted is True

    listed_after = await council.list_entries(limit=10)
    assert len(listed_after) == 0

    await council.close()
