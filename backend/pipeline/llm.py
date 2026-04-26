from __future__ import annotations

from typing import Any
import logging

import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def llm_available(timeout: float = 0.5) -> bool:
    try:
        response = requests.get(f"{settings.local_model_base_url}/api/tags", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def query_local_llm(prompt: str, timeout: float = 20.0) -> str | None:
    result = query_local_llm_detailed(prompt, timeout=timeout)
    return result.get("response")


def query_local_llm_detailed(prompt: str, timeout: float = 20.0, response_format: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": settings.local_model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": settings.local_model_num_ctx},
    }
    if response_format:
        payload["format"] = response_format
    try:
        response = requests.post(
            f"{settings.local_model_base_url}/api/generate",
            json=payload,
            timeout=timeout,
        )
        if not response.ok:
            logger.warning("Ollama generate failed: status=%s body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
        data = response.json()
        return {"response": data.get("response"), "error": None}
    except requests.Timeout:
        return {"response": None, "error": "timeout"}
    except requests.RequestException:
        return {"response": None, "error": "request_error"}
