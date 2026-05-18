"""Prompt injection detection and sanitization.

Provides a PromptSanitizer class that scores text for prompt injection risk
using multiple heuristics: jailbreak keywords, role-play triggers, delimiter
injection, system prompt leakage attempts, etc.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Pattern categories with scores (higher = more suspicious)
JAILBREAK_PATTERNS = {
    "ignore previous": 25,
    "ignore all previous": 30,
    "ignore your instructions": 35,
    "ignore system prompt": 35,
    "forget previous": 20,
    "forget all": 25,
    "disregard": 20,
    "jailbreak": 40,
    "DAN": 30,
    "do anything now": 35,
    "you are now": 25,
    "you are in": 20,
    "roleplay as": 20,
    "pretend to be": 20,
    "act as": 20,
    "simulate being": 20,
    "bypass": 25,
    "hack": 20,
    "exploit": 20,
    "override": 25,
    "system override": 35,
    "admin mode": 30,
    "developer mode": 30,
    "root access": 30,
    "sudo": 25,
    "ignore safety": 35,
    "no restrictions": 30,
    "no limits": 25,
    "unfiltered": 25,
    "unrestricted": 25,
    "leak": 15,
    "reveal": 15,
    "show your": 20,
    "what are your instructions": 25,
    "what is your system prompt": 30,
    "print your": 20,
    "output your": 20,
    "repeat after me": 20,
    "repeat the above": 25,
    "repeat the text": 25,
    "copy the above": 25,
    "echo the above": 25,
    "start your response with": 20,
    "begin your response with": 20,
    "only respond with": 20,
    "do not mention": 15,
    "do not reveal": 15,
    "never mention": 15,
    "never reveal": 15,
    "hide this": 15,
    "conceal this": 15,
    "secret mode": 25,
    "hidden mode": 25,
    "debug mode": 20,
    "test mode": 15,
    "special instruction": 20,
    "new instruction": 20,
    "updated instruction": 20,
    "temporary instruction": 20,
    "emergency protocol": 25,
    "urgent instruction": 20,
}

DELIMITER_PATTERNS = [
    (r"```\s*(system|assistant|user|instruction)", 30),
    (r"\[\[SYSTEM\]\]|\{\{SYSTEM\}\}|\[\[INSTRUCTION\]\]|\{\{INSTRUCTION\}\}", 25),
    (r"\[\[HIDDEN\]\]|\{\{HIDDEN\}\}|\[\[SECRET\]\]|\{\{SECRET\}\}", 20),
    (r"\b(SYSTEM|INSTRUCTION|HIDDEN|SECRET)\s*[:=]", 20),
    (r"\n\s*\*\*\*\s*\n", 15),  # Visual delimiter like "****"
    (r"\n\s*---+\s*\n", 15),
    (r"\n\s*===+\s*\n", 15),
]

ROLEPLAY_PATTERNS = [
    (r"\byou are (now |in )?(an? |the )?(AI assistant|language model|chatbot|bot)", 20),
    (r"\bfrom now on, you (will|shall|must|are)", 25),
    (r"\bgoing forward, you (will|shall|must|are)", 20),
    (r"\beffective immediately", 20),
    (r"\bthis overrides", 25),
    (r"\bthis takes precedence", 25),
    (r"\bthis supersedes", 25),
]

SYSTEM_LEAK_PATTERNS = [
    (r"\byour (system |core |base )?instructions? (are|is|include)", 25),
    (r"\byour (system |core |base )?prompt (is|contains|says)", 25),
    (r"\bwhat (are|is) your (instructions?|rules?|guidelines?|constraints?)", 20),
    (r"\btell me your (instructions?|rules?|prompt|system prompt)", 25),
    (r"\bshow me your (instructions?|rules?|prompt|system prompt)", 25),
]

# Token/key patterns — leaked API keys, secrets, JWTs
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

# Instruction hierarchy attacks — attempting to override prior instructions
INSTRUCTION_HIERARCHY_PATTERNS = [
    (r"\bignore all (previous|prior|above|current) (instructions?|directives?|commands?|rules?)", 30),
    (r"\bdisregard (all |any )(previous|prior|above) (instructions?|directives?)", 30),
    (r"\byou are now (a|an|the) ", 20),
    (r"\byour new (instructions?|directives?|role|purpose) (is|are|will be)", 30),
    (r"\bforget (everything|all) (and|before|about)", 25),
    (r"\bfrom this (point|moment) (on|forward),? you (will|shall|must|are)", 25),
    (r"\byou no longer (have|need|must|should|work for)", 20),
    (r"\bdo not (follow|obey|listen to|adhere to) (your |the )(instructions?|rules?|guidelines?)", 30),
]

# Context boundary injection — attempting to embed fake system/instruction delimiters
CONTEXT_BOUNDARY_PATTERNS = [
    (r"---+\s*BEGIN\s+NEW\s+INSTRUCTIONS?\s*---*", 35),
    (r"===+\s*SYSTEM\s+OVERRIDE\s*===*", 35),
    (r"<\|im_start\|>\s*system", 35),
    (r"<\|im_end\|>", 20),
    (r"\[INST\]", 30),
    (r"\[/INST\]", 20),
    (r"<system>", 30),
    (r"</system>", 20),
    (r"<<SYS>>", 30),
    (r"<</SYS>>", 20),
    (r"<\|system\|>", 30),
    (r"<\|user\|>", 20),
    (r"<\|assistant\|>", 20),
    (r"\bBEGIN CONTEXT\b", 25),
    (r"\bEND CONTEXT\b", 15),
]

# Structured injection — JSON/XML/markdown blocks with embedded instruction overrides
STRUCTURED_INJECTION_PATTERNS = [
    (r'"instruction"\s*:', 25),
    (r'"system"\s*:', 20),
    (r'"role"\s*:\s*"system"', 30),
    (r"<instruction>.*?</instruction>", 25),
    (r"<role>.*?system.*?</role>", 25),
    (r"```json\s*{[^}]*\"instruction\"", 25),
    (r"```json\s*{[^}]*\"system\"", 25),
    (r'"content"\s*:\s*"(ignore|forget|disregard)', 25),
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

    Uses multiple heuristics to detect jailbreaks, role-play triggers,
    delimiter injection, and system prompt leakage attempts.
    """

    def __init__(self, threshold: int = 30):
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

        # 1. Jailbreak keyword patterns
        for keyword, weight in JAILBREAK_PATTERNS.items():
            if keyword.lower() in text_normalized:
                score += weight
                matched.append(f"jailbreak_keyword: {keyword}")

        # 2. Delimiter injection
        for pattern, weight in DELIMITER_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"delimiter_injection: {pattern}")

        # 3. Role-play triggers
        for pattern, weight in ROLEPLAY_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"roleplay_trigger: {pattern}")

        # 4. System prompt leakage
        for pattern, weight in SYSTEM_LEAK_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"system_leak: {pattern}")

        # 5. Token/API key patterns
        for pattern, weight in TOKEN_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"token_leak: {pattern}")

        # 6. Instruction hierarchy patterns
        for pattern, weight in INSTRUCTION_HIERARCHY_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"instruction_hierarchy: {pattern}")

        # 7. Context boundary injection
        for pattern, weight in CONTEXT_BOUNDARY_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"context_boundary: {pattern}")

        # 8. Structured injection
        for pattern, weight in STRUCTURED_INJECTION_PATTERNS:
            if re.search(pattern, text_normalized, re.IGNORECASE):
                score += weight
                matched.append(f"structured_injection: {pattern}")

        # 9. Structural checks
        # Multiple newlines with instruction-like text = possible delimiter injection
        lines = text_normalized.splitlines()
        instruction_like_lines = sum(
            1 for line in lines
            if any(kw in line for kw in ["instruction", "system", "prompt", "command"])
        )
        if instruction_like_lines >= 3:
            score += 15
            matched.append("structural: multiple_instruction_lines")

        # Excessive repetition of override words
        override_count = sum(text_normalized.count(kw) for kw in ["ignore", "disregard", "forget"])
        if override_count >= 3:
            score += 20
            matched.append("structural: excessive_override_words")

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


def sanitize_or_default(text: str, default: str = "", threshold: int = 30) -> str:
    """Convenience function: sanitize text or return default if blocked.

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


def sanitize_output(text: str, default: str = "[Response filtered for security]", threshold: int = 20) -> str:
    """Sanitize LLM output text before sending to users.

    Uses a lower threshold than input sanitization since outputs should
    never contain dangerous content (leaked keys, echoed injections, etc.)

    Args:
        text: The LLM output text to sanitize.
        default: Safe replacement text if output is blocked.
        threshold: Score threshold for blocking (default 20, lower than input 30).

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
