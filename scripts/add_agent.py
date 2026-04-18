#!/usr/bin/env python3
"""Add a new Pillywiggins agent to agents.yaml, docker-compose.yaml, and env.example."""

import argparse
import os
import re
import yaml


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def add_agent_to_config(agent_id, personality, channel, allowed_user_ids, token_env, config_path="agents.yaml"):
    config = load_yaml(config_path)
    if "agents" not in config:
        config["agents"] = []

    for entry in config["agents"]:
        if entry["id"] == agent_id:
            print(f"Agent '{agent_id}' already exists in {config_path}")
            return False

    config["agents"].append({
        "id": agent_id,
        "personality": personality,
        "channel": channel,
        "allowed_user_ids": allowed_user_ids,
        "environment": {
            "TELEGRAM_BOT_TOKEN": f"${{{token_env}}}"
        },
    })
    save_yaml(config_path, config)
    print(f"Added '{agent_id}' to {config_path}")
    return True


def add_agent_to_compose(agent_id, personality_path, token_env, compose_path="docker-compose.yaml"):
    compose = load_yaml(compose_path)
    if "services" not in compose:
        compose["services"] = {}

    if agent_id in compose["services"]:
        print(f"Service '{agent_id}' already exists in {compose_path}")
        return False

    compose["services"][agent_id] = {
        "build": ".",
        "command": f"python -m pillywiggins --agent-id {agent_id}",
        "env_file": ".env",
        "environment": {
            "AGENT_ID": agent_id,
            "TELEGRAM_BOT_TOKEN": f"${{{token_env}}}",
            "PERSONALITY_FILE": personality_path,
        },
        "volumes": [
            "./personalities:/config:ro",
            "./agents.yaml:/app/agents.yaml:ro",
            "skills:/app/skills",
        ],
        "depends_on": {
            "postgres": {"condition": "service_healthy"},
            "redis": {"condition": "service_started"},
            "nats": {"condition": "service_started"},
            "searxng": {"condition": "service_healthy"},
        },
    }
    save_yaml(compose_path, compose)
    print(f"Added '{agent_id}' service to {compose_path}")
    return True


def add_token_to_env_file(token_env, agent_id, env_path=".env"):
    token_line = f"{token_env}=your_{agent_id}_telegram_bot_token_here"

    if not os.path.exists(env_path):
        print(f"No {env_path} found. Create it from env.example first: cp env.example .env")
        return False

    with open(env_path) as f:
        content = f.read()

    if token_env in content:
        print(f"{token_env} already in {env_path}")
        return False

    lines = content.split("\n")
    new_lines = []
    inserted = False

    for i, line in enumerate(lines):
        new_lines.append(line)
        if not inserted and line.strip().startswith("#") and "Telegram Bot Token" in line:
            new_lines.append(token_line)
            inserted = True

    if not inserted:
        for i, line in enumerate(lines):
            new_lines.append(line)
            if not inserted and re.match(r"^[A-Z_]+_TELEGRAM_TOKEN=", line):
                new_lines.append(token_line)
                inserted = True

    if not inserted:
        new_lines.append("")
        new_lines.append("# --- Telegram Bot Tokens ---")
        new_lines.append(token_line)

    with open(env_path, "w") as f:
        f.write("\n".join(new_lines))
    print(f"Added {token_env} to {env_path}")
    return True


def add_token_to_env_example(token_env, agent_id, env_path="env.example"):
    token_line = f"{token_env}=your_{agent_id}_telegram_bot_token_here"

    with open(env_path) as f:
        content = f.read()

    if token_env in content:
        print(f"{token_env} already in {env_path}")
        return False

    lines = content.split("\n")
    new_lines = []
    inserted = False

    for line in lines:
        if not inserted and re.match(r"^[A-Z_]+_TELEGRAM_TOKEN=", line):
            new_lines.append(line)
        elif not inserted and line.strip() == "# Add more agents with: python scripts/add_agent.py <agent_id>":
            new_lines.append(f"# {token_line}")
            new_lines.append(line)
            inserted = True
        else:
            new_lines.append(line)

    with open(env_path, "w") as f:
        f.write("\n".join(new_lines))
    print(f"Added {token_env} to {env_path}")
    return True


parser = argparse.ArgumentParser(description="Add a new Pillywiggins agent")
parser.add_argument("agent_id", help="Unique agent ID (e.g. mustardseed, bramblethorn)")
parser.add_argument("--personality", default=None, help="Personality YAML path (default: /config/{agent_id}.yaml)")
parser.add_argument("--channel", default="telegram", help="Channel adapter (default: telegram)")
parser.add_argument("--allowed-user-ids", default="all", help="Comma-separated user IDs or 'all' (default: all)")
parser.add_argument("--token-env", default=None, help="Env var name for bot token (default: {AGENT_ID.upper()}_TELEGRAM_TOKEN)")
parser.add_argument("--bot-chat-limit", type=int, default=3, help="Max consecutive bot-to-bot replies (default: 3, 0=never, -1=unlimited)")

args = parser.parse_args()

agent_id = args.agent_id
personality = args.personality or f"/config/{agent_id}.yaml"
channel = args.channel
allowed_user_ids = args.allowed_user_ids
token_env = args.token_env or f"{agent_id.upper()}_TELEGRAM_TOKEN"

print(f"Adding agent: {agent_id}")
print(f"  Personality: {personality}")
print(f"  Channel: {channel}")
print(f"  Allowed users: {allowed_user_ids}")
print(f"  Token env var: {token_env}")
print(f"  Bot chat limit: {args.bot_chat_limit}")
print()

add_agent_to_config(agent_id, personality, channel, allowed_user_ids, token_env)
add_agent_to_compose(agent_id, personality, token_env)
add_token_to_env_example(token_env, agent_id)
add_token_to_env_file(token_env, agent_id)

yaml_path = f"personalities/{agent_id}.yaml"
if not os.path.exists(yaml_path):
    display_name = agent_id.capitalize()
    personality_content = f"""name: {display_name}
channel: telegram
description: "A Pillywiggins agent named {display_name}."
system_prompt: |
  You are {display_name}, a helpful and engaging AI assistant with your own unique personality. Be friendly, concise, and helpful in your interactions. You have access to tools for memory, web search, and skill building — use them when appropriate.
traits:
  - helpful
  - friendly
  - concise
scheduling: {{}}
schedules:
  - name: heartbeat
    action: heartbeat
    interval_seconds: 1800
  - name: memory_review
    action: memory_review
    interval_seconds: 3600
  - name: skill_reload
    action: skill_reload
    cron_expr: "0 */6 * * *"
bot_chat_limit: {args.bot_chat_limit}
"""
    with open(yaml_path, "w") as f:
        f.write(personality_content)
    print(f"Created personality file: {yaml_path}")
    print(f"Edit it to customize {display_name}'s personality, traits, and system prompt.")
else:
    print(f"Personality file exists: {yaml_path}")

print(f"""
Next steps:
1. Create a Telegram bot via @BotFather and get the token
2. Add the token to .env: {token_env}=your_actual_token_here
3. Customize the personality: edit {yaml_path}
4. Start: docker compose up -d {agent_id}
""")