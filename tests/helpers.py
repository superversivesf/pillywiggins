"""Shared test helpers for the pillywiggins test suite."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from pydantic_ai import RunContext

from pillywiggins.agents.deps import AgentDeps
from pillywiggins.skills.registry import Skill


# ---------------------------------------------------------------------------
# Pool mock helper (used by memory tests)
# ---------------------------------------------------------------------------


def make_pool_mock(acquire_return=None):
    """Create a mock asyncpg connection pool with optional acquire context manager.

    Args:
        acquire_return: If provided, the mock pool's acquire() will yield this
            object as an async context manager. If None, acquire() is not set.

    Returns:
        A MagicMock pool with close = AsyncMock().
    """
    mock_pool = MagicMock()
    mock_pool.close = AsyncMock()

    if acquire_return is not None:
        @asynccontextmanager
        async def _acquire():
            yield acquire_return

        mock_pool.acquire = _acquire

    return mock_pool


# ---------------------------------------------------------------------------
# RunContext / AgentDeps helper (used by brain and skill tool tests)
# ---------------------------------------------------------------------------


def make_ctx(
    agent_id="puck",
    channel="discord",
    channel_user_id="",
    metadata=None,
    personality=None,
    private_memory=None,
    skill_registry=None,
    council_memory=None,
    nats_bus=None,
    scheduler=None,
    conversation_key="",
    conversation_info=None,
    logger=None,
    settings=None,
    embedding_model="",
    llm_base_url="",
    llm_api_key="",
    llm_provider="",
    embedding_dimension=0,
):
    """Create a mock RunContext[AgentDeps] with sensible defaults.

    Any parameter accepted by AgentDeps can be passed through.
    """
    ctx = MagicMock(spec=RunContext)
    ctx.deps = AgentDeps(
        agent_id=agent_id,
        channel=channel,
        channel_user_id=channel_user_id,
        metadata=metadata if metadata is not None else {},
        personality=personality,
        private_memory=private_memory,
        skill_registry=skill_registry,
        council_memory=council_memory,
        nats_bus=nats_bus,
        scheduler=scheduler,
        conversation_key=conversation_key,
        conversation_info=conversation_info or (lambda: {"message_count": 0, "estimated_tokens": 0}),
        logger=logger,
        settings=settings,
        embedding_model=embedding_model,
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_provider=llm_provider,
        embedding_dimension=embedding_dimension,
    )
    return ctx


# ---------------------------------------------------------------------------
# Skill helper (used by brain and skill tool tests)
# ---------------------------------------------------------------------------


def make_skill(
    name="test_skill",
    description="A test skill",
    run_func=None,
    meta=None,
    permissions=None,
    file_path=None,
):
    """Create a Skill instance with sensible defaults for testing."""
    if run_func is None:
        run_func = AsyncMock(return_value="ok")
    if meta is None:
        meta = {"name": name, "description": description}
    if permissions is None:
        permissions = {"network": False, "subprocess": False, "file_write": False}
    return Skill(
        name=name,
        description=description,
        run_func=run_func,
        meta=meta,
        permissions=permissions,
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# Adapter mock helpers (used by adapter tests)
# ---------------------------------------------------------------------------


def make_mock_agent(
    agent_id="puck",
    channel="telegram",
    model_name="qwen3.5:8b",
):
    """Create a mock PillywigginAgent with common attributes.

    Returns a MagicMock with agent_id, personality, model_name,
    handle_message, switch_model, clear_history, get_status, and
    compact_history set up.
    """
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.personality = MagicMock()
    agent.personality.channel = channel
    agent.model_name = model_name
    agent.handle_message = AsyncMock(return_value="response")
    agent.switch_model = MagicMock()
    agent.clear_history = AsyncMock()
    agent.get_status = MagicMock(
        return_value={
            "agent_id": agent_id,
            "channel": channel,
            "model_name": model_name,
            "message_count": 7,
            "estimated_tokens": 1500,
        }
    )
    agent.compact_history = AsyncMock(return_value="Compacted: 7 messages → 1 summary")
    return agent


def make_mock_settings(
    llm_base_url="http://localhost:11434",
    llm_api_key="",
    llm_provider="ollama",
    allowed_user_ids="all",
):
    """Create a mock Settings object with common attributes."""
    settings = MagicMock()
    settings.llm_base_url = llm_base_url
    settings.llm_api_key = llm_api_key
    settings.llm_provider = llm_provider
    settings.get_allowed_user_ids = MagicMock(return_value=set())
    settings.allowed_user_ids = allowed_user_ids
    return settings


# ---------------------------------------------------------------------------
# aiohttp mock helpers (used by brave_search, check_website, embeddings tests)
# ---------------------------------------------------------------------------


def make_mock_aiohttp_response(status=200, json_data=None, text_data=None):
    """Create a mock aiohttp response with async context manager support.

    Args:
        status: HTTP status code.
        json_data: If provided, mock_resp.json will be an AsyncMock returning this.
        text_data: If provided, mock_resp.text will be an AsyncMock returning this.
    """
    mock_resp = AsyncMock()
    mock_resp.status = status
    if json_data is not None:
        mock_resp.json = AsyncMock(return_value=json_data)
    if text_data is not None:
        mock_resp.text = AsyncMock(return_value=text_data)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def make_mock_aiohttp_session(method="get", response=None, side_effect=None):
    """Create a mock aiohttp ClientSession with async context manager support.

    Args:
        method: HTTP method to mock ('get' or 'post').
        response: Single mock response to return (used as return_value).
        side_effect: Sequence of responses for sequential calls, or an
            Exception to raise. Takes precedence over response.

    Returns:
        A MagicMock session with __aenter__/__aexit__ support and the
        specified method configured.
    """
    mock_session = AsyncMock()
    if side_effect is not None:
        setattr(mock_session, method, MagicMock(side_effect=side_effect))
    elif response is not None:
        setattr(mock_session, method, MagicMock(return_value=response))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    return mock_session