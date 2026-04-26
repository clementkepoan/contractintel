from __future__ import annotations

from typing import Any

import requests

from backend.config import settings


def llm_available(timeout: float = 0.5) -> bool:
    try:
        response = requests.get(f"{settings.local_model_base_url}/api/tags", timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def query_local_llm(prompt: str, timeout: float = 20.0) -> str | None:
    try:
        response = requests.post(
            f"{settings.local_model_base_url}/api/generate",
            json={
                "model": settings.local_model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": settings.local_model_num_ctx},
            },
            timeout=timeout,
        )
        if not response.ok:
            print(f"Ollama generate failed: status={response.status_code} body={response.text[:500]}")
            response.raise_for_status()
        data = response.json()
        return data.get("response")
    except requests.RequestException:
        return None
