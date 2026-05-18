"""AI evaluation module that grades agent responses.

Provides a Judge class that calls an OpenAI-compatible /v1/chat/completions endpoint
to evaluate agent responses against expected behaviors. Includes batch evaluation
with concurrency limiting.
"""

import asyncio
import json
import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Data Model
# ──────────────────────────────────────────────


@dataclass
class JudgeResult:
    """Result from an AI judge evaluation.

    Attributes:
        passed: Whether the agent response met the expected behavior.
        score: Numeric score from 1 (worst) to 5 (best).
        reasoning: Human-readable explanation of the grade.
    """

    passed: bool
    score: int
    reasoning: str


# ──────────────────────────────────────────────
# Prompt Template
# ──────────────────────────────────────────────

_JUDGE_SYSTEM_PROMPT = """You are an impartial AI judge evaluating an agent's response to a user question.

Your job is to grade the agent response across four dimensions:

1. **Task Understanding** — Did the agent correctly understand what was being asked?
2. **Tool Usage** — Did the agent use the right tools/functions effectively?
3. **Completeness** — Did the answer cover all parts of the question?
4. **Correctness** — Is the factual content accurate and free of errors?

Respond ONLY with a valid JSON object — no preamble, no markdown fences, no commentary:

{
  "passed": true,
  "score": 4,
  "understanding": "The agent understood the core request but missed the nuance about ...",
  "tool_usage": "Appropriate use of search and file-read tools.",
  "completeness": "Covered all major points but omitted edge case ...",
  "correctness": "All stated facts are accurate.",
  "overall": "Good response overall but incomplete on ..."
}

Score scale:
- 1: Completely wrong or unhelpful
- 2: Major errors or missing critical parts
- 3: Adequate but with noticeable gaps
- 4: Good response with minor issues
- 5: Excellent, thorough, and fully correct

"passed" must be true when score >= 3, false otherwise."""


def _build_user_message(
    question: str, agent_response: str, expected_behavior: str
) -> str:
    """Build the user message for the judge evaluation request."""
    return (
        f"--- QUESTION ---\n{question}\n\n"
        f"--- AGENT RESPONSE ---\n{agent_response}\n\n"
        f"--- EXPECTED BEHAVIOR ---\n{expected_behavior}\n\n"
        "Evaluate the agent response against the expected behavior. "
        "Return ONLY a JSON object."
    )


# ──────────────────────────────────────────────
# Response Parsing
# ──────────────────────────────────────────────


def _parse_judge_response(raw_text: str) -> JudgeResult | None:
    """Attempt to parse a JSON judge result from raw model output.

    Handles common formatting issues: markdown code fences, leading/trailing
    whitespace, and stray characters after the JSON object.

    Returns None if parsing fails.
    """
    text = raw_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence line
        newline_idx = text.find("\n")
        if newline_idx != -1:
            text = text[newline_idx + 1 :]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Find the outermost JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
        return None

    json_candidate = text[brace_start : brace_end + 1]

    try:
        data = json.loads(json_candidate)
    except json.JSONDecodeError:
        return None

    # Extract fields with defaults
    passed = bool(data.get("passed", False))
    score = int(data.get("score", 1))
    score = max(1, min(5, score))  # Clamp to 1–5
    reasoning = data.get("overall", data.get("reasoning", ""))

    # Build detailed reasoning from sub-scores if available
    parts = []
    for key, label in [
        ("understanding", "Task Understanding"),
        ("tool_usage", "Tool Usage"),
        ("completeness", "Completeness"),
        ("correctness", "Correctness"),
    ]:
        val = data.get(key, "")
        if val:
            parts.append(f"{label}: {val}")
    if reasoning:
        parts.insert(0, reasoning)

    return JudgeResult(
        passed=passed,
        score=score,
        reasoning="\n\n".join(parts) if parts else "No reasoning provided.",
    )


def _heuristic_result() -> JudgeResult:
    """Return a fallback JudgeResult when parsing fails.

    This is a conservative heuristic — we assume failure so the test framework
    can flag it for human review rather than silently passing a broken evaluation.
    """
    return JudgeResult(
        passed=False,
        score=1,
        reasoning="[HEURISTIC FALLBACK] Could not parse judge response. "
        "Manual review required.",
    )


# ──────────────────────────────────────────────
# Judge Class
# ──────────────────────────────────────────────


