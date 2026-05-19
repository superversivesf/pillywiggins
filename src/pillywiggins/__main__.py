import argparse
import asyncio
import fcntl
import importlib
import logging
import os
import sys
from pathlib import Path

from pillywiggins.agents.base import PillywigginAgent
from pillywiggins.agents.personality import load_personality
from pillywiggins.agents_config import apply_agent_env, get_agent_config
from pillywiggins.config import Settings
from pillywiggins.health import start_health_server
from pillywiggins.memory.cache import ConversationCache
from pillywiggins.memory.private import PrivateMemory
from pillywiggins.memory.store import ConversationStore
from pillywiggins.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def _load_adapter_class(channel: str):
    """Dynamically import the adapter class for the given channel name.

    Naming convention: ``<channel>_adapter`` module containing
    ``<Channel>Adapter`` class (e.g. ``telegram`` → ``TelegramAdapter``).
    """
    adapter_name = f"{channel}_adapter"
    class_name = f"{channel.capitalize()}Adapter"
    module_path = f"pillywiggins.adapters.{adapter_name}"
    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise ImportError(f"Adapter for channel '{channel}' not found ({module_path})") from exc
    try:
        return getattr(mod, class_name)
    except AttributeError as exc:
        raise ImportError(f"Adapter class '{class_name}' not found in {module_path}") from exc


def _acquire_agent_lock(agent_id: str) -> None:
    """Acquire an exclusive fcntl lock for this agent_id.

    If another process already holds the lock, log an error and exit.
    The lock is automatically released when the process exits.
    """
    lock_path = f"/tmp/pillywiggins-{agent_id}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.error(
            "Another instance of agent '%s' is already running. "
            "Stop it first with: docker compose stop %s",
            agent_id,
            agent_id,
        )
        sys.exit(1)


def _check_agents_config_directory(path: str) -> None:
    """Exit with a clear error if *path* is a directory (not a file or
    symlink-to-file).

    Docker Compose bind mounts create a directory at ``./agents.yaml``
    when the configured host file does not exist, which produces an
    ``IsADirectoryError`` later when :func:`load_agents_config` tries
    to open it.  This guard catches that situation at startup and
    prints an actionable fix.
    """
    p = Path(path)
    if p.is_dir():
        print(
            f"ERROR: {path} is a directory, not a file.\n"
            f"Docker Compose bind mounts create a directory if the file "
            f"does not exist.\n"
            f"Fix:  cp agents.yaml.example {path}",
            file=sys.stderr,
        )
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Pillywiggins Agent")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("onboard", help="Interactive onboarding wizard")

    test_parser = subparsers.add_parser(
        "test", help="Black-box test suite setup and execution"
    )
    test_parser.add_argument(
        "--config",
        default=".blackbox_config.json",
        help="Path to blackbox config file (default: .blackbox_config.json)",
    )
    test_parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Run scenarios directly (skip setup wizard)",
    )

    import_parser = subparsers.add_parser(
        "import-skills", help="Import Claude-style skills to Pillywiggins format"
    )
    import_parser.add_argument(
        "--source",
        required=True,
        help="Path to .skill.md file or directory of skills",
    )
    import_parser.add_argument(
        "--output",
        default="skills",
        help="Output directory for generated skill files (default: skills/)",
    )

    parser.add_argument(
        "--agent-id",
        required=False,
        default=None,
    )
    args = parser.parse_args()

    if args.command == "onboard":
        from pillywiggins.onboard import onboard

        asyncio.run(onboard())
        return

    if args.command == "test":
        if args.run:
            from tests.blackbox.runner import main as test_main

            test_main(config_path=args.config)
        else:
            from tests.blackbox.cli import setup_wizard

            setup_wizard(config_path=args.config)
        return

    if args.command == "import-skills":
        from pillywiggins.skills.claude_importer import import_claude_skills

        imported = import_claude_skills(args.source, args.output)
        if imported:
            print(f"Imported {len(imported)} skill(s):")
            for p in imported:
                print(f"  {p}")
        else:
            print("No skills found to import.")
        return

    if not args.agent_id:
        parser.error("--agent-id is required")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = Settings()
    settings.resolve_embedding_config()

    _check_agents_config_directory(settings.agents_config_path)

    agent_cfg = get_agent_config(args.agent_id, path=settings.agents_config_path)
    apply_agent_env(agent_cfg)
    settings = Settings()
    settings.resolve_embedding_config()
    personality = load_personality(agent_cfg.personality)
    agent_id = agent_cfg.id
    channel = agent_cfg.channel
    allowed_user_ids = agent_cfg.allowed_user_ids

    _acquire_agent_lock(agent_id)

    cache = ConversationCache(redis_url=settings.redis_url)
    store = ConversationStore(
        database_url=settings.database_url, agent_id=agent_id, channel=channel
    )
    private_memory = PrivateMemory(database_url=settings.database_url, agent_id=agent_id, embedding_dimension=settings.embedding_dimension)
    skill_registry = SkillRegistry(skills_dir=Path(settings.skills_dir), agent_id=agent_id)
    skill_registry.load_all()
    agent = PillywigginAgent(
        agent_id=agent_id,
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
        database_url=settings.database_url,
        nats_url=settings.nats_url,
    )

    AdapterClass = _load_adapter_class(channel)

    token_attr = f"{channel}_bot_token"
    token = getattr(settings, token_attr, None)
    if token is None:
        raise ValueError(f"Missing token setting: {token_attr}")

    adapter = AdapterClass(agent=agent, token=token, settings=settings)

    agent.set_adapter(adapter)

    logger.info("Starting %s on %s", personality.name, channel)

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
    await agent.start()
    try:
        await adapter.connect()
        await adapter.listen()
    finally:
        await agent.shutdown()
        if agent._private_memory is not None:
            await agent._private_memory.close()
        if agent._store is not None:
            await agent._store.close()
        await agent._cache.close()
        await health_runner.cleanup()


if __name__ == "__main__":
    main()
