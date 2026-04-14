import argparse
import asyncio
import logging

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import load_personality
from pillywiggins.adapters.telegram_adapter import TelegramAdapter
from pillywiggins.config import Settings

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
    agent = PillywigginAgent(
        agent_id=settings.agent_id,
        personality=personality,
        model_name=settings.model_name,
        provider=settings.llm_provider,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
    )

    if args.channel == "telegram":
        adapter = TelegramAdapter(agent=agent, token=settings.telegram_bot_token, settings=settings)
    else:
        raise ValueError(f"Channel {args.channel} not yet implemented")

    logger.info("Starting %s on %s", personality.name, args.channel)

    asyncio.run(_run(adapter))


async def _run(adapter):
    await adapter.connect()
    await adapter.listen()


if __name__ == "__main__":
    main()