import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


async def embed(
    text: str,
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
) -> Optional[list[float]]:
    if provider == "ollama":
        url = f"{base_url.rstrip('/')}/api/embed"
        payload = {"model": model, "input": text}
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": text}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Embedding request failed: %s %s", resp.status, body[:200])
                    return None
                body = await resp.json()
                if provider == "ollama":
                    return body.get("embeddings", [None])[0]
                else:
                    data = body.get("data", [])
                    if data:
                        return data[0].get("embedding")
                    return None
    except Exception:
        logger.exception("Error generating embedding")
        return None


async def embed_texts(
    texts: list[str],
    base_url: str,
    api_key: str,
    provider: str,
    model: str = "nomic-embed-text",
) -> Optional[list[list[float]]]:
    if provider == "ollama":
        url = f"{base_url.rstrip('/')}/api/embed"
        payload = {"model": model, "input": texts}
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        url = f"{base_url.rstrip('/')}/embeddings"
        payload = {"model": model, "input": texts}
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("Batch embedding request failed: %s %s", resp.status, body[:200])
                    return None
                body = await resp.json()
                if provider == "ollama":
                    return body.get("embeddings", [])
                else:
                    return [d.get("embedding") for d in body.get("data", [])]
    except Exception:
        logger.exception("Error generating batch embeddings")
        return None