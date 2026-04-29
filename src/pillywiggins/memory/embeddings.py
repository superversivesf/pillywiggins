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

# Known embedding model dimensions — used to validate that generated
# vectors match the pgvector column width.  If the configured model
# is not in this map the dimension will be probed at runtime.
KNOWN_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "nomic-embed-text": 768,
    "nomic-embed-text-v1.5": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "all-MiniLM-L6-v2": 384,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
}


def normalize_ollama_url(base_url: str) -> str:
    """Strip the OpenAI-compatible ``/v1`` suffix so Ollama native endpoints work.

    The default ``llm_base_url`` in Settings is
    ``http://host.docker.internal:11434/v1`` – the ``/v1`` suffix is required
    by PydanticAI (which calls ``/v1/chat/completions``), but Ollama's native
    ``/api/embed`` endpoint lives at the root.  This mirrors the same
    normalization done in ``health.py`` for the LLM health-check.
    """
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        stripped = stripped[:-3]
    return stripped.rstrip("/")


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
            body = await resp.text()
            if resp.status != 200:
                logger.error(
                    "Embedding request failed: status=%s url=%s body=%s",
                    resp.status,
                    url,
                    body[:500],
                )
                return {"_error_status": resp.status, "_error_body": body[:500]}
            try:
                return await resp.json()
            except Exception:
                logger.exception(
                    "Embedding response is not valid JSON (status=%s url=%s body=%s)",
                    resp.status,
                    url,
                    body[:500],
                )
                return None


async def _embed_with_retry(
    text_or_texts: str | list[str],
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
) -> dict | None:
    """Call the embedding endpoint with retries and exponential backoff."""
    if provider == "ollama":
        # Ollama's native /api/embed endpoint is at the root, not under /v1.
        # Strip the OpenAI-compatible /v1 suffix that PydanticAI needs.
        url = f"{normalize_ollama_url(base_url)}/api/embed"
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
            if result is None:
                # Usually means the response was unparseable JSON.
                if attempt < _MAX_RETRIES:
                    delay = min(_BASE_DELAY * (2 ** (attempt - 1)), _MAX_DELAY)
                    logger.warning(
                        "Embedding attempt %s/%s returned None (unparseable), retrying in %.1fs...",
                        attempt,
                        _MAX_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("Embedding exhausted all %s retries (unparseable response).", _MAX_RETRIES)
                return None
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
    expected_dimension: int | None = None,
) -> list[float] | None:
    """Generate an embedding for a single text, with retry and caching.

    Args:
        text: The text to embed.
        base_url: API base URL (for Ollama, the /v1 suffix is stripped automatically).
        api_key: Optional API key for authentication.
        provider: "ollama" or "openai"-compatible.
        model: Embedding model name.
        use_cache: Whether to use the in-memory cache.
        expected_dimension: If set, validate that the returned vector has this
            many dimensions. Mismatches are logged as errors and None is returned.

    Returns:
        A list of floats representing the embedding, or None on failure.
    """
    key = _cache_key(text, base_url, provider, model)
    if use_cache:
        cached = _get_from_cache(key)
        if cached is not None:
            logger.debug("Embedding cache hit for single text")
            return cached

    result = await _embed_with_retry(text, base_url, api_key, provider, model)
    if result is None:
        logger.error(
            "Embedding generation failed: provider=%s model=%s text=%r",
            provider, model, text[:100],
        )
        return None

    if provider == "ollama":
        embedding = result.get("embeddings", [None])[0]
    else:
        data = result.get("data", [])
        if data:
            embedding = data[0].get("embedding")
        else:
            embedding = None

    if embedding is None:
        logger.error(
            "Embedding response contained no vector: provider=%s model=%s response_keys=%s",
            provider, model, list(result.keys()),
        )
        return None

    if expected_dimension is not None and len(embedding) != expected_dimension:
        logger.error(
            "Embedding dimension mismatch: model=%s expected=%d actual=%d. "
            "Update embedding_model config or re-initialize the database with the correct vector dimension.",
            model, expected_dimension, len(embedding),
        )
        return None

    if use_cache:
        _set_cache(key, embedding)
    return embedding


