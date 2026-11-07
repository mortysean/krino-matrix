"""模型调用：一个很薄的接口（complete / stream），OpenRouter 实现 + 离线 mock（mock.py）。"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from . import credits
from .config import settings

log = logging.getLogger("krino.llm")


@dataclass
class LLMResult:
    text: str
    refused: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    sources: list = None  # 联网时查过的网页 [{url, title}]


def collect_sources(annotations, into: list | None) -> list:
    """OpenRouter 的 url_citation 标注 → [{url, title}]，去重，最多 6 个。"""
    out = into if into is not None else []
    for a in annotations or []:
        c = a.get("url_citation") or {} if isinstance(a, dict) else {}
        url = str(c.get("url") or "")
        if url.startswith(("http://", "https://")) and all(x["url"] != url for x in out) and len(out) < 6:
            out.append({"url": url[:500], "title": str(c.get("title") or "")[:120]})
    return out


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    def complete(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
                 context: dict | None = None) -> LLMResult: ...

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]: ...


def web_tool() -> dict:
    """OpenRouter 的服务端搜索工具：模型自己决定查不查、查什么，OpenRouter 查完把结果交给模型，不需要我们这边循环。"""
    params = {"max_results": settings.web_search_results, "max_uses": settings.web_search_max_uses}
    if settings.web_search != "auto":
        params["engine"] = settings.web_search
    return {"type": "openrouter:web_search", "parameters": params}


def _no_web(context: dict | None) -> dict:
    return {**(context or {}), "web": False}


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
                "max_tokens": max_tokens or settings.llm_max_tokens, "reasoning": reasoning,
                "usage": {"include": True},  # 让 OpenRouter 返回这次的实际花费，用来记积分
                **({"tools": [web_tool()]} if (context or {}).get("web") else {})}

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
        if resp.status_code in (400, 403, 404) and "tools" in body:  # 这个模型 / 工作区用不了搜索：不联网照常回答
            log.warning("联网搜索不可用（%s），这次不联网：%s", resp.status_code, resp.text[:200])
            return self.complete(system=system, messages=messages, max_tokens=max_tokens, context=_no_web(context))
        if resp.status_code != 200:
            self._raise_for(resp)
        data = resp.json()
        if "error" in data:
            log.error("OpenRouter upstream error: %s", data["error"])
            raise LLMError("模型服务出错")
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        credits.charge_llm((context or {}).get("payer"), usage, data.get("model", body["model"]))
        sources = collect_sources((choice.get("message") or {}).get("annotations"), (context or {}).get("sources"))
        return LLMResult(text=text, refused=choice.get("finish_reason") == "content_filter" or not text, sources=sources,
                         model=data.get("model", body["model"]), input_tokens=usage.get("prompt_tokens", 0) or 0,
                         output_tokens=usage.get("completion_tokens", 0) or 0)

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]:
        body = {**self._body(system, messages, max_tokens, context), "stream": True}
        try:
            usage, fallback = None, False
            with self._client.stream("POST", "/chat/completions", json=body, headers=self._headers()) as resp:
                if resp.status_code in (400, 403, 404) and "tools" in body:
                    resp.read()
                    log.warning("联网搜索不可用（%s），这次不联网：%s", resp.status_code, resp.text[:200])
                    fallback = True
                elif resp.status_code != 200:
                    resp.read()
                    self._raise_for(resp)
                for line in ([] if fallback else resp.iter_lines()):
                    if not line.startswith("data:"):
                        continue  # SSE 注释（": OPENROUTER PROCESSING"）和空行
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except ValueError:
                        continue
                    if "error" in data:
                        raise LLMError("模型服务出错")
                    usage = data.get("usage") or usage  # 最后一块带着整次的用量
                    d = (data.get("choices") or [{}])[0].get("delta") or {}
                    if d.get("annotations") and (context or {}).get("sources") is not None:
                        collect_sources(d["annotations"], context["sources"])
                    delta = d.get("content")
                    if delta:
                        yield delta
            if fallback:
                yield from self.stream(system=system, messages=messages, max_tokens=max_tokens, context=_no_web(context))
                return
            credits.charge_llm((context or {}).get("payer"), usage, body["model"])
        except httpx.TimeoutException as e:
            raise LLMError("模型响应超时，请稍后再试") from e
        except httpx.HTTPError as e:
            raise LLMError("无法连接模型服务") from e


class OmniLLM:
    """“直接听”：百炼 Qwen-Omni（OpenAI 兼容接口）。最后一条用户消息换成录音（context["audio"]，WAV 的 base64），
    人设、记忆、前面的对话照常是文字。只用来回应语音，打字聊天不走这里。"""

    name = "omni"

    def __init__(self) -> None:
        self._client = httpx.Client(base_url=settings.dashscope_base_url.replace("/api/v1", "/compatible-mode/v1").rstrip("/"),
                                    timeout=httpx.Timeout(settings.llm_timeout_s, connect=10))

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]:
        ctx = context or {}
        msgs = [{"role": "system", "content": system}, *messages]
        audio = ctx.get("audio")
        if audio:
            note = "（这是对方刚说的话，语音）" if ctx.get("lang") != "en" else "(what they just said, as audio)"
            msgs[-1] = {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "data:;base64," + audio, "format": "wav"}},
                                                    {"type": "text", "text": note}]}
        body = {"model": settings.hear_model, "messages": msgs, "stream": True, "stream_options": {"include_usage": True},
                "modalities": ["text"], "max_tokens": max_tokens or settings.llm_max_tokens}
        usage = None
        try:
            with self._client.stream("POST", "/chat/completions", json=body,
                                     headers={"Authorization": f"Bearer {settings.dashscope_api_key}"}) as resp:
                if resp.status_code != 200:
                    resp.read()
                    log.error("Qwen-Omni %s: %s", resp.status_code, resp.text[:300])
                    raise LLMError({429: "听不过来了，请稍后再说一次"}.get(resp.status_code, f"听的服务出错（{resp.status_code}）"))
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except ValueError:
                        continue
                    usage = data.get("usage") or usage
                    for ch in data.get("choices") or []:
                        delta = (ch.get("delta") or {}).get("content")
                        if delta:
                            yield delta
        except httpx.TimeoutException as e:
            raise LLMError("听的服务响应超时，请再说一次") from e
        except httpx.HTTPError as e:
            raise LLMError("无法连接听的服务") from e
        if usage:
            details = usage.get("prompt_tokens_details") or {}
            audio_t = details.get("audio_tokens") or 0
            text_t = (usage.get("prompt_tokens") or 0) - audio_t
            cny = (text_t * settings.hear_price_text_in + audio_t * settings.hear_price_audio_in
                   + (usage.get("completion_tokens") or 0) * settings.hear_price_out) / 1_000_000
            credits.charge(ctx.get("payer"), "hear", cny, model=settings.hear_model, audio_tokens=audio_t)


def transcribe_for_record(audio_b64: str, payer: str | None = None) -> str:
    """记下你说的原话（只用来存对话记录和整理记忆；她的回答是直接听录音得出的，不靠这个）。失败返回空字符串。"""
    if settings.hear_provider == "mock" or settings.llm_provider == "mock":
        return "（模拟听到的话）你好呀，今天过得怎么样"
    try:
        r = httpx.post(settings.dashscope_base_url.replace("/api/v1", "/compatible-mode/v1").rstrip("/") + "/chat/completions",
                       headers={"Authorization": f"Bearer {settings.dashscope_api_key}"}, timeout=40,
                       json={"model": settings.hear_asr_model, "stream": False, "asr_options": {"enable_itn": True},
                             "messages": [{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + audio_b64}}]}]})
        if r.status_code != 200:
            log.warning("记录原话失败 %s: %s", r.status_code, r.text[:200])
            return ""
        text = str(((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("记录原话失败：%s", e)
        return ""
    seconds = len(audio_b64) * 3 / 4 / 32000  # 16kHz 16bit 单声道
    credits.charge(payer, "hear_asr", seconds * settings.hear_asr_price, seconds=round(seconds, 1))
    return text[:2000]


def hear_ready() -> bool:
    return settings.hear_provider == "mock" or (settings.hear_provider == "dashscope" and bool(settings.dashscope_api_key))


_hear: OmniLLM | None = None


def get_hear_llm():
    """能直接听的模型；没配置就返回 None（前端退回“先识别成文字”）。"""
    global _hear
    if settings.hear_provider == "mock" or (settings.hear_provider != "off" and settings.llm_provider == "mock"):
        from .mock import MockLLM
        return MockLLM()
    if not hear_ready():
        return None
    _hear = _hear or OmniLLM()
    return _hear


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
