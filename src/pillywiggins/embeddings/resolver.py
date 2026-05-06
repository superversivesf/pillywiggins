from __future__ import annotations

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

DEFAULT_HF_MODEL = "all-MiniLM-L6-v2"

PREFERRED_OLLAMA_MODELS = [
    "nomic-embed-text",
    "mxbai-embed-large",
    "all-minilm",
    "snowflake-arctic-embed",
]


async def discover_ollama_embedding_model(
    ollama_base_url: str = "http://localhost:11434",
) -> str | None:
    """Query Ollama /api/tags and pick the best embedding-capable model."""
    try:
        async with aiohttp.ClientSession() as client:
            resp = await client.get(f"{ollama_base_url}/api/tags", timeout=5.0)
            resp.raise_for_status()
            data = await resp.json()
            models = [
                m.get("name", m.get("model", "")).split(":")[0]
                for m in data.get("models", [])
            ]
            # Prefer known embedding models
            for preferred in PREFERRED_OLLAMA_MODELS:
                for name in models:
                    if preferred in name.lower():
                        return name
            # Fallback: any model with "embed" in name
            for name in models:
                if "embed" in name.lower():
                    return name
    except Exception as exc:
        logger.warning("Could not discover Ollama embedding models: %s", exc)
    return None


class HuggingFaceEmbeddingProvider:
    """sentence-transformers fallback provider."""

    def __init__(self, model_name: str = DEFAULT_HF_MODEL):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: str | list[str]) -> list[float] | list[list[float]]:
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        if isinstance(texts, str):
            return embeddings.tolist()
        return [e.tolist() for e in embeddings]
