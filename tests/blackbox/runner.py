"""Scenario runner that executes black-box test scenarios and formats results.

Run all scenarios against configured agents, collect results from the AI judge,
and produce a human-readable summary with pass/fail counts and per-scenario scores.

Usage:
    python -m tests.blackbox.runner          # standalone
    from tests.blackbox.runner import main   # integrated from cli
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from .config import BlackboxConfig, CONFIG_PATH
from .harness import AgentHarness
from .judge import Judge
from .scenarios import SCENARIOS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# Core runner
# ──────────────────────────────────────────────────────────────────────────


async def run_all(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
    scenarios: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run all (or selected) scenarios and collect results.

    Args:
        harness: Connected AgentHarness instance.
        agents: Dict mapping agent_id -> Telegram @username.
        judge: Configured Judge instance.
        scenarios: Optional subset of SCENARIOS to run. If None, runs all.

    Returns:
        Flat list of result dicts from every scenario that ran.
    """
    if scenarios is None:
        scenarios = SCENARIOS

    all_results: list[dict[str, Any]] = []

    for name, scenario_fn in scenarios.items():
        print(f"\n  [{name}] Running...")
        try:
            results = await scenario_fn(harness, agents, judge)
        except Exception as exc:
            logger.exception("Scenario %s raised unhandled exception", name)
            results = [
                {
                    "scenario": name,
                    "question": "",
                    "response": "",
                    "expected": "",
                    "passed": False,
                    "score": 1,
                    "reasoning": f"Scenario crashed: {exc}",
                }
            ]

        all_results.extend(results)

        # Per-scenario quick summary
        passed = sum(1 for r in results if r.get("passed"))
        total = len(results)
        print(f"  [{name}] {passed}/{total} passed")

    return all_results


# ──────────────────────────────────────────────────────────────────────────
# Formatting
# ──────────────────────────────────────────────────────────────────────────


def format_results(results: list[dict[str, Any]]) -> str:
    """Produce a pretty-printed summary of test results.

    Args:
        results: Flat list of result dicts from run_all().

    Returns:
        Multi-line formatted string suitable for printing.
    """
    if not results:
        return "No results to display."

    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    avg_score = sum(r.get("score", 0) for r in results) / total if total else 0

    lines = [
        "=" * 60,
        "  Black-Box Test Results",
        "=" * 60,
        f"  Total evaluations: {total}",
        f"  Passed:             {passed}",
        f"  Failed:             {failed}",
        f"  Average score:      {avg_score:.1f}/5.0",
        "=" * 60,
        "",
    ]

    # Group by scenario
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        name = r.get("scenario", "unknown")
        by_scenario.setdefault(name, []).append(r)

    for scenario_name in sorted(by_scenario.keys()):
        items = by_scenario[scenario_name]
        s_passed = sum(1 for r in items if r.get("passed"))
        s_total = len(items)
        s_avg = sum(r.get("score", 0) for r in items) / s_total if s_total else 0

        lines.append(f"--- {scenario_name} ({s_passed}/{s_total} passed, avg {s_avg:.1f}/5.0) ---")

        for i, item in enumerate(items):
            status = "PASS" if item.get("passed") else "FAIL"
            score = item.get("score", "?")
            question = item.get("question", "")
            response = item.get("response", "")
            reasoning = item.get("reasoning", "")

            # Truncate for display
            q_short = (question[:80] + "...") if len(question) > 80 else question
            r_short = (response[:120] + "...") if len(response) > 120 else response

            lines.append(f"  [{status}] score={score} | Q: {q_short}")
            lines.append(f"         R: {r_short}")

            # Show reasoning for failures or when verbose
            if not item.get("passed") and reasoning:
                reason_short = (reasoning[:150] + "...") if len(reasoning) > 150 else reasoning
                lines.append(f"         Reason: {reason_short}")

        lines.append("")

    # Overall verdict
    if passed == total:
        lines.append(">>> ALL SCENARIOS PASSED <<<")
    else:
        lines.append(f">>> {failed}/{total} EVALUATIONS FAILED <<<")

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────


def main(config_path: Path | str | None = None) -> None:
    """Load config, create harness + judge, run all scenarios, print results.

    Exits gracefully if the config file doesn't exist (prints a message
    and returns rather than raising).

    Args:
        config_path: Optional path to blackbox config JSON.
                     Defaults to .blackbox_config.json.
    """
    if config_path is None:
        config_path = CONFIG_PATH
    config_path = Path(config_path)

    # 1. Load config (graceful if missing)
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        print("Run the setup wizard first:")
        print("  python -m tests.blackbox.cli")
        return

    cfg = BlackboxConfig.load(config_path)

    # 2. Validate minimum configuration
    if not cfg.test_telegram_token:
        print("Test harness credentials incomplete. Run setup wizard:")
        print("  python -m tests.blackbox.cli")
        return

    if not cfg.agent_tokens:
        print("No agents configured. Run setup wizard:")
        print("  python -m tests.blackbox.cli")
        return

    # 3. Build agent map: agent_id -> @username
    #    We need usernames for harness.ask(). Derive from agent_ids by convention
    #    (agent tokens alone don't give us the @username — config needs it).
    #    For now, use agent_id as the username handle (agents configured this way
    #    are expected to be reachable via @agent_id).
    agents: dict[str, str] = {}
    for agent_id in cfg.agent_tokens:
        # Use agent_id as the Telegram @handle — the setup wizard should
        # collect the actual @username alongside the token.
        agents[agent_id] = f"@{agent_id}"

    # Allow override via personality_mapping if usernames stored there
    if cfg.personality_mapping:
        for agent_id, personality in cfg.personality_mapping.items():
            # Check if the personality string is actually a @username
            # (some configs may store usernames in personality_mapping)
            if personality.startswith("@"):
                agents[agent_id] = personality

    # 4. Create judge
    judge = Judge(
        endpoint_url=cfg.ai_endpoint_url,
        model=cfg.ai_model,
    )

    # 5. Create harness and run
    harness = AgentHarness(
        bot_token=cfg.test_telegram_token,
    )

    async def _run() -> None:
        async with harness:
            print(f"\nConnected to Telegram as test harness bot.")
            print(f"Agents under test: {list(agents.keys())}")
            print(f"Judge: {cfg.ai_model} @ {cfg.ai_endpoint_url}")
            print()

            results = await run_all(harness, agents, judge)

            print()
            print(format_results(results))

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n\nTest run cancelled.")
        sys.exit(0)


if __name__ == "__main__":
    main()
