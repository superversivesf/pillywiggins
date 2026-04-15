import argparse
import asyncio
import logging
from pathlib import Path

from pillywiggins.adapters.telegram_adapter import TelegramAdapter
from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import load_personality
from pillywiggins.config import Settings
from pillywiggins.health import start_health_server
from pillywiggins.memory.cache import ConversationCache
from pillywiggins.memory.private import PrivateMemory
from pillywiggins.memory.store import ConversationStore
from pillywiggins.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Pillywiggins Agent")
    parser.add_argument(
        "--channel",
        required=True,
        choices=["telegram", "discord", "slack", "matrix", "email"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    settings = Settings()
    personality = load_personality(settings.personality_file)
    cache = ConversationCache(redis_url=settings.redis_url)
    store = ConversationStore(database_url=settings.database_url, agent_id=settings.agent_id, channel=settings.channel)
    private_memory = PrivateMemory(database_url=settings.database_url, agent_id=settings.agent_id)
    skill_registry = SkillRegistry(skills_dir=Path(settings.skills_dir))
    skill_registry.load_all()
    agent = PillywigginAgent(
        agent_id=settings.agent_id,
        personality=personality,
        model_name=settings.model_name,
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        cache=cache,
        store=store,
        private_memory=private_memory,
        skill_registry=skill_registry,
        compact_keep_messages=settings.compact_keep_messages,
        compact_truncate_message_chars=settings.compact_truncate_message_chars,
    )

    if args.channel == "telegram":
        adapter = TelegramAdapter(agent=agent, token=settings.telegram_bot_token, settings=settings)
    else:
        raise ValueError(f"Channel {args.channel} not yet implemented")

    logger.info("Starting %s on %s", personality.name, args.channel)

    asyncio.run(_run(adapter, agent, settings))


async def _run(adapter, agent, settings):
    health_runner = await start_health_server(settings)
    try:
        await agent._private_memory.connect()
    except Exception:
        logger.exception("Failed to connect private memory, continuing without it")
        agent._private_memory = None
    try:
        await agent._store.connect()
    except Exception:
        logger.exception("Failed to connect conversation store, continuing without it")
        agent._store = None
    await agent.load_history()
    try:
        await adapter.connect()
        await adapter.listen()
    finally:
        if agent._private_memory is not None:
            await agent._private_memory.close()
        if agent._store is not None:
            await agent._store.close()
        await agent._cache.close()
        await health_runner.cleanup()


if __name__ == "__main__":
    main()