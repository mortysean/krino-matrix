import json
import os
import re
from fnmatch import fnmatch
from functools import cached_property
from pathlib import Path
from typing import Any, Literal, TypeVar

import anthropic
import httpx
import litellm
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

litellm.suppress_debug_info = True
litellm.drop_params = True

T = TypeVar("T", bound=BaseModel)

ANTHROPIC_MAX_TOKENS = 8192     # the Anthropic API requires max_tokens; used when the caller doesn't set it
ANTHROPIC_STOP_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


class Provider(BaseModel):
    """An endpoint that serves models. Models are always named in OpenRouter format, e.g. "deepseek/deepseek-v4.1-flash".

    backend decides how the request is sent:
      openrouter  litellm, model sent as "openrouter/<model>"
      litellm     litellm, model sent unchanged (OpenRouter names match litellm's for most direct providers)
      anthropic   official Anthropic SDK, for gateways that only accept it;
                  "anthropic/claude-opus-5.5" is sent as "claude-opus-5-5"
    """
    name: str
    backend: Literal["openrouter", "litellm", "anthropic"] = "litellm"
    api_base: str | None = None         # None: backend's default endpoint
    api_key: str | None = None          # None: read from the backend's standard env var
    models: list[str] = ["*"]           # glob patterns of models this provider serves
    native_structured: bool = True      # False: enforce JSON via prompt instead of the API's structured output

    @classmethod
    def from_env(cls, name: str) -> "Provider":
        """Read LLM_<NAME>_BACKEND / _API_BASE / _API_KEY / _MODELS / _NATIVE_STRUCTURED."""
        prefix = f"LLM_{name.upper().replace('-', '_')}_"
        return cls.model_validate({
            "name": name,
            "backend": (os.getenv(prefix + "BACKEND") or "litellm").lower(),
            "api_base": os.getenv(prefix + "API_BASE") or None,
            "api_key": os.getenv(prefix + "API_KEY") or None,
            "models": [m.strip() for m in os.getenv(prefix + "MODELS", "*").split(",") if m.strip()],
            "native_structured": os.getenv(prefix + "NATIVE_STRUCTURED", "true").lower() != "false",
        })

    def serves(self, model: str) -> bool:
        return any(fnmatch(model, pattern) for pattern in self.models)

    def backend_model(self, model: str) -> str:
        if self.backend == "openrouter":
            return f"openrouter/{model}"
        if self.backend == "anthropic":
            return model.removeprefix("anthropic/").replace(".", "-")
        return model


def list_providers() -> list[str]:
    return [name.strip() for name in os.getenv("LLM_PROVIDERS", "").split(",") if name.strip()]


def resolve_provider(model: str) -> Provider:
    """The first provider in LLM_PROVIDERS that serves the model."""
    names = list_providers()
    if not names:
        raise KeyError("LLM_PROVIDERS is not set in .env")
    for name in names:
        provider = Provider.from_env(name)
        if provider.serves(model):
            return provider
    raise KeyError(f"No provider in LLM_PROVIDERS {names} serves {model!r}; add it to some LLM_<NAME>_MODELS")


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str | None
    tool_calls: list[ToolCall] = []
    finish_reason: str | None = None    # "stop" / "length" / "tool_calls", same on every backend
    input_tokens: int = 0
    output_tokens: int = 0

    def to_message(self) -> dict:
        """The assistant turn in OpenAI format, for appending to the conversation history."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
                }
                for call in self.tool_calls
            ]
        return message


class LLM:
    """Unified chat interface. Messages and tools always use the OpenAI format, whatever the backend."""

    def __init__(
        self,
        model: str | None = None,
        provider: str | Provider | None = None,
        **defaults: Any
    ):
        """model: OpenRouter-format name, None for LLM_DEFAULT.
        provider: name in .env or explicit Provider, None to pick the first in LLM_PROVIDERS that serves the model.
        """
        model = model or os.getenv("LLM_DEFAULT")
        if not model:
            raise KeyError("No model given and LLM_DEFAULT is not set in .env")
        if provider is None:
            provider = resolve_provider(model)
        elif isinstance(provider, str):
            provider = Provider.from_env(provider)

        self.model = model
        self.provider = provider
        self.defaults = defaults
        if provider.backend == "anthropic":
            self._client = anthropic.Anthropic(api_key=provider.api_key, base_url=provider.api_base)
            self._aclient = anthropic.AsyncAnthropic(api_key=provider.api_key, base_url=provider.api_base)

    @cached_property
    def served_model(self) -> str:
        """The concrete model behind self.model, resolved on first use. OpenRouter aliases such as
        "~deepseek/deepseek-flash-latest" move to each new release, and litellm reports the alias back,
        so ask OpenRouter directly with a one-token request; other backends serve the name as given."""
        if self.provider.backend != "openrouter":
            return self.model
        response = httpx.post(
            (self.provider.api_base or "https://openrouter.ai/api/v1").rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self.provider.api_key or os.getenv('OPENROUTER_API_KEY')}"},
            json={"model": self.model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["model"]

    def chat(
        self,
        messages: str | list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs: Any
    ) -> LLMResponse:
        if self.provider.backend == "anthropic":
            request = self._anthropic_request(messages, system, tools, kwargs)
            with self._client.messages.stream(**request) as stream:
                return self._from_anthropic(stream.get_final_message())

        request = self._litellm_request(messages, system, tools, kwargs)
        # Always stream: some gateways answer with SSE even for non-stream requests
        chunks = list(litellm.completion(**request))
        return self._from_litellm(litellm.stream_chunk_builder(chunks, messages=request["messages"]))

    async def achat(
        self,
        messages: str | list[dict],
        system: str | None = None,
        tools: list[dict] | None = None,
        **kwargs: Any
    ) -> LLMResponse:
        if self.provider.backend == "anthropic":
            request = self._anthropic_request(messages, system, tools, kwargs)
            async with self._aclient.messages.stream(**request) as stream:
                return self._from_anthropic(await stream.get_final_message())

        request = self._litellm_request(messages, system, tools, kwargs)
        chunks = [chunk async for chunk in await litellm.acompletion(**request)]
        return self._from_litellm(litellm.stream_chunk_builder(chunks, messages=request["messages"]))

    def structured(
        self,
        messages: str | list[dict],
        output: type[T],
        system: str | None = None,
        **kwargs: Any
    ) -> T:
        if self.provider.backend == "anthropic" and self.provider.native_structured:
            request = self._anthropic_request(messages, system, None, kwargs)
            with self._client.messages.stream(**request, output_format=output) as stream:
                return self._parsed_anthropic(stream.get_final_message())

        messages, kwargs = self._structured_args(messages, output, kwargs)
        return self._parse(self.chat(messages, system=system, **kwargs), output)

    async def astructured(
        self,
        messages: str | list[dict],
        output: type[T],
        system: str | None = None,
        **kwargs: Any
    ) -> T:
        if self.provider.backend == "anthropic" and self.provider.native_structured:
            request = self._anthropic_request(messages, system, None, kwargs)
            async with self._aclient.messages.stream(**request, output_format=output) as stream:
                return self._parsed_anthropic(await stream.get_final_message())

        messages, kwargs = self._structured_args(messages, output, kwargs)
        return self._parse(await self.achat(messages, system=system, **kwargs), output)

    def _litellm_request(
        self,
        messages: str | list[dict],
        system: str | None,
        tools: list[dict] | None,
        kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        messages = _as_messages(messages)
        if system:
            messages = [{"role": "system", "content": system}, *messages]

        request = {
            "model": self.provider.backend_model(self.model),
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.defaults,
            **kwargs,
        }
        if self.provider.api_base:
            request["api_base"] = self.provider.api_base
        if self.provider.api_key:
            request["api_key"] = self.provider.api_key
        if tools:
            request["tools"] = tools
        return request

    def _anthropic_request(
        self,
        messages: str | list[dict],
        system: str | None,
        tools: list[dict] | None,
        kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        systems = [system] if system else []
        converted: list[dict] = []
        for message in _as_messages(messages):
            role, content = message["role"], message.get("content")
            if role == "system":
                if content:
                    systems.append(content)
                continue
            if role == "tool":
                role = "user"
                content = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": content}]
            elif role == "assistant" and message.get("tool_calls"):
                content = _blocks(content) + [
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"] or "{}"),
                    }
                    for call in message["tool_calls"]
                ]
            # Anthropic requires alternating roles, e.g. several tool results form one user turn
            if converted and converted[-1]["role"] == role:
                converted[-1]["content"] = _blocks(converted[-1]["content"]) + _blocks(content)
            else:
                converted.append({"role": role, "content": content})

        request = {
            "model": self.provider.backend_model(self.model),
            "messages": converted,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            **self.defaults,
            **kwargs,
        }
        if systems:
            request["system"] = "\n\n".join(systems)
        if tools:
            request["tools"] = [
                {
                    "name": tool["function"]["name"],
                    "description": tool["function"].get("description", ""),
                    "input_schema": tool["function"].get("parameters", {"type": "object", "properties": {}}),
                }
                for tool in tools
            ]
        return request

    def _structured_args(
        self,
        messages: str | list[dict],
        output: type[BaseModel],
        kwargs: dict[str, Any]
    ) -> tuple[list[dict], dict[str, Any]]:
        messages = _as_messages(messages)
        if self.provider.native_structured:
            return messages, {**kwargs, "response_format": output}

        # Appended to the last user turn: gateways may replace the system prompt
        schema = json.dumps(output.model_json_schema(), ensure_ascii=False)
        instruction = (
            "\n\nRespond with a single JSON object that conforms to this JSON schema, "
            f"and nothing else:\n{schema}"
        )
        last = messages[-1]
        content = last["content"]
        if isinstance(content, str):
            content = content + instruction
        else:
            content = [*content, {"type": "text", "text": instruction}]
        return [*messages[:-1], {**last, "content": content}], kwargs

    @staticmethod
    def _parse(response: LLMResponse, output: type[T]) -> T:
        if response.finish_reason == "length":
            raise ValueError(
                f"Output truncated after {response.output_tokens} tokens; increase max_tokens"
            )
        text = response.content or ""
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fenced:
            text = fenced.group(1)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"No JSON object in model output: {response.content!r}")
        return output.model_validate_json(text[start:end + 1])

    @staticmethod
    def _parsed_anthropic(message: Any) -> Any:
        if message.stop_reason == "max_tokens":
            raise ValueError(
                f"Output truncated after {message.usage.output_tokens} tokens; increase max_tokens"
            )
        return message.parsed_output

    @staticmethod
    def _from_litellm(raw: Any) -> LLMResponse:
        choice = raw.choices[0]
        message = choice.message
        usage = getattr(raw, "usage", None)
        return LLMResponse(
            content=message.content,
            tool_calls=[
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments or "{}"),
                )
                for call in (message.tool_calls or [])
            ],
            finish_reason=choice.finish_reason,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )

    @staticmethod
    def _from_anthropic(message: Any) -> LLMResponse:
        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            content=text or None,
            tool_calls=[
                ToolCall(id=block.id, name=block.name, arguments=block.input)
                for block in message.content
                if block.type == "tool_use"
            ],
            finish_reason=ANTHROPIC_STOP_REASONS.get(message.stop_reason, message.stop_reason),
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def _as_messages(messages: str | list[dict]) -> list[dict]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    return list(messages)


def _blocks(content: str | list | None) -> list:
    if not content:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content)
