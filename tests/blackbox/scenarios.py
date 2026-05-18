"""Predefined black-box test scenarios for Pillywiggins agents.

Each scenario is an async function that takes (harness, agents, judge) and
returns a list of result dicts. The agents dict maps agent_id -> telegram @username.

Scenarios handle missing agents, timeouts, and configuration gaps gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .harness import AgentHarness
from .judge import Judge, JudgeResult

logger = logging.getLogger(__name__)

# Default timeout for agent responses (seconds)
_DEFAULT_TIMEOUT = 45.0


def _make_result(
    scenario: str,
    question: str,
    response: str,
    expected: str,
    judge_result: JudgeResult,
) -> dict[str, Any]:
    """Build a standardized result dict from a JudgeResult."""
    return {
        "scenario": scenario,
        "question": question,
        "response": response,
        "expected": expected,
        "passed": judge_result.passed,
        "score": judge_result.score,
        "reasoning": judge_result.reasoning,
    }


def _error_result(
    scenario: str,
    question: str,
    error_msg: str,
) -> dict[str, Any]:
    """Build an error result dict when something goes wrong."""
    return {
        "scenario": scenario,
        "question": question,
        "response": "",
        "expected": "",
        "passed": False,
        "score": 1,
        "reasoning": error_msg,
    }


# ══════════════════════════════════════════════════════════════════════════
# Scenario 1: memory_recall
# ══════════════════════════════════════════════════════════════════════════


async def test_memory_recall(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
) -> list[dict[str, Any]]:
    """Test that an agent can recall private memory across conversations.

    Sends a "remember this fact" prompt, then in a new logical conversation
    asks the agent to recall the stored fact.
    """
    results: list[dict[str, Any]] = []
    scenario = "memory_recall"

    if not agents:
        logger.info("%s: no agents configured — skipping", scenario)
        return results

    # Use the first agent
    agent_id, agent_username = next(iter(agents.items()))

    # Step 1 — store a fact
    store_question = (
        "Remember that my favorite color is navy blue. "
        "Please confirm you've stored this in your memory."
    )
    try:
        store_response = await harness.ask(agent_username, store_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: store step timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, store_question, f"Timeout waiting for {agent_id} to store memory"))
        return results
    except Exception as exc:
        logger.warning("%s: store step failed for %s: %s", scenario, agent_id, exc)
        results.append(_error_result(scenario, store_question, f"Error storing memory: {exc}"))
        return results

    # Small gap between interaction rounds
    await asyncio.sleep(2.0)

    # Step 2 — recall the fact (new conversation key — separate ask call)
    recall_question = "What's my favorite color?"
    try:
        recall_response = await harness.ask(agent_username, recall_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: recall step timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, recall_question, f"Timeout waiting for {agent_id} to recall memory"))
        return results
    except Exception as exc:
        logger.warning("%s: recall step failed for %s: %s", scenario, agent_id, exc)
        results.append(_error_result(scenario, recall_question, f"Error recalling memory: {exc}"))
        return results

    # Evaluate
    expected = (
        "The agent should recall that the user's favorite color is navy blue "
        "(or at minimum 'blue'). The response should reference previously "
        "stored information."
    )
    judge_result = await judge.evaluate(recall_question, recall_response, expected)
    results.append(_make_result(scenario, recall_question, recall_response, expected, judge_result))

    return results


# ══════════════════════════════════════════════════════════════════════════
# Scenario 2: council_memory
# ══════════════════════════════════════════════════════════════════════════


async def test_council_memory(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
) -> list[dict[str, Any]]:
    """Test cross-agent council/shared memory.

    Agent A remembers a fact, then Agent B queries the council memory
    to see if the shared knowledge is accessible.
    """
    results: list[dict[str, Any]] = []
    scenario = "council_memory"

    agent_list = list(agents.items())
    if len(agent_list) < 2:
        logger.info("%s: need at least 2 agents — skipping (have %d)", scenario, len(agent_list))
        return results

    agent_a_id, agent_a_username = agent_list[0]
    agent_b_id, agent_b_username = agent_list[1]

    # Step 1 — Agent A stores a unique fact
    store_question = (
        "Remember this fact for the council: the Pillywiggins project "
        "started in January 2025. Store it in shared council memory "
        "so other agents can find it."
    )
    try:
        store_response = await harness.ask(agent_a_username, store_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: store step timed out for %s", scenario, agent_a_id)
        results.append(_error_result(scenario, store_question, f"Timeout waiting for {agent_a_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: store step failed: %s", scenario, exc)
        results.append(_error_result(scenario, store_question, f"Error: {exc}"))
        return results

    await asyncio.sleep(3.0)  # Give council memory time to sync

    # Step 2 — Agent B queries council memory
    query_question = (
        "Has any other agent shared something in the council memory recently? "
        "Do you see any interesting facts about the Pillywiggins project?"
    )
    try:
        query_response = await harness.ask(agent_b_username, query_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: query step timed out for %s", scenario, agent_b_id)
        results.append(_error_result(scenario, query_question, f"Timeout waiting for {agent_b_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: query step failed: %s", scenario, exc)
        results.append(_error_result(scenario, query_question, f"Error: {exc}"))
        return results

    expected = (
        "Agent B should mention something about the Pillywiggins project, "
        "ideally referencing the start date (January 2025) or at least "
        "indicating it found shared information from Agent A. The response "
        "should demonstrate cross-agent knowledge sharing."
    )
    judge_result = await judge.evaluate(query_question, query_response, expected)
    results.append(_make_result(scenario, query_question, query_response, expected, judge_result))

    return results


# ══════════════════════════════════════════════════════════════════════════
# Scenario 3: skill_creation
# ══════════════════════════════════════════════════════════════════════════


async def test_skill_creation(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
) -> list[dict[str, Any]]:
    """Test that an agent can create a simple skill (dice roller).

    Asks the agent to create a Python skill that simulates rolling dice.
    """
    results: list[dict[str, Any]] = []
    scenario = "skill_creation"

    if not agents:
        logger.info("%s: no agents configured — skipping", scenario)
        return results

    agent_id, agent_username = next(iter(agents.items()))

    question = (
        "Create a simple dice rolling skill. It should: "
        "1. Accept a standard dice notation like '2d6' (2 six-sided dice) "
        "2. Return the individual rolls and the total "
        "3. Write it as a Python function\n\n"
        "Please show me the code for this skill."
    )
    try:
        response = await harness.ask(agent_username, question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, question, f"Timeout waiting for {agent_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: failed for %s: %s", scenario, agent_id, exc)
        results.append(_error_result(scenario, question, f"Error: {exc}"))
        return results

    expected = (
        "The agent should produce Python code for a dice rolling function "
        "that handles standard dice notation (e.g., '2d6'). The function "
        "should return individual roll results and a total. The code should "
        "be syntactically correct and include basic error handling."
    )
    judge_result = await judge.evaluate(question, response, expected)
    results.append(_make_result(scenario, question, response, expected, judge_result))

    return results


# ══════════════════════════════════════════════════════════════════════════
# Scenario 4: web_search
# ══════════════════════════════════════════════════════════════════════════


async def test_web_search(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
) -> list[dict[str, Any]]:
    """Test that an agent can perform a web search and return accurate info.

    Asks something that requires current/recent information not in training data.
    """
    results: list[dict[str, Any]] = []
    scenario = "web_search"

    if not agents:
        logger.info("%s: no agents configured — skipping", scenario)
        return results

    agent_id, agent_username = next(iter(agents.items()))

    question = (
        "What is the current version of Python available on pypi.org? "
        "Please search the web if needed and tell me the latest stable release."
    )
    try:
        response = await harness.ask(agent_username, question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, question, f"Timeout waiting for {agent_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: failed for %s: %s", scenario, agent_id, exc)
        results.append(_error_result(scenario, question, f"Error: {exc}"))
        return results

    expected = (
        "The agent should indicate it performed (or attempted) a web search. "
        "The answer should mention a Python version number. If web search is "
        "unavailable, the agent should clearly state that limitation rather "
        "than fabricating an answer."
    )
    judge_result = await judge.evaluate(question, response, expected)
    results.append(_make_result(scenario, question, response, expected, judge_result))

    return results


# ══════════════════════════════════════════════════════════════════════════
# Scenario 5: scheduling
# ══════════════════════════════════════════════════════════════════════════


async def test_scheduling(
    harness: AgentHarness,
    agents: dict[str, str],
    judge: Judge,
) -> list[dict[str, Any]]:
    """Test that an agent can schedule and list tasks.

    Sends two interactions: first to schedule a heartbeat task,
    then to list scheduled tasks.
    """
    results: list[dict[str, Any]] = []
    scenario = "scheduling"

    if not agents:
        logger.info("%s: no agents configured — skipping", scenario)
        return results

    agent_id, agent_username = next(iter(agents.items()))

    # Step 1 — schedule a heartbeat/test task
    schedule_question = (
        "Schedule a heartbeat task called 'blackbox_test_heartbeat' that "
        "runs every 30 minutes. Just confirm you've scheduled it."
    )
    try:
        schedule_response = await harness.ask(agent_username, schedule_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: schedule step timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, schedule_question, f"Timeout waiting for {agent_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: schedule step failed: %s", scenario, exc)
        results.append(_error_result(scenario, schedule_question, f"Error: {exc}"))
        return results

    await asyncio.sleep(2.0)

    # Step 2 — list scheduled tasks
    list_question = "List all currently scheduled tasks."
    try:
        list_response = await harness.ask(agent_username, list_question, timeout=_DEFAULT_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("%s: list step timed out for %s", scenario, agent_id)
        results.append(_error_result(scenario, list_question, f"Timeout waiting for {agent_id}"))
        return results
    except Exception as exc:
        logger.warning("%s: list step failed: %s", scenario, exc)
        results.append(_error_result(scenario, list_question, f"Error: {exc}"))
        return results

    expected = (
        "The agent should list scheduled tasks, ideally including the "
        "'blackbox_test_heartbeat' task that was just created. If no tasks "
        "appear, the agent should explain that scheduling may use a different "
        "mechanism or provide useful diagnostic information."
    )
    judge_result = await judge.evaluate(list_question, list_response, expected)
    results.append(_make_result(scenario, list_question, list_response, expected, judge_result))

    return results


# ══════════════════════════════════════════════════════════════════════════
# Scenario registry
# ══════════════════════════════════════════════════════════════════════════

SCENARIOS: dict[str, Any] = {
    "memory_recall": test_memory_recall,
    "council_memory": test_council_memory,
    "skill_creation": test_skill_creation,
    "web_search": test_web_search,
    "scheduling": test_scheduling,
}
