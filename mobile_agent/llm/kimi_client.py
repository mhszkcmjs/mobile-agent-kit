"""
Kimi(Moonshot)LLM 客户端,封装文本/视觉两种调用 + tenacity 重试。

PRD §8.4:
  - 重试 3 次指数退避,不重试 4xx
  - 单次 60s
  - 默认 temperature=0.3,路由用 0
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from openai import APIStatusError, OpenAI
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from mobile_agent.config import cfg
from mobile_agent.constants import (
    LLM_MAX_RETRIES,
    LLM_TEMPERATURE_DEFAULT,
    LLM_TIMEOUT_SEC,
)


def _is_retryable(exc: BaseException) -> bool:
    """4xx 不重试,其余重试。"""
    if isinstance(exc, APIStatusError):
        return not (400 <= exc.status_code < 500)
    return True


class KimiClient:
    def __init__(self) -> None:
        cfg.assert_llm_ready()
        self._client = OpenAI(
            api_key=cfg.MOONSHOT_API_KEY,
            base_url=cfg.MOONSHOT_BASE_URL,
            timeout=LLM_TIMEOUT_SEC,
        )

    @retry(
        stop=stop_after_attempt(LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = LLM_TEMPERATURE_DEFAULT,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or cfg.MODEL_NAME,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    @retry(
        stop=stop_after_attempt(LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    def chat_with_image(
        self,
        prompt: str,
        image_path: Path | str,
        *,
        model: str | None = None,
        temperature: float = LLM_TEMPERATURE_DEFAULT,
    ) -> str:
        img_b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                ],
            }
        ]
        resp = self._client.chat.completions.create(
            model=model or cfg.VISION_MODEL_NAME,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content or ""

    def chat_json_with_image(
        self,
        prompt: str,
        image_path: Path | str,
        *,
        model: str | None = None,
        temperature: float = LLM_TEMPERATURE_DEFAULT,
    ) -> dict[str, Any]:
        """视觉调用 + JSON 解析。"""
        raw = self.chat_with_image(prompt, image_path, model=model, temperature=temperature)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"VLM 未返回合法 JSON: {raw[:300]}") from e

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = LLM_TEMPERATURE_DEFAULT,
    ) -> dict[str, Any]:
        """带 JSON 校验的 chat。失败原始字符串 + 解析异常一起抛。"""
        raw = self.chat(messages, model=model, temperature=temperature, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM 未返回合法 JSON:{raw[:300]}") from e


# 进程级单例
_singleton: KimiClient | None = None


def get_kimi() -> KimiClient:
    global _singleton
    if _singleton is None:
        _singleton = KimiClient()
    return _singleton