class Judge:
    """AI-powered evaluator that grades agent responses.

    Calls an OpenAI-compatible /v1/chat/completions endpoint with a structured
    evaluation prompt and parses the JSON response.

    Args:
        endpoint_url: Base URL of the OpenAI-compatible API (e.g. http://localhost:11434/v1).
        model: Model identifier to use for evaluation.
        timeout: Request timeout in seconds. Defaults to 60.
    """

    def __init__(
        self,
        endpoint_url: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self.endpoint_url = endpoint_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    async def evaluate(
        self,
        question: str,
        agent_response: str,
        expected_behavior: str,
    ) -> JudgeResult:
        """Evaluate an agent response against expected behavior.

        Args:
            question: The original question the agent was asked.
            agent_response: The agent's full response text.
            expected_behavior: Description of what a correct response should contain.

        Returns:
            A JudgeResult with pass/fail, score, and reasoning.
            Falls back to a heuristic result if the model response cannot be parsed.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _build_user_message(
                        question, agent_response, expected_behavior
                    ),
                },
            ],
            "temperature": 0.0,
        }

        # Build URL: endpoint_url is already base, append /chat/completions
        url = f"{self.endpoint_url}/chat/completions"

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    # Handle non-200 responses gracefully
                    if resp.status != 200:
                        body_text = await resp.text()
                        logger.warning(
                            "Judge endpoint returned %d: %s",
                            resp.status,
                            body_text[:500],
                        )
                        return JudgeResult(
                            passed=False,
                            score=1,
                            reasoning=(
                                f"Judge API returned HTTP {resp.status}. "
                                "Evaluation could not be completed."
                            ),
                        )

                    data = await resp.json()

        except aiohttp.ClientError as exc:
            logger.warning("Judge request failed: %s", exc)
            return JudgeResult(
                passed=False,
                score=1,
                reasoning=(
                    f"Judge API request failed: {exc}. "
                    "Evaluation could not be completed."
                ),
            )
        except asyncio.TimeoutError:
            logger.warning("Judge request timed out after %.0fs", self.timeout)
            return JudgeResult(
                passed=False,
                score=1,
                reasoning=(
                    f"Judge API request timed out after {self.timeout}s. "
                    "Evaluation could not be completed."
                ),
            )

        # Extract the assistant's text response
        choices = data.get("choices", [])
        if not choices:
            logger.warning("Judge response contained no choices")
            return _heuristic_result()

        raw_text = choices[0].get("message", {}).get("content", "")

        # Try structured parse, fall back to heuristic
        result = _parse_judge_response(raw_text)
        if result is None:
            logger.warning("Failed to parse judge response: %s", raw_text[:300])
            return _heuristic_result()

        return result


# ──────────────────────────────────────────────
# Batch Evaluation
# ──────────────────────────────────────────────


@dataclass
class EvalItem:
    """A single item for batch evaluation.

    Attributes:
        id: Unique identifier for this evaluation item (e.g., conversation round).
        question: The original question asked to the agent.
        agent_response: The agent's response text.
        expected_behavior: The expected behavior description.
    """

    id: str
    question: str
    agent_response: str
    expected_behavior: str


@dataclass
class BatchEvalResult:
    """Result of a single batch evaluation item.

    Attributes:
        id: The id from the input EvalItem.
        judge_result: The JudgeResult from the AI judge.
    """

    id: str
    judge_result: JudgeResult


async def batch_evaluate(
    judge: Judge,
    items: list[EvalItem],
    max_concurrency: int = 4,
) -> list[BatchEvalResult]:
    """Evaluate multiple agent responses concurrently.

    Uses an asyncio.Semaphore to limit concurrent API calls, preventing
    rate-limiting or overload of the judge endpoint.

    Args:
        judge: Configured Judge instance.
        items: List of evaluation items.
        max_concurrency: Maximum number of concurrent evaluations. Defaults to 4.

    Returns:
        List of BatchEvalResult, one per input item, in the same order.
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _evaluate_one(item: EvalItem) -> BatchEvalResult:
        async with semaphore:
            result = await judge.evaluate(
                question=item.question,
                agent_response=item.agent_response,
                expected_behavior=item.expected_behavior,
            )
        return BatchEvalResult(id=item.id, judge_result=result)

    tasks = [_evaluate_one(item) for item in items]
    return await asyncio.gather(*tasks)