async def embed_texts(
    texts: list[str],
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
    use_cache: bool = True,
    expected_dimension: int | None = None,
) -> list[list[float]] | None:
    """Generate embeddings for a batch of texts, with retry and caching.

    Args:
        texts: List of texts to embed.
        base_url: API base URL (for Ollama, the /v1 suffix is stripped automatically).
        api_key: Optional API key for authentication.
        provider: "ollama" or "openai"-compatible.
        model: Embedding model name.
        use_cache: Whether to use the in-memory cache.
        expected_dimension: If set, validate that each returned vector has this
            many dimensions. Mismatches are logged as errors and None is returned.

    Returns:
        A list of embedding vectors, or None on failure.
    """
    key = _cache_key(texts, base_url, provider, model)
    if use_cache:
        cached = _get_from_cache(key)
        if cached is not None:
            logger.debug("Embedding cache hit for batch texts")
            return cached

    result = await _embed_with_retry(texts, base_url, api_key, provider, model)
    if result is None:
        logger.error(
            "Batch embedding generation failed: provider=%s model=%s num_texts=%d",
            provider, model, len(texts),
        )
        return None

    if provider == "ollama":
        embeddings = result.get("embeddings", [])
    else:
        embeddings = [d.get("embedding") for d in result.get("data", [])]

    if not embeddings or any(e is None for e in embeddings):
        logger.error(
            "Batch embedding response had missing vectors: provider=%s model=%s num_returned=%d",
            provider, model, len(embeddings),
        )
        return None

    if expected_dimension is not None:
        for idx, vec in enumerate(embeddings):
            if len(vec) != expected_dimension:
                logger.error(
                    "Batch embedding dimension mismatch at index %d: model=%s expected=%d actual=%d. "
                    "Update embedding_model config or re-initialize the database.",
                    idx, model, expected_dimension, len(vec),
                )
                return None

    if use_cache:
        _set_cache(key, embeddings)
    return embeddings


async def check_embedding_health(
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
    expected_dimension: int | None = None,
) -> dict:
    """Verify that the embedding endpoint is reachable and produces valid vectors.

    Returns a dict with:
        - ``healthy`` (bool): Whether the check passed.
        - ``model`` (str): The model name tested.
        - ``dimension`` (int | None): Actual vector dimension produced (or None on failure).
        - ``expected_dimension`` (int | None): The expected dimension, if provided.
        - ``dimension_match`` (bool | None): True if dimensions match, None if not checked.
        - ``error`` (str | None): Error message on failure.
    """
    result: dict = {
        "healthy": False,
        "model": model,
        "dimension": None,
        "expected_dimension": expected_dimension,
        "dimension_match": None,
        "error": None,
    }
    try:
        vec = await embed(
            "health check probe",
            base_url=base_url,
            api_key=api_key,
            provider=provider,
            model=model,
            use_cache=False,
            # Don't validate dimension inside embed — we want to observe the
            # actual dimension even if it mismatches, so we can report it.
        )
        if vec is None:
            result["error"] = f"Embedding endpoint returned None (provider={provider}, model={model})"
            return result
        result["dimension"] = len(vec)
        if expected_dimension is not None:
            result["dimension_match"] = len(vec) == expected_dimension
            if not result["dimension_match"]:
                result["error"] = (
                    f"Dimension mismatch: model {model} produces {len(vec)}-dim vectors, "
                    f"but expected {expected_dimension}"
                )
                return result
        result["healthy"] = True
    except Exception as exc:
        result["error"] = f"Embedding health check exception: {exc}"
    return result


def get_expected_dimension(model: str, fallback: int = 768) -> int:
    """Return the known vector dimension for *model*, or *fallback* if unknown."""
    return KNOWN_EMBEDDING_DIMENSIONS.get(model, fallback)
