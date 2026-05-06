import logging
import re
import shutil
import subprocess
from pathlib import Path

import aiohttp
import questionary
import yaml

PERSONALITIES_DIR = Path("personalities")
AGENTS_YAML = Path("agents.yaml")
AGENTS_YAML_EXAMPLE = Path("agents.yaml.example")
DOCKER_COMPOSE = Path("docker-compose.yaml")
DOCKER_COMPOSE_EXAMPLE = Path("docker-compose.yaml.example")
ENV_FILE = Path(".env")
ENV_EXAMPLE = Path("env.example")

COMPOSE_DEPENDS_ON = {
    "postgres": {"condition": "service_healthy"},
    "redis": {"condition": "service_healthy"},
    "nats": {"condition": "service_healthy"},
}

COMPOSE_NETWORKS = ["pillywiggins"]

COMPOSE_VOLUMES = [
    "./personalities:/config:ro",
    "./agents.yaml:/app/agents.yaml:ro",
    "./skills:/app/skills",
]

LLM_ENV_KEYS = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "MODEL_NAME")

COMMON_TIMEZONES = [
    "UTC",
    "America/Los_Angeles",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Kolkata",
    "Australia/Sydney",
    "Pacific/Auckland",
]

CUSTOM_TIMEZONE_OPTION = "Type custom timezone"

B = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
RED = "\033[31m"
RESET = "\033[0m"

logger = logging.getLogger(__name__)


def _host_url(url: str) -> str:
    return url.replace("host.docker.internal", "localhost")


def ensure_config_files() -> None:
    if not AGENTS_YAML.exists() and AGENTS_YAML_EXAMPLE.exists():
        shutil.copy2(AGENTS_YAML_EXAMPLE, AGENTS_YAML)
    if not DOCKER_COMPOSE.exists() and DOCKER_COMPOSE_EXAMPLE.exists():
        shutil.copy2(DOCKER_COMPOSE_EXAMPLE, DOCKER_COMPOSE)
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def read_text(path: Path) -> str:
    with open(path) as f:
        return f.read()


def write_text(path: Path, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)


