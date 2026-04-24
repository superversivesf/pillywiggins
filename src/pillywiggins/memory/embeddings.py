import asyncio
import hashlib
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

# Retry/backoff config
_MAX_RETRIES = 3
_BASE_DELAY = 0.5
_MAX_DELAY = 5.0

# In-memory cache config
_CACHE_TTL_SECONDS = 3600  # 1 hour
_embedding_cache: dict[str, tuple[list | list[list], float]] = {}


def _cache_key(texts: str | list[str], base_url: str, provider: str, model: str) -> str:
    """Build a deterministic cache key for embedding request inputs."""
    if isinstance(texts, list):
        text_part = "\n".join(texts)
    else:
        text_part = texts
    raw = f"{text_part}::{base_url}::{provider}::{model}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_from_cache(key: str) -> list | list[list] | None:
    """Return cached value if TTL has not expired."""
    if key not in _embedding_cache:
        return None
    value, timestamp = _embedding_cache[key]
    if time.monotonic() - timestamp > _CACHE_TTL_SECONDS:
        del _embedding_cache[key]
        return None
    return value


def _set_cache(key: str, value: list | list[list]) -> None:
    _embedding_cache[key] = (value, time.monotonic())


def _should_retry(status: int) -> bool:
    """Retry only on 5xx server errors or network-level failures."""
    return 500 <= status < 600


async def _do_embed_request(
    url: str,
    payload: dict,
    headers: dict,
) -> dict | None:
    """Execute a single HTTP POST and return parsed JSON or None."""
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Embedding request failed: %s %s", resp.status, body[:200])
                return {"_error_status": resp.status, "_error_body": body[:200]}
            return await resp.json()


async def _embed_with_retry(
    text_or_texts: str | list[str],
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
) -> dict | None:
    """Call the embedding endpoint with retries and exponential backoff."""
    if provider == "ollama":
        url = f"{base_url.rstrip('/')}/api/embed"
        payload = {"model": model, "input": text_or_texts}
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": text_or_texts}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = await _do_embed_request(url, payload, headers)
            status = result.get("_error_status", 200)
            if status == 200:
                return result
            if not _should_retry(status):
                logger.error("Embedding returned %s (non-retryable), giving up.", status)
                return None
            # retryable error
            if attempt < _MAX_RETRIES:
                delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                logger.warning(
                    "Embedding attempt %s/%s failed with %s, retrying in %.1fs...",
                    attempt,
                    _MAX_RETRIES,
                    status,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("Embedding exhausted all %s retries.", _MAX_RETRIES)
                return None
        except Exception as exc:
            if attempt < _MAX_RETRIES:
                delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                logger.warning(
                    "Embedding attempt %s/%s raised %s, retrying in %.1fs...",
                    attempt,
                    _MAX_RETRIES,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.exception("Error generating embedding after %s retries", _MAX_RETRIES)
                return None

    return None


async def embed(
    text: str,
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
    use_cache: bool = True,
) -> list[float] | None:
    """Generate an embedding for a single text, with retry and caching."""
    key = _cache_key(text, base_url, provider, model)
    if use_cache:
        cached = _get_from_cache(key)
        if cached is not None:
            logger.debug("Embedding cache hit for single text")
            return cached

    result = await _embed_with_retry(text, base_url, api_key, provider, model)
    if result is None:
        return None

    if provider == "ollama":
        embedding = result.get("embeddings", [None])[0]
    else:
        data = result.get("data", [])
        if data:
            embedding = data[0].get("embedding")
        else:
            embedding = None

    if use_cache and embedding is not None:
        _set_cache(key, embedding)
    return embedding


async def embed_texts(
    texts: list[str],
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
    use_cache: bool = True,
) -> list[list[float]] | None:
    """Generate embeddings for a batch of texts, with retry and caching."""
    key = _cache_key(texts, base_url, provider, model)
    if use_cache:
        cached = _get_from_cache(key)
        if cached is not None:
            logger.debug("Embedding cache hit for batch texts")
            return cached

    result = await _embed_with_retry(texts, base_url, api_key, provider, model)
    if result is None:
        return None

    if provider == "ollama":
        embeddings = result.get("embeddings", [])
    else:
        embeddings = [d.get("embedding") for d in result.get("data", [])]

    if use_cache and embeddings is not None:
        _set_cache(key, embeddings)
    return embeddings
