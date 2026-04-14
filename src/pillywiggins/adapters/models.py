import logging
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    id: str
    owned_by: str = ""


async def list_models(base_url: str, api_key: str, provider: str) -> list[ModelInfo]:
    if provider == "ollama":
        url = f"{base_url.rstrip('/')}/v1/models"
    else:
        url = f"{base_url.rstrip('/')}/models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("Failed to list models: %s %s", resp.status, text[:200])
                    return []
                body = await resp.json()
                models = []
                for m in body.get("data", []):
                    models.append(ModelInfo(id=m.get("id", ""), owned_by=m.get("owned_by", "")))
                return models
    except Exception:
        logger.exception("Error listing models")
        return []