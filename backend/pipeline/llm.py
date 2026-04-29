from __future__ import annotations

from typing import Any
import logging

import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def _api_base_url() -> str:
    base = settings.local_model_base_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _request_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.local_model_api_key:
        headers["Authorization"] = f"Bearer {settings.local_model_api_key}"
    return headers


def llm_available(timeout: float = 0.5) -> bool:
    try:
        response = requests.get(f"{_api_base_url()}/models", headers=_request_headers(), timeout=timeout)
        return response.ok
    except requests.RequestException:
        return False


def _post_chat_completion(payload: dict[str, Any], timeout: float) -> requests.Response:
    return requests.post(
        f"{_api_base_url()}/chat/completions",
        headers=_request_headers(),
        json=payload,
        timeout=timeout,
    )


def query_local_llm(prompt: str, timeout: float = 20.0) -> str | None:
    result = query_local_llm_detailed(prompt, timeout=timeout)
    return result.get("response")


def query_local_messages_detailed(
    messages: list[dict[str, str]],
    timeout: float = 20.0,
    response_format: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": settings.local_model_temperature,
        "top_p": settings.local_model_top_p,
        "top_k": settings.local_model_top_k,
        "min_p": settings.local_model_min_p,
        "presence_penalty": settings.local_model_presence_penalty,
        "repetition_penalty": settings.local_model_repetition_penalty,
        "frequency_penalty": settings.local_model_frequency_penalty,
        "stream": False,
        "max_tokens": 8192,
        "chat_template_kwargs": {"enable_thinking": settings.local_model_enable_thinking},
    }
    effective_model_name = model_name if model_name is not None else settings.local_model_name
    if effective_model_name:
        payload["model"] = effective_model_name
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}
    try:
        response = _post_chat_completion(payload, timeout)
        if not response.ok:
            logger.warning("OpenAI-compatible chat completion failed: status=%s body=%s", response.status_code, response.text[:500])
            response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        content = None
        if choices:
            content = (((choices[0] or {}).get("message") or {}).get("content"))
        return {"response": content, "error": None}
    except requests.Timeout:
        return {"response": None, "error": "timeout"}
    except requests.RequestException:
        return {"response": None, "error": "request_error"}


def query_local_llm_detailed(
    prompt: str,
    timeout: float = 20.0,
    response_format: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    return query_local_messages_detailed(
        [
            {"role": "user", "content": prompt},
        ],
        timeout=timeout,
        response_format=response_format,
        model_name=model_name,
    )
