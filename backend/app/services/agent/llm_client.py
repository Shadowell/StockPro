"""DashScope/Qwen OpenAI 兼容客户端（同步，供后台研发线程使用）。"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:/+-]{2,128}$")


def llm_api_key() -> Optional[str]:
    return str(settings.QWEN_API_KEY or "").strip() or None


def llm_available() -> bool:
    return bool(llm_api_key())


def resolve_model_name(model: Optional[str] = None) -> str:
    candidate = str(model or "").strip() or str(settings.QWEN_STOCK_MODEL or "").strip() or "qwen-plus"
    if not _MODEL_NAME_RE.fullmatch(candidate):
        raise ValueError(f"非法模型名称: {candidate}")
    return candidate


def resolve_base_url() -> str:
    return str(getattr(settings, "QWEN_BASE_URL", "") or _DEFAULT_BASE_URL).rstrip("/")


class QwenClient:
    """OpenAI Chat Completions 兼容客户端，带指数退避重试。"""

    def __init__(self, model: Optional[str] = None):
        self.api_key = llm_api_key()
        if not self.api_key:
            raise RuntimeError("QWEN_API_KEY 未配置，无法执行 AI 策略研发")
        self.model = resolve_model_name(model)
        self.base_url = resolve_base_url()

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
        max_tokens: int = 4096,
        response_format: Optional[Dict[str, str]] = None,
        max_retries: int = _MAX_RETRIES,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                with httpx.Client(timeout=120.0, trust_env=False) as client:
                    resp = client.post(url, headers=headers, json=body)
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    logger.warning("Qwen API %s (attempt %s/%s)", last_error, attempt, max_retries)
                    time.sleep(_RETRY_DELAY * attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return str(data["choices"][0]["message"]["content"])
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"Qwen API HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
            except (httpx.RequestError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
                logger.warning("Qwen API error (attempt %s/%s): %s", attempt, max_retries, last_error)
                time.sleep(_RETRY_DELAY * attempt)
        raise RuntimeError(f"Qwen API 调用失败（已重试 {max_retries} 次）: {last_error or '未知错误'}")

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        raw = self.chat(messages, temperature=temperature, max_tokens=max_tokens,
                        response_format={"type": "json_object"})
        return parse_json_block(raw)


def parse_json_block(text: str) -> Dict[str, Any]:
    content = str(text or "").strip()
    if content.startswith("```"):
        first_nl = content.find("\n")
        if first_nl != -1:
            content = content[first_nl + 1:]
        if content.rstrip().endswith("```"):
            content = content.rstrip()[:-3].strip()
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        content = content[start:end + 1]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM 返回的 JSON 不是对象")
    return parsed
