"""CLI wizard for blackbox test suite configuration.

Interactive wizard that configures AI judge endpoint, model selection,
Telethon credentials, and multi-agent test setup.
"""

import sys
from typing import Optional

from .config import BlackboxConfig

# Try importing questionary for prettier prompts; fall back to input()
try:
    import questionary  # noqa: F401

    _HAS_QUESTIONARY = True
except ImportError:
    _HAS_QUESTIONARY = False


def _prompt(prompt_text: str, default: str = "") -> str:
    """Prompt the user with optional default value."""
    if default:
        result = input(f"{prompt_text} [{default}]: ")
        return result.strip() if result.strip() else default
    else:
        return input(f"{prompt_text}: ").strip()


def _prompt_yesno(prompt_text: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    result = input(prompt_text + suffix).strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def poll_models(endpoint_url: str) -> list[str]:
    """Poll the AI endpoint for available models.

    Returns a list of model IDs, or an empty list if the endpoint
    is unreachable or the response format is unexpected.
    """
    import json
    import urllib.request
    import urllib.error

    # Normalize: strip trailing slash, then append /models
    base = endpoint_url.rstrip("/")
    # If the URL ends with /v1, /models goes after; otherwise check structure
    if base.endswith("/v1"):
        models_url = base + "/models"
    else:
        models_url = base + "/v1/models"

    try:
        req = urllib.request.Request(models_url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"  Warning: Could not reach model endpoint: {e}")
        return []

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        print(f"  Warning: Invalid JSON from model endpoint: {e}")
        return []

    # OpenAI-compatible: {"object": "list", "data": [{"id": "...", ...}, ...]}
    # Ollama: {"models": [{"name": "...", ...}, ...]}
    if "data" in data and isinstance(data["data"], list):
        return [m.get("id", "") for m in data["data"] if m.get("id")]
    elif "models" in data and isinstance(data["models"], list):
        return [m.get("name", "") for m in data["models"] if m.get("name")]
    else:
        # Unknown format — try to extract any model-like strings
        return []


def setup_wizard(config_path: Optional[str] = None) -> BlackboxConfig:
    """Run the interactive setup wizard.

    Args:
        config_path: Optional path to existing config to load. If None,
                     uses the default .blackbox_config.json.

    Returns:
        A configured BlackboxConfig instance. The caller is responsible
        for calling .save() to persist it.
    """
    from pathlib import Path

    print("=" * 60)
    print("  Pillywiggins Black-Box Test Suite — Setup Wizard")
    print("=" * 60)
    print()

    # 1. Load existing config if present
    if config_path:
        cfg_path = Path(config_path)
    else:
        cfg_path = BlackboxConfig.__dataclass_fields__.get("CONFIG_PATH")
        # Fallback
        from .config import CONFIG_PATH as _DEFAULT_PATH
        cfg_path = _DEFAULT_PATH

    cfg = BlackboxConfig.load(cfg_path)
    if cfg_path.exists():
        print(f"Loaded existing config from {cfg_path}")
        print()

    # 2. AI endpoint URL
    print("--- AI Judge Configuration ---")
    cfg.ai_endpoint_url = _prompt(
        "AI endpoint URL (OpenAI-compatible)",
        cfg.ai_endpoint_url,
    )

    # 3. Poll for models
    print(f"\nPolling {cfg.ai_endpoint_url}/models for available models...")
    models = poll_models(cfg.ai_endpoint_url)
    if models:
        print(f"  Found {len(models)} model(s):")
        for i, m in enumerate(models, 1):
            marker = "  (*)" if m == cfg.ai_model else "    "
            print(f"  [{i}] {marker} {m}")
        print()

        if _HAS_QUESTIONARY:
            import questionary
            choice = questionary.select(
                "Select AI judge model:",
                choices=models,
                default=cfg.ai_model if cfg.ai_model in models else models[0],
            ).ask()
            if choice:
                cfg.ai_model = choice
        else:
            choice = _prompt("Select model (number or name)", cfg.ai_model)
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(models):
                    cfg.ai_model = models[idx]
            except ValueError:
                if choice in models:
                    cfg.ai_model = choice
    else:
        print("  No models discovered. Using default model name.")
        cfg.ai_model = _prompt("AI model name", cfg.ai_model)

    print()

    # 4. Telegram test harness credentials
    print("--- Telegram Test Harness Credentials ---")
    print("(These are for the black-box test bot, not for agents under test)")
    cfg.test_telegram_token = _prompt(
        "Telegram bot token for test harness",
        cfg.test_telegram_token or "",
    )
    print()

    # 5. How many agents?
    print("--- Agents Under Test ---")
    while True:
        count_str = _prompt(
            "How many agents to configure (minimum 2)",
            str(max(len(cfg.agent_tokens), 2)),
        )
        try:
            agent_count = int(count_str)
            if agent_count >= 2:
                break
            print("  Must be at least 2 agents for cross-agent testing.")
        except ValueError:
            print("  Please enter a number.")

    print()

    # 6. Per-agent configuration
    new_tokens: dict[str, str] = {}
    new_personalities: dict[str, str] = {}

    existing_agents = list(cfg.agent_tokens.keys())
    existing_personalities = list(cfg.personality_mapping.keys())

    for i in range(agent_count):
        print(f"--- Agent {i + 1} of {agent_count} ---")

        # Pre-fill if we have existing data for this index
        default_agent_id = ""
        default_personality = ""
        default_token = ""
        if i < len(existing_agents):
            default_agent_id = existing_agents[i]
            default_token = cfg.agent_tokens.get(default_agent_id, "")
        if i < len(existing_personalities):
            pid_key = existing_personalities[i] if i < len(existing_personalities) else ""
            default_personality = cfg.personality_mapping.get(pid_key, "")

        agent_id = _prompt("  Agent ID", default_agent_id or f"agent_{i + 1}")
        if not agent_id:
            agent_id = f"agent_{i + 1}"

        personality = _prompt(
            "  Personality filename (e.g., friendly.yaml)",
            default_personality or "",
        )

        token = _prompt(
            "  Telegram bot token for this agent",
            default_token or "",
        )

        new_tokens[agent_id] = token
        new_personalities[agent_id] = personality
        print()

    cfg.agent_tokens = new_tokens
    cfg.personality_mapping = new_personalities

    # 7. Save
    cfg.save(cfg_path)
    print(f"Configuration saved to {cfg_path}")
    print()

    # 8. Summary
    print("=" * 60)
    print("  Configuration Summary")
    print("=" * 60)
    print(f"  AI Endpoint:    {cfg.ai_endpoint_url}")
    print(f"  AI Model:       {cfg.ai_model}")
    print(f"  Test TG Token:  {'***' if cfg.test_telegram_token else '(not set)'}")
    print(f"  Agents ({len(cfg.agent_tokens)}):")
    for aid, tok in cfg.agent_tokens.items():
        pers = cfg.personality_mapping.get(aid, "")
        token_display = "***" if tok else "(no token)"
        print(f"    - {aid}: personality={pers or '(none)'}, token={token_display}")
    print()

    return cfg


def main() -> None:
    """Entry point: run the setup wizard."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Pillywiggins black-box test suite setup wizard",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to config file (default: .blackbox_config.json)",
    )
    args = parser.parse_args()

    try:
        setup_wizard(config_path=args.config)
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
