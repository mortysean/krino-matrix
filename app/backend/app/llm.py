"""模型调用：一个很薄的接口（complete / stream），OpenRouter 实现 + 离线 mock（mock.py）。"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from .config import settings

log = logging.getLogger("krino.llm")


@dataclass
class LLMResult:
    text: str
    refused: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def complete(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
                 context: dict | None = None) -> LLMResult: ...

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]: ...


class OpenRouterLLM:
    """OpenRouter（OpenAI 兼容的 /chat/completions）。密钥只在服务端。"""

    name = "openrouter"

    def __init__(self) -> None:
        self._client = httpx.Client(base_url=settings.llm_base_url.rstrip("/"),
                                    timeout=httpx.Timeout(settings.llm_timeout_s, connect=10),
                                    headers={"X-Title": "KRINO WORLD"})

    def _body(self, system: str, messages: list[dict], max_tokens: int | None, context: dict | None) -> dict:
        if not settings.llm_api_key:
            raise LLMError("未配置 OPENROUTER_API_KEY，请在 .env 中填写，或设置 LLM_PROVIDER=mock 离线演示")
        reasoning = {"enabled": False} if settings.llm_reasoning == "off" else {"effort": settings.llm_reasoning, "exclude": True}
        return {"model": (context or {}).get("model") or settings.llm_model,
                "messages": [{"role": "system", "content": system}, *messages],
                "max_tokens": max_tokens or settings.llm_max_tokens, "reasoning": reasoning}

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {settings.llm_api_key}"}

    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        try:
            detail = str(resp.json().get("error", {}).get("message", ""))[:200]
        except ValueError:
            detail = resp.text[:200]
        log.error("OpenRouter %s: %s", resp.status_code, detail)
        raise LLMError({429: "模型服务繁忙，请稍后再试", 402: "OpenRouter 余额不足",
                        401: "OpenRouter 密钥无效", 403: "OpenRouter 密钥无权限"}.get(resp.status_code,
                                                                                     f"模型服务出错（{resp.status_code}）"))

    def complete(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
                 context: dict | None = None) -> LLMResult:
        body = self._body(system, messages, max_tokens, context)
        try:
            resp = self._client.post("/chat/completions", json=body, headers=self._headers())
        except httpx.TimeoutException as e:
            raise LLMError("模型响应超时，请稍后再试") from e
        except httpx.HTTPError as e:
            raise LLMError("无法连接模型服务") from e
        if resp.status_code != 200:
            self._raise_for(resp)
        data = resp.json()
        if "error" in data:
            log.error("OpenRouter upstream error: %s", data["error"])
            raise LLMError("模型服务出错")
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return LLMResult(text=text, refused=choice.get("finish_reason") == "content_filter" or not text,
                         model=data.get("model", body["model"]), input_tokens=usage.get("prompt_tokens", 0) or 0,
                         output_tokens=usage.get("completion_tokens", 0) or 0)

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]:
        body = {**self._body(system, messages, max_tokens, context), "stream": True}
        try:
            with self._client.stream("POST", "/chat/completions", json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    resp.read()
                    self._raise_for(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue  # SSE 注释（": OPENROUTER PROCESSING"）和空行
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        data = json.loads(payload)
                    except ValueError:
                        continue
                    if "error" in data:
                        raise LLMError("模型服务出错")
                    delta = ((data.get("choices") or [{}])[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
        except httpx.TimeoutException as e:
            raise LLMError("模型响应超时，请稍后再试") from e
        except httpx.HTTPError as e:
            raise LLMError("无法连接模型服务") from e


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        if settings.llm_provider == "openrouter":
            _llm = OpenRouterLLM()
        else:
            from .mock import MockLLM

            _llm = MockLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    """测试用。"""
    global _llm
    _llm = llm