def _read_env_dict(path: Path) -> dict[str, str]:
    """Read a .env file into a key-value dict (preserving comments)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, val = stripped.partition("=")
            result[key.strip()] = val.strip()
    return result


def _write_env_dict(path: Path, data: dict[str, str]) -> None:
    """Write a key-value dict back to a .env file, preserving comments."""
    if not path.exists():
        path.write_text("")
    lines = path.read_text().splitlines()
    out_lines: list[str] = []
    written_keys: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        if "=" in stripped:
            key, _, _ = stripped.partition("=")
            key = key.strip()
            if key in data:
                out_lines.append(f"{key}={data[key]}")
                written_keys.add(key)
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)
    # Append any new keys at the end
    for key, val in data.items():
        if key not in written_keys:
            out_lines.append(f"{key}={val}")
    path.write_text("\n".join(out_lines) + "\n")


def discover_personalities() -> list[dict]:
    results = []
    if not PERSONALITIES_DIR.exists():
        return results
    for yml in sorted(PERSONALITIES_DIR.rglob("*.yaml")):
        if yml.name == "pack.yaml":
            continue
        with open(yml) as f:
            data = yaml.safe_load(f)
        if data and "name" in data:
            rel = yml.relative_to(PERSONALITIES_DIR)
            pack = rel.parent.as_posix() if rel.parent != Path(".") else None
            results.append(
                {
                    "filename": str(rel),
                    "stem": yml.stem,
                    "name": data["name"],
                    "description": data.get("description", ""),
                    "channel": data.get("channel", "telegram"),
                    "bot_chat_limit": data.get("bot_chat_limit", 3),
                    "pack": pack,
                }
            )
    return results


def discover_packs() -> list[dict]:
    results = []
    if not PERSONALITIES_DIR.exists():
        return results
    for sub in sorted(PERSONALITIES_DIR.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        pack_manifest = sub / "pack.yaml"
        pack_name = sub.name.replace("_", " ").title()
        pack_desc = ""
        pack_category = ""
        if pack_manifest.exists():
            with open(pack_manifest) as f:
                data = yaml.safe_load(f) or {}
            pack_name = data.get("name", pack_name)
            pack_desc = data.get("description", "")
            pack_category = data.get("category", "")
        personality_count = sum(1 for y in sub.glob("*.yaml") if y.name != "pack.yaml")
        if personality_count == 0:
            continue
        results.append(
            {
                "name": pack_name,
                "description": pack_desc,
                "category": pack_category,
                "path": sub.name,
                "personality_count": personality_count,
            }
        )
    return results


def load_existing_agents() -> list[dict]:
    if not AGENTS_YAML.exists():
        return []
    data = load_yaml(AGENTS_YAML)
    return data.get("agents", [])


def agent_ids_in_use() -> set[str]:
    return {a["id"] for a in load_existing_agents()}


async def validate_telegram_token(token: str) -> tuple[bool, str]:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return (False, f"HTTP {resp.status}")
                try:
                    body = await resp.json()
                except Exception:
                    return (False, "Invalid JSON response")
                if not body.get("ok"):
                    return (False, body.get("description", "Request not ok"))
                result = body.get("result")
                if not result or not result.get("username"):
                    return (False, "Missing result.username in response")
                return (True, result["username"])
    except aiohttp.ClientError as exc:
        return (False, f"Connection error: {exc}")
    except TimeoutError:
        return (False, "Request timed out")
    except Exception as exc:
        return (False, f"Unexpected error: {exc}")


from pillywiggins.adapters.models import list_models


def get_default_llm_config() -> dict:
    env_path = Path(".env")
    if not env_path.is_file():
        return {k: "" for k in LLM_ENV_KEYS}
    result = {k: "" for k in LLM_ENV_KEYS}
    try:
        text = env_path.read_text(encoding="utf-8")
    except Exception:
        return result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key in result:
            result[key] = value
    return result


def get_first_agent_llm_config() -> dict | None:
    agents = load_existing_agents()
    if not agents:
        return None
    first = agents[0]
    env = first.get("environment", {})
    result = {}
    for key in LLM_ENV_KEYS:
        if key in env:
            result[key] = env[key]
    return result if result else None


def _token_env_for_agent(agent_id: str, channel: str = "telegram") -> str:
    suffix = channel.upper()
    return f"{agent_id.upper()}_{suffix}_TOKEN"


def _personality_path_for(personality_filename: str) -> str:
    return f"/config/{personality_filename}"


def add_agent_to_agents_yaml(
    agent_id: str,
    personality_filename: str,
    channel: str,
    token_env: str,
    allowed_user_ids: str,
    bot_chat_limit: int,
    llm_config: dict | None,
    timezone: str = "UTC",
) -> None:
    personality_path = _personality_path_for(personality_filename)

    if AGENTS_YAML.exists():
        data = load_yaml(AGENTS_YAML)
    else:
        data = {"agents": []}

    if "agents" not in data:
        data["agents"] = []

    for entry in data["agents"]:
        if entry.get("id") == agent_id:
            logger.warning(f"Agent '{agent_id}' already exists in agents.yaml")
            return

    environment = {
        "TELEGRAM_BOT_TOKEN": f"${{{token_env}}}",
        "TIMEZONE": timezone,
        "TZ": timezone,
    }
    # Always write per-agent LLM vars when a config is provided.
    # LLM_PROVIDER, LLM_BASE_URL, MODEL_NAME are literal values.
    # LLM_API_KEY references {AGENT_ID}_LLM_API_KEY from .env.
    if llm_config:
        if llm_config.get("LLM_PROVIDER"):
            environment["LLM_PROVIDER"] = llm_config["LLM_PROVIDER"]
        if llm_config.get("LLM_BASE_URL"):
            environment["LLM_BASE_URL"] = llm_config["LLM_BASE_URL"]
        if llm_config.get("LLM_API_KEY"):
            environment["LLM_API_KEY"] = f"${{{agent_id.upper()}_LLM_API_KEY}}"
        if llm_config.get("MODEL_NAME"):
            environment["MODEL_NAME"] = llm_config["MODEL_NAME"]

    entry = {
        "id": agent_id,
        "personality": personality_path,
        "channel": channel,
        "allowed_user_ids": allowed_user_ids,
        "bot_chat_limit": bot_chat_limit,
        "timezone": timezone,
        "environment": environment,
    }

    data["agents"].append(entry)
    save_yaml(AGENTS_YAML, data)
    logger.info(f"Added '{agent_id}' to agents.yaml")


def add_agent_to_docker_compose(
    agent_id: str,
    personality_filename: str,
    token_env: str,
    llm_config: dict | None = None,
    timezone: str = "UTC",
) -> None:
    personality_path = _personality_path_for(personality_filename)

    if DOCKER_COMPOSE.exists():
        compose = load_yaml(DOCKER_COMPOSE)
    else:
        compose = {"services": {}, "volumes": {}}

    if "services" not in compose:
        compose["services"] = {}

    if agent_id in compose["services"]:
        logger.warning(f"Service '{agent_id}' already exists in docker-compose.yaml")
        return

    service_env = {
        "AGENT_ID": agent_id,
        "TELEGRAM_BOT_TOKEN": f"${{{token_env}}}",
        "PERSONALITY_FILE": personality_path,
        "NATS_URL": "nats://nats:4222",
        "TIMEZONE": timezone,
        "TZ": timezone,
    }
    # Add per-agent LLM vars to docker-compose environment section.
    # LLM_PROVIDER, LLM_BASE_URL, MODEL_NAME are literal values.
    # LLM_API_KEY references the per-agent var from .env.
    if llm_config:
        if llm_config.get("LLM_PROVIDER"):
            service_env["LLM_PROVIDER"] = llm_config["LLM_PROVIDER"]
        if llm_config.get("LLM_BASE_URL"):
            service_env["LLM_BASE_URL"] = llm_config["LLM_BASE_URL"]
        if llm_config.get("LLM_API_KEY"):
            service_env["LLM_API_KEY"] = f"${{{agent_id.upper()}_LLM_API_KEY}}"
        if llm_config.get("MODEL_NAME"):
            service_env["MODEL_NAME"] = llm_config["MODEL_NAME"]

    service = {
        "build": ".",
        "command": f"python -m pillywiggins --agent-id {agent_id}",
        "env_file": ".env",
        "restart": "unless-stopped",
        "extra_hosts": ["host.docker.internal:host-gateway"],
        "environment": service_env,
        "volumes": list(COMPOSE_VOLUMES),
        "depends_on": dict(COMPOSE_DEPENDS_ON),
        "networks": list(COMPOSE_NETWORKS),
        "healthcheck": {
            "test": ["CMD-SHELL", "ps aux | grep -v grep | grep pillywiggins || exit 1"],
            "interval": "10s",
            "timeout": "5s",
            "retries": 3,
        },
    }

    compose["services"][agent_id] = service

    # Ensure the 'networks' top-level key exists in the compose file
    if "networks" not in compose:
        compose["networks"] = {}
    if "pillywiggins" not in compose["networks"]:
        compose["networks"]["pillywiggins"] = {"driver": "bridge"}

    if "volumes" not in compose:
        compose["volumes"] = {}
    for vol in ["pgdata", "redisdata", "searxng_data"]:
        if vol not in compose["volumes"]:
            compose["volumes"][vol] = None

    save_yaml(DOCKER_COMPOSE, compose)
    logger.info(f"Added '{agent_id}' service to docker-compose.yaml")


def add_token_to_env(agent_id: str, token_value: str, env_path: Path = ENV_FILE, channel: str = "telegram") -> None:
    token_env = _token_env_for_agent(agent_id, channel)
    token_line = f"{token_env}={token_value}"

    if not env_path.exists():
        lines = [
            "# Pillywiggins Environment Configuration",
            "",
            "# --- Agent Credentials ---",
            token_line,
        ]
        write_text(env_path, "\n".join(lines) + "\n")
        logger.info(f"Created {env_path} with {token_env}")
        return

    content = read_text(env_path)

    if token_env in content:
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            stripped = line.strip().lstrip("#")
            if stripped.startswith(f"{token_env}="):
                new_lines.append(token_line)
            else:
                new_lines.append(line)
        write_text(env_path, "\n".join(new_lines))
        logger.info(f"Updated {token_env} in {env_path}")
        return

    lines = content.split("\n")
    new_lines = []
    inserted = False

    for line in lines:
        new_lines.append(line)
        if not inserted and "Agent Credentials" in line:
            new_lines.append(token_line)
            inserted = True

    if not inserted:
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and re.match(r"^[A-Z_]+_(TOKEN|SECRET|PASSWORD)=", line):
                new_lines.append(token_line)
                inserted = True

    if not inserted:
        new_lines.append("")
        new_lines.append("# --- Agent Credentials ---")
        new_lines.append(token_line)

    write_text(env_path, "\n".join(new_lines))
    logger.info(f"Added {token_env} to {env_path}")


def add_llm_api_key_to_env(agent_id: str, api_key: str, env_path: Path = ENV_FILE) -> None:
    key_env = f"{agent_id.upper()}_LLM_API_KEY"
    key_line = f"{key_env}={api_key}"

    if not env_path.exists():
        return

    content = read_text(env_path)

    if key_env in content:
        lines = content.split("\n")
        new_lines = []
        for line in lines:
            if line.strip().startswith(f"{key_env}="):
                new_lines.append(key_line)
            else:
                new_lines.append(line)
        write_text(env_path, "\n".join(new_lines))
        return

    lines = content.split("\n")
    new_lines = []
    inserted = False

    for line in lines:
        new_lines.append(line)
        if not inserted and "LLM Provider" in line:
            new_lines.append(key_line)
            inserted = True

    if not inserted:
        for line in lines:
            new_lines.append(line)
            if not inserted and re.match(r"^LLM_API_KEY=", line):
                new_lines.append(key_line)
                inserted = True

    if not inserted:
        new_lines.append("")
        new_lines.append("# --- Per-Agent LLM API Keys ---")
        new_lines.append(key_line)

    write_text(env_path, "\n".join(new_lines))
    logger.info(f"Added {key_env} to {env_path}")


def add_brave_api_key_to_env(api_key: str, env_path: Path = ENV_FILE) -> None:
    key_line = f"BRAVE_API_KEY={api_key}"

    if not env_path.exists():
        return

    content = read_text(env_path)
    lines = content.split("\n")

    # Update existing key
    for i, line in enumerate(lines):
        if line.strip().startswith("BRAVE_API_KEY="):
            lines[i] = key_line
            write_text(env_path, "\n".join(lines))
            logger.info(f"Updated BRAVE_API_KEY in {env_path}")
            return

    # Insert after search-related section
    for i, line in enumerate(lines):
        if "Search" in line or "SEARXNG" in line or "BRAVE" in line:
            lines.insert(i + 1, key_line)
            write_text(env_path, "\n".join(lines))
            logger.info(f"Added BRAVE_API_KEY to {env_path}")
            return

    # Append at end with header
    lines.append("")
    lines.append("# --- Search Configuration ---")
    lines.append(key_line)
    write_text(env_path, "\n".join(lines))
    logger.info(f"Added BRAVE_API_KEY to {env_path}")


def add_agent_to_configs(
    agent_id: str,
    personality_filename: str,
    channel: str,
    token_env: str,
    allowed_user_ids: str,
    bot_chat_limit: int,
    llm_config: dict | None,
    token_value: str = "",
    timezone: str = "UTC",
) -> None:
    add_agent_to_agents_yaml(
        agent_id,
        personality_filename,
        channel,
        token_env,
        allowed_user_ids,
        bot_chat_limit,
        llm_config,
        timezone=timezone,
    )
    add_agent_to_docker_compose(
        agent_id, personality_filename, token_env, llm_config=llm_config, timezone=timezone
    )
    if token_value:
        add_token_to_env(agent_id, token_value, channel=channel)
    if llm_config and llm_config.get("LLM_API_KEY"):
        add_llm_api_key_to_env(agent_id, llm_config["LLM_API_KEY"])


def remove_agent_from_agents_yaml(agent_id: str) -> None:
    if not AGENTS_YAML.exists():
        return
    data = load_yaml(AGENTS_YAML)
    if "agents" not in data:
        return
    data["agents"] = [a for a in data["agents"] if a.get("id") != agent_id]
    save_yaml(AGENTS_YAML, data)
    logger.info(f"Removed '{agent_id}' from agents.yaml")


def remove_agent_from_docker_compose(agent_id: str) -> None:
    if not DOCKER_COMPOSE.exists():
        return
    compose = load_yaml(DOCKER_COMPOSE)
    if "services" not in compose:
        return
    if agent_id in compose["services"]:
        del compose["services"][agent_id]
    save_yaml(DOCKER_COMPOSE, compose)
    logger.info(f"Removed '{agent_id}' service from docker-compose.yaml")


def comment_token_in_env(agent_id: str, env_path: Path = ENV_FILE) -> None:
    token_env = _token_env_for_agent(agent_id)
    if not env_path.exists():
        return
    content = read_text(env_path)
    lines = content.split("\n")
    new_lines = []
    changed = False

    for line in lines:
        if line.strip().startswith(f"{token_env}="):
            value = line.split("=", 1)[1] if "=" in line else ""
            new_lines.append(f"#{token_env}={value}")
            changed = True
        else:
            new_lines.append(line)

    if changed:
        write_text(env_path, "\n".join(new_lines))
        logger.info(f"Commented out {token_env} in {env_path}")


def remove_agent_from_configs(agent_id: str) -> None:
    remove_agent_from_agents_yaml(agent_id)
    remove_agent_from_docker_compose(agent_id)
    comment_token_in_env(agent_id)


async def _add_agent_flow() -> None:
    personalities = discover_personalities()
    if not personalities:
        logger.warning("No personality files found in personalities/")
        return

    personality = None  # initialise to avoid UnboundLocalError
    is_blank = False

    # 0. Pack selection
    packs = discover_packs()
    selected_pack = None
    if packs:
        pack_choices = [
            questionary.Choice(title=f"{p['name']} ({p['personality_count']} personalities) — {p['description']}", value=p["path"])
            for p in packs
        ]
        pack_choices.append(questionary.Choice(title="Browse all personalities", value="__all__"))
        pack_choices.append(questionary.Choice(title="Start blank (no personality)", value="__blank__"))
        pack_choice = await questionary.select(
            "Choose a personality pack:",
            choices=pack_choices,
        ).ask_async()
        if pack_choice is None:
            return
        if pack_choice == "__blank__":
            is_blank = True
        elif pack_choice != "__all__":
            selected_pack = pack_choice
    else:
        pack_choice = await questionary.select(
            "No packs found. Choose:",
            choices=[
                questionary.Choice(title="Browse all personalities", value="__all__"),
                questionary.Choice(title="Start blank (no personality)", value="__blank__"),
            ],
        ).ask_async()
        if pack_choice is None:
            return
        if pack_choice == "__blank__":
            is_blank = True

    # 1. Personality selection
    if is_blank:
        pass  # blank — no personality to select
    else:
        if selected_pack:
            filtered = [p for p in personalities if p.get("pack") == selected_pack]
        else:
            filtered = personalities
        choices = [f"{p['name']} — {p['description']}" for p in filtered]
        choice = await questionary.select("Select a personality:", choices=choices).ask_async()
        if choice is None:
            return

        idx = choices.index(choice)
        personality = filtered[idx]

    # 2. Channel selection
    channel = await questionary.select(
        "Select channel:",
        choices=[
            questionary.Choice(title="Telegram", value="telegram"),
            questionary.Choice(title="Discord", value="discord"),
            questionary.Choice(title="Slack", value="slack"),
            questionary.Choice(title="Matrix", value="matrix"),
            questionary.Choice(title="Email", value="email"),
        ],
    ).ask_async()
    if channel is None:
        return

    # 3. Agent ID — default to personality stem, user can override
    default_agent_id = personality["stem"] if personality else ""
    agent_id = await questionary.text(
        "Agent ID (lowercase, used as service name):",
        default=default_agent_id,
        validate=lambda v: (
            True
            if v and re.match(r"^[a-z][a-z0-9_-]*$", v)
            else "Must be lowercase, start with a letter, letters/dashes/underscores only"
        ),
    ).ask_async()
    if agent_id is None:
        return

    existing_ids = agent_ids_in_use()
    if agent_id in existing_ids:
        overwrite = await questionary.confirm(
            f"Agent '{agent_id}' already exists. Replace it?",
            default=False,
        ).ask_async()
        if not overwrite:
            return
        remove_agent_from_configs(agent_id)

    # 4. Token / credential setup (channel-specific)
    if channel == "telegram":
        token = await questionary.text(
            "Enter Telegram bot token (from @BotFather):",
            validate=lambda t: (
                True if t and len(t) > 10 else "Token too short, enter a valid bot token"
            ),
        ).ask_async()
        if token is None:
            return
        valid, info = await validate_telegram_token(token)
        if not valid:
            logger.warning(f"Token validation failed: {info}")
            confirm = await questionary.confirm("Continue anyway?", default=False).ask_async()
            if not confirm:
                return
            bot_info = "(validation failed)"
        else:
            logger.info(f"Token valid! Bot: @{info}")
            bot_info = f"@{info}"
    elif channel == "discord":
        token = await questionary.text(
            "Enter Discord bot token:",
            validate=lambda t: True if t and len(t) > 20 else "Token too short",
        ).ask_async()
        if token is None:
            return
        bot_info = "(Discord)"
    elif channel == "slack":
        token = await questionary.text(
            "Enter Slack bot token (xoxb-...):",
            validate=lambda t: True if t and t.startswith("xoxb") else "Must start with xoxb-",
        ).ask_async()
        if token is None:
            return
        bot_info = "(Slack)"
    elif channel == "matrix":
        homeserver = await questionary.text(
            "Matrix homeserver URL (e.g. https://matrix.example.com):",
            default="https://matrix.example.com",
        ).ask_async()
        if homeserver is None:
            return
        access_token = await questionary.text(
            "Matrix access token:",
            validate=lambda t: True if t and len(t) > 10 else "Token too short",
        ).ask_async()
        if access_token is None:
            return
        token = f"{homeserver}\n{access_token}"
        bot_info = "(Matrix)"
    elif channel == "email":
        smtp_host = await questionary.text(
            "SMTP host:",
            default="smtp.gmail.com",
        ).ask_async()
        if smtp_host is None:
            return
        smtp_port = await questionary.text(
            "SMTP port:",
            default="587",
        ).ask_async()
        if smtp_port is None:
            return
        smtp_user = await questionary.text(
            "SMTP user (email address):",
        ).ask_async()
        if smtp_user is None:
            return
        smtp_password = await questionary.password(
            "SMTP password:",
        ).ask_async()
        if smtp_password is None:
            return
        imap_host = await questionary.text(
            "IMAP host:",
            default="imap.gmail.com",
        ).ask_async()
        if imap_host is None:
            return
        imap_port = await questionary.text(
            "IMAP port:",
            default="993",
        ).ask_async()
        if imap_port is None:
            return
        token = f"{smtp_host}\n{smtp_port}\n{smtp_user}\n{smtp_password}\n{imap_host}\n{imap_port}"
        bot_info = "(Email)"
    else:
        token = ""
        bot_info = "(unknown channel)"

    # Optional Brave Search API key (prompt alongside credentials — can skip)
    env = _read_env_dict(ENV_FILE)
    existing_brave_key = env.get("BRAVE_API_KEY", "")
    brave_api_key = await questionary.text(
        "Brave Search API key (optional — press Enter to skip):",
        default=existing_brave_key,
    ).ask_async()
    if brave_api_key:
        add_brave_api_key_to_env(brave_api_key)

    # 5. LLM provider + model — default to first agent's config if available
    existing_llm = get_first_agent_llm_config()
    defaults = get_default_llm_config()
    if existing_llm:
        defaults = {k: existing_llm.get(k, defaults.get(k, "")) for k in LLM_ENV_KEYS}

    llm_provider = await questionary.select(
        "Select LLM provider:",
        choices=["ollama", "openai"],
        default=defaults.get("LLM_PROVIDER", "ollama") or "ollama",
    ).ask_async()
    if llm_provider is None:
        return

    if llm_provider == "ollama":
        default_base = defaults.get("LLM_BASE_URL") or "http://host.docker.internal:11434/v1"
    else:
        default_base = defaults.get("LLM_BASE_URL") or "https://api.openai.com/v1"

    llm_base_url = await questionary.text(
        "LLM base URL:",
        default=default_base,
    ).ask_async()
    if llm_base_url is None:
        return

    llm_api_key = ""
    if llm_provider == "openai" or "ollama.com" in llm_base_url:
        default_key = defaults.get("LLM_API_KEY", "")
        llm_api_key = await questionary.text(
            "LLM API key (leave blank if not needed):",
            default=default_key,
        ).ask_async()
        if llm_api_key is None:
            return

    model_infos = await list_models(_host_url(llm_base_url), llm_api_key, llm_provider)
    models = sorted(m.id for m in model_infos if m.id)
    if models:
        default_model = defaults.get("MODEL_NAME", "")
        if default_model not in models:
            default_model = models[0]
        chosen_model = await questionary.select(
            "Select model:",
            choices=models,
            default=default_model,
        ).ask_async()
        if chosen_model is None:
            return
    else:
        chosen_model = await questionary.text(
            "Model name (could not poll models from provider):",
            default=defaults.get("MODEL_NAME", "qwen3.5:8b"),
        ).ask_async()
        if chosen_model is None:
            return

    # 6. Allowed users
    default_uids = "all"
    for a in load_existing_agents():
        uid = a.get("allowed_user_ids", "all")
        if uid != "all":
            default_uids = uid
            break

    allowed_user_ids = await questionary.text(
        "Allowed user IDs (comma-separated, or 'all'):",
        default=default_uids,
    ).ask_async()
    if allowed_user_ids is None:
        return

    # 7. Bot chat limit
    default_limit = str(personality.get("bot_chat_limit", 3))
    bot_chat_limit_str = await questionary.text(
        "Bot chat limit (max consecutive bot-to-bot replies, 0=never, -1=unlimited):",
        default=default_limit,
    ).ask_async()
    if bot_chat_limit_str is None:
        return
    try:
        bot_chat_limit = int(bot_chat_limit_str)
    except ValueError:
        bot_chat_limit = 3

    # 8. Timezone
    default_tz = "UTC"
    for a in load_existing_agents():
        tz = a.get("timezone", "UTC")
        if tz != "UTC":
            default_tz = tz
            break

    tz_choices = COMMON_TIMEZONES + [CUSTOM_TIMEZONE_OPTION]
    tz_choice = await questionary.select(
        "Select timezone:",
        choices=tz_choices,
        default=default_tz,
    ).ask_async()
    if tz_choice is None:
        return
    if tz_choice == CUSTOM_TIMEZONE_OPTION:
        tz = await questionary.text(
            "Enter timezone (e.g. America/Los_Angeles):",
            default=default_tz,
        ).ask_async()
        if tz is None:
            return
    else:
        tz = tz_choice

    # 9. Review
    token_env = _token_env_for_agent(agent_id, channel)

    llm_config = {
        "LLM_PROVIDER": llm_provider,
        "LLM_BASE_URL": llm_base_url,
        "LLM_API_KEY": llm_api_key,
        "MODEL_NAME": chosen_model,
    }

    logger.info("\n--- Review ---")
    logger.info(f"  Agent ID:       {agent_id}")
    logger.info(f"  Personality:    {personality['name']} ({personality['filename']})")
    logger.info(f"  Channel:        {channel}")
    logger.info(f"  Bot:            {bot_info}")
    logger.info(f"  Token env var:  {token_env}")
    logger.info(f"  LLM provider:   {llm_provider}")
    logger.info(f"  LLM base URL:   {llm_base_url}")
    logger.info(f"  Model:          {chosen_model}")
    logger.info(f"  Allowed users:  {allowed_user_ids}")
    logger.info(f"  Bot chat limit: {bot_chat_limit}")
    logger.info(f"  Timezone:       {tz}")
    if llm_api_key:
        logger.info(f"  API key:        {'*' * 8}{llm_api_key[-4:]}")
    logger.info("")

    confirm = await questionary.confirm("Write configs and start agent?", default=True).ask_async()
    if not confirm:
        return

    # 10. Write configs
    add_agent_to_configs(
        agent_id=agent_id,
        personality_filename=personality["filename"],
        channel=channel,
        token_env=token_env,
        allowed_user_ids=allowed_user_ids,
        bot_chat_limit=bot_chat_limit,
        llm_config=llm_config,
        token_value=token,
        timezone=tz,
    )

    # 11. Docker up
    start = await questionary.confirm(
        "Build and start all services now?",
        default=True,
    ).ask_async()
    if start:
        logger.info("Building and starting all services...")
        try:
            subprocess.run(["docker", "compose", "up", "-d", "--build"], check=False)
        except FileNotFoundError:
            logger.warning("docker compose not found. Run manually: docker compose up -d --build")
    else:
        logger.info("Run when ready: docker compose up -d --build")


async def _reconfigure_agent_flow() -> None:
    agents = load_existing_agents()
    if not agents:
        logger.warning("No agents found in agents.yaml")
        return

    choices = [a["id"] for a in agents]
    agent_id = await questionary.select("Select agent to reconfigure:", choices=choices).ask_async()
    if agent_id is None:
        return

    agent_data = None
    for a in agents:
        if a["id"] == agent_id:
            agent_data = a
            break

    if not agent_data:
        return

    env = agent_data.get("environment", {})
    current_uids = agent_data.get("allowed_user_ids", "all")
    current_tz = agent_data.get("timezone", "UTC")

    # Allowed users
    new_uids = await questionary.text(
        "Allowed user IDs (comma-separated, or 'all'):",
        default=current_uids,
    ).ask_async()
    if new_uids is None:
        return

    # Timezone
    tz_choices = COMMON_TIMEZONES + [CUSTOM_TIMEZONE_OPTION]
    default_tz = current_tz if current_tz in COMMON_TIMEZONES else "UTC"
    tz_choice = await questionary.select(
        "Select timezone:",
        choices=tz_choices,
        default=default_tz,
    ).ask_async()
    if tz_choice is None:
        return
    if tz_choice == CUSTOM_TIMEZONE_OPTION:
        new_tz = await questionary.text(
            "Enter timezone (e.g. America/Los_Angeles):",
            default=current_tz,
        ).ask_async()
        if new_tz is None:
            return
    else:
        new_tz = tz_choice

    # Token
    new_token = await questionary.text(
        "Telegram bot token (press Enter to keep current):",
        default="",
    ).ask_async()
    if new_token is None:
        return

    # LLM config — always prompt, prefill from current agent's environment
    defaults = get_default_llm_config()
    current_provider = env.get("LLM_PROVIDER", defaults.get("LLM_PROVIDER", "ollama"))
    current_base_url = env.get(
        "LLM_BASE_URL", defaults.get("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
    )
    current_model = env.get("MODEL_NAME", defaults.get("MODEL_NAME", "qwen3.5:8b"))

    new_provider = await questionary.select(
        "LLM provider:",
        choices=["ollama", "openai"],
        default=current_provider,
    ).ask_async()
    if new_provider is None:
        return

    new_base_url = await questionary.text(
        "LLM base URL:",
        default=current_base_url,
    ).ask_async()
    if new_base_url is None:
        return

    llm_api_key = ""
    existing_has_api_key = "LLM_API_KEY" in env
    needs_key = new_provider == "openai" or "ollama.com" in new_base_url
    if needs_key:
        llm_api_key = await questionary.text(
            "LLM API key (leave blank to keep current):",
            default="",
        ).ask_async()
        if llm_api_key is None:
            return

    model_infos = await list_models(_host_url(new_base_url), llm_api_key or None, new_provider)
    models = sorted(m.id for m in model_infos if m.id)
    if models:
        default_model = current_model if current_model in models else models[0]
        new_model = await questionary.select(
            "Select model:",
            choices=models,
            default=default_model,
        ).ask_async()
        if new_model is None:
            return
    else:
        new_model = await questionary.text(
            "Model name:",
            default=current_model,
        ).ask_async()
        if new_model is None:
            return

    agent_data["allowed_user_ids"] = new_uids
    agent_data["timezone"] = new_tz

    # Build new environment — always include per-agent LLM vars
    new_env = {"TELEGRAM_BOT_TOKEN": env.get("TELEGRAM_BOT_TOKEN", "")}

    if new_provider:
        new_env["LLM_PROVIDER"] = new_provider
    if new_base_url:
        new_env["LLM_BASE_URL"] = new_base_url
    if new_provider:
        new_env["MODEL_NAME"] = new_model
    # If user entered a new key, write the env ref and save to .env.
    # If user left it blank but the agent previously had a key, keep the existing ref.
    # If provider doesn't need a key, omit it.
    if llm_api_key:
        new_env["LLM_API_KEY"] = f"${{{agent_id.upper()}_LLM_API_KEY}}"
    elif existing_has_api_key and needs_key:
        new_env["LLM_API_KEY"] = env["LLM_API_KEY"]

    agent_data["environment"] = new_env

    for i, a in enumerate(agents):
        if a["id"] == agent_id:
            agents[i] = agent_data
            break

    data = load_yaml(AGENTS_YAML)
    data["agents"] = agents
    save_yaml(AGENTS_YAML, data)
    logger.info(f"Updated '{agent_id}' in agents.yaml")

    channel = agent_data.get("channel", "telegram")
    if new_token:
        add_token_to_env(agent_id, new_token, channel=channel)

    if llm_api_key:
        add_llm_api_key_to_env(agent_id, llm_api_key)

    # Update docker-compose.yaml with LLM vars too
    token_env = _token_env_for_agent(agent_id, channel)
    compose = load_yaml(DOCKER_COMPOSE)
    if "services" in compose and agent_id in compose["services"]:
        svc_env = compose["services"][agent_id].setdefault("environment", {})
        svc_env["AGENT_ID"] = agent_id
        svc_env["TELEGRAM_BOT_TOKEN"] = f"${{{token_env}}}"
        svc_env["PERSONALITY_FILE"] = agent_data["personality"]
        svc_env["TIMEZONE"] = new_tz
        svc_env["TZ"] = new_tz

        # Per-agent LLM vars
        if new_provider:
            svc_env["LLM_PROVIDER"] = new_provider
        if new_base_url:
            svc_env["LLM_BASE_URL"] = new_base_url
        if new_provider:
            svc_env["MODEL_NAME"] = new_model
        if llm_api_key:
            svc_env["LLM_API_KEY"] = f"${{{agent_id.upper()}_LLM_API_KEY}}"
        elif existing_has_api_key and needs_key and "LLM_API_KEY" in svc_env:
            # Keep existing docker-compose LLM_API_KEY ref
            pass
        else:
            svc_env.pop("LLM_API_KEY", None)

        save_yaml(DOCKER_COMPOSE, compose)

    logger.info(f"\nReconfigured '{agent_id}'.")
    start = await questionary.confirm(
        "Build and restart all services now?",
        default=True,
    ).ask_async()
    if start:
        logger.info("Building and restarting all services...")
        try:
            subprocess.run(["docker", "compose", "up", "-d", "--build"], check=False)
        except FileNotFoundError:
            logger.warning("docker compose not found. Run manually: docker compose up -d --build")
    else:
        logger.info("Run when ready: docker compose up -d --build")


async def _remove_agent_flow() -> None:
    agents = load_existing_agents()
    if not agents:
        logger.warning("No agents found in agents.yaml")
        return

    choices = [a["id"] for a in agents]
    agent_id = await questionary.select("Select agent to remove:", choices=choices).ask_async()
    if agent_id is None:
        return

    confirm = await questionary.confirm(
        f"Remove agent '{agent_id}' from all config files?",
        default=False,
    ).ask_async()
    if not confirm:
        return

    try:
        subprocess.run(["docker", "compose", "stop", agent_id], check=False)
        subprocess.run(["docker", "compose", "rm", "-f", agent_id], check=False)
    except FileNotFoundError:
        pass

    remove_agent_from_configs(agent_id)
    logger.info(f"Agent '{agent_id}' removed.")


async def _start_restart_flow() -> None:
    agents = load_existing_agents()
    if not agents:
        logger.warning("No agents configured. Add one first.")
        return

    choices = ["All agents", "Select specific agent"]
    action = await questionary.select("Start or restart:", choices=choices).ask_async()
    if action is None:
        return

    if action == "All agents":
        try:
            subprocess.run(["docker", "compose", "up", "-d", "--build"], check=False)
        except FileNotFoundError:
            logger.warning("docker compose not found. Run manually: docker compose up -d --build")
    else:
        agent_choices = [a["id"] for a in agents]
        agent_id = await questionary.select("Select agent:", choices=agent_choices).ask_async()
        if agent_id is None:
            return
        try:
            subprocess.run(["docker", "compose", "up", "-d", "--build", agent_id], check=False)
        except FileNotFoundError:
            logger.warning("docker compose not found. Run manually: docker compose up -d --build")


async def _configure_search_flow() -> None:
    """Configure web search provider: Brave API or SearXNG."""
    ensure_config_files()

    env = _read_env_dict(ENV_FILE)
    current_provider = env.get("SEARCH_PROVIDER", "searxng")

    logger.info(f"\n{B}{CYAN}🔍 Search Configuration{RESET}")
    logger.info(f"{DIM}Current provider: {current_provider}{RESET}\n")

    provider = await questionary.select(
        "Select web search provider:",
        choices=[
            questionary.Choice(
                title="SearXNG (self-hosted, free, requires Docker)",
                value="searxng",
            ),
            questionary.Choice(
                title="Brave Search API (hosted, free tier ~1,000/mo)",
                value="brave",
            ),
            questionary.Choice(
                title="None (disable web search)",
                value="none",
            ),
        ],
        default=current_provider,
    ).ask_async()
    if provider is None:
        return

    env["SEARCH_PROVIDER"] = provider

    if provider == "brave":
        api_key = env.get("BRAVE_API_KEY", "")
        new_key = await questionary.text(
            "Brave Search API key (get free at https://brave.com/search/api/):",
            default=api_key,
        ).ask_async()
        if new_key is not None:
            env["BRAVE_API_KEY"] = new_key

    elif provider == "searxng":
        current_url = env.get("SEARXNG_URL", "http://searxng:8080")
        new_url = await questionary.text(
            "SearXNG URL:",
            default=current_url,
        ).ask_async()
        if new_url is not None:
            env["SEARXNG_URL"] = new_url
        current_secret = env.get("SEARXNG_SECRET", "")
        new_secret = await questionary.text(
            "SearXNG secret key (optional):",
            default=current_secret,
        ).ask_async()
        if new_secret is not None:
            env["SEARXNG_SECRET"] = new_secret

    _write_env_dict(ENV_FILE, env)
    logger.info(f"\n✅ Search provider set to: {provider}")
    logger.info(f"Values saved to {ENV_FILE}")


async def onboard() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ensure_config_files()

    logger.info(f"\n{B}{MAGENTA}🧚 Pillywiggins Onboard Wizard{RESET}")
    logger.info(f"{DIM}{'─' * 40}{RESET}\n")

    while True:
        action = await questionary.select(
            "What would you like to do?",
            choices=[
                "✨ Add agent",
                "🔧 Reconfigure agent",
                "🔍 Configure search (Brave/SearXNG)",
                "🗑️  Remove agent",
                "🚀 Start/restart agents",
                "👋 Exit",
            ],
        ).ask_async()

        if action is None or action == "👋 Exit":
            logger.info(f"\n{DIM}Goodbye!{RESET}")
            return

        if action == "✨ Add agent":
            await _add_agent_flow()
        elif action == "🔧 Reconfigure agent":
            await _reconfigure_agent_flow()
        elif action == "🔍 Configure search (Brave/SearXNG)":
            await _configure_search_flow()
        elif action == "🗑️  Remove agent":
            await _remove_agent_flow()
        elif action == "🚀 Start/restart agents":
            await _start_restart_flow()
