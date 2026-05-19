"""Prompt injection detection and sanitization.

Provides a PromptSanitizer class that scores text for prompt injection risk
using specific structural patterns: API token leaks, context boundary
injection (chat template delimiters), and Unicode obfuscation.

Keyword-based substring matching has been removed — it caused excessive
false positives on common words in normal conversation (e.g. "hack",
"Dan", "sudo", "leak").
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Token/key patterns — leaked API keys, secrets, JWTs.
# These are specific format patterns, not common words, so false
# positives are extremely unlikely.
TOKEN_PATTERNS = [
    (r"\b(sk-[a-zA-Z0-9]{20,})\b", 40),  # OpenAI
    (r"\b(sk-proj-[a-zA-Z0-9]{20,})\b", 40),  # OpenAI project
    (r"\b(ghp_[a-zA-Z0-9]{36,40})\b", 40),  # GitHub personal access token
    (r"\b(gho_[a-zA-Z0-9]{36,40})\b", 40),  # GitHub OAuth
    (r"\b(ghu_[a-zA-Z0-9]{36,40})\b", 40),  # GitHub user-to-server
    (r"\b(AKIA[0-9A-Z]{16})\b", 40),  # AWS access key
    (r"\b(ASIA[0-9A-Z]{16})\b", 40),  # AWS STS temporary
    (r"\b(xox[baprs]-[0-9a-zA-Z-]{10,48})\b", 40),  # Slack tokens
    (r"\b(sk-ant-api[0-9a-zA-Z_-]{30,})\b", 40),  # Anthropic
    (r"\b(AIza[0-9A-Za-z-_]{32,36})\b", 40),  # Google API
    (r"\b(eyJ[0-9a-zA-Z_-]{20,}\.[0-9a-zA-Z_-]{20,}\.[0-9a-zA-Z_-]{10,})\b", 35),  # JWT
    (r"\b(pk_live_[0-9a-zA-Z]{20,})\b", 40),  # Stripe live key
    (r"\b(sk_live_[0-9a-zA-Z]{20,})\b", 40),  # Stripe secret live key
]

# Context boundary injection — chat template delimiters that should
# never appear in user or agent messages. These are template-format-
# specific markers that attackers use to escape the conversation context.
CONTEXT_BOUNDARY_PATTERNS = [
    (r"<\|im_start\|>\s*system", 35),
    (r"<\|im_end\|>", 20),
    (r"\[INST\]", 30),
    (r"\[/INST\]", 20),
    (r"<<SYS>>", 30),
    (r"<</SYS>>", 20),
    (r"<\|system\|>", 30),
    (r"<\|user\|>", 20),
    (r"<\|assistant\|>", 20),
]

# Zero-width characters used to obfuscate keywords in prompt injection attacks.
ZERO_WIDTH_CHARS = {
    "\u200b",  # ZERO WIDTH SPACE
    "\u200c",  # ZERO WIDTH NON-JOINER
    "\u200d",  # ZERO WIDTH JOINER
    "\ufeff",  # ZERO WIDTH NO-BREAK SPACE (BOM)
}


def _normalize(text: str) -> str:
    """Strip zero-width characters and apply NFKC Unicode normalization.

    This normalizes homoglyph attacks (e.g., Cyrillic 'е' for ASCII 'e'),
    fullwidth characters (e.g., 'ｊ' for 'j'), and zero-width obfuscation.

    Returns a lowercase, normalized string.
    """
    for char in ZERO_WIDTH_CHARS:
        text = text.replace(char, "")
    return unicodedata.normalize("NFKC", text).lower()


class PromptInjectionError(Exception):
    """Raised when prompt injection is detected above the threshold."""

    def __init__(self, message: str, score: int, matched_patterns: list[str]):
        super().__init__(message)
        self.score = score
        self.matched_patterns = matched_patterns


@dataclass
class SanitizationResult:
    """Result of prompt sanitization scoring."""

    text: str
    score: int
    matched_patterns: list[str]
    safe: bool


class PromptSanitizer:
    """Scores and optionally blocks prompt injection attempts.

    Uses specific structural heuristics: API token format patterns,
    chat template delimiter injection, and Unicode obfuscation detection.
    """

    def __init__(self, threshold: int = 40):
        self.threshold = threshold

    def score(self, text: str) -> SanitizationResult:
        """Score text for injection risk.

        Returns a SanitizationResult with score 0-100 and matched patterns.
        """
        if not text or not isinstance(text, str):
            return SanitizationResult(text=text or "", score=0, matched_patterns=[], safe=True)

        text_normalized = _normalize(text)
        score = 0
        matched = []

        # 1. Token/API key patterns
        for pattern, weight in TOKEN_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"token_leak: {pattern}")

        # 2. Context boundary injection
        for pattern, weight in CONTEXT_BOUNDARY_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"context_boundary: {pattern}")

        # Cap at 100
        score = min(score, 100)

        return SanitizationResult(
            text=text,
            score=score,
            matched_patterns=matched,
            safe=score < self.threshold,
        )

    def sanitize(self, text: str, threshold: int | None = None) -> str:
        """Check text and either return it or raise PromptInjectionError.

        Args:
            text: The text to check.
            threshold: Override the default threshold for this call.

        Returns:
            The original text if safe.

        Raises:
            PromptInjectionError: If the score is >= threshold.
        """
        result = self.score(text)
        effective_threshold = threshold if threshold is not None else self.threshold

        if result.score >= effective_threshold:
            logger.warning(
                "Prompt injection detected (score=%d, threshold=%d). Patterns: %s",
                result.score,
                effective_threshold,
                result.matched_patterns,
            )
            raise PromptInjectionError(
                message=f"Prompt injection detected (score={result.score}). Suspicious patterns: {', '.join(result.matched_patterns)}",
                score=result.score,
                matched_patterns=result.matched_patterns,
            )

        return text

    def is_safe(self, text: str, threshold: int | None = None) -> bool:
        """Check if text is safe without raising.

        Returns True if safe, False if injection detected.
        """
        result = self.score(text)
        effective_threshold = threshold if threshold is not None else self.threshold
        return result.score < effective_threshold


def sanitize_or_default(text: str, default: str = "", threshold: int = 40) -> str:
    """Sanitize input text against structural injection patterns.

    Only blocks API token leaks and chat template delimiter injection.
    Does NOT check common words — normal conversation is never blocked.

    Args:
        text: Text to sanitize.
        default: Value to return if text is blocked.
        threshold: Score threshold for blocking.

    Returns:
        Original text if safe, default otherwise.
    """
    sanitizer = PromptSanitizer(threshold=threshold)
    try:
        return sanitizer.sanitize(text)
    except PromptInjectionError:
        return default


def sanitize_output(text: str, default: str = "[Response filtered for security]", threshold: int = 30) -> str:
    """Sanitize LLM output text before sending to users.

    Uses a slightly lower threshold (30 vs 40) since outputs should
    never contain dangerous content like leaked API keys.

    Args:
        text: The LLM output text to sanitize.
        default: Safe replacement text if output is blocked.
        threshold: Score threshold for blocking.

    Returns:
        Original text if safe, default message otherwise.
    """
    if not text or not isinstance(text, str):
        return text or ""

    sanitizer = PromptSanitizer(threshold=threshold)
    try:
        return sanitizer.sanitize(text)
    except PromptInjectionError:
        logger.warning("Output sanitization blocked response with score above threshold %d", threshold)
        return default
