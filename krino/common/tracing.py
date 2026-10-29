import os
import threading
import time
from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel

from .llm import LLM, LLMResponse


class Call(BaseModel):
    stage: str
    model: str
    duration_ms: int
    ok: bool
    error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class CallLog:
    """The model calls of one turn, so failures and latency can be traced per user and conversation."""

    def __init__(self):
        self.stage = "unknown"
        self.calls: list[Call] = []


current_log: ContextVar[CallLog | None] = ContextVar("current_log", default=None)


class TracedLLM(LLM):
    """LLM that records every call into the CallLog of the current turn."""

    VERSION_TTL = 3600

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._local = threading.local()     # call depth, per thread: one instance serves concurrent turns
        self._version: tuple[float, str] | None = None

    def _record(self, start: float, ok: bool, error: str = ""):
        log = current_log.get()
        if log is None:
            return
        tokens = getattr(self._local, "tokens", (0, 0))
        log.calls.append(Call(
            stage=log.stage, model=self.model, duration_ms=int((time.perf_counter() - start) * 1000), ok=ok,
            error=error[:500], input_tokens=tokens[0], output_tokens=tokens[1],
        ))

    def _traced(self, fn, *args: Any, **kwargs: Any):
        # structured() calls chat() underneath: only the outermost call is recorded
        depth = getattr(self._local, "depth", 0)
        if depth == 0:
            self._local.tokens = (0, 0)
        self._local.depth = depth + 1
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:
            if depth == 0:
                self._record(start, False, f"{type(e).__name__}: {e}")
            raise
        finally:
            self._local.depth = depth
        if isinstance(result, LLMResponse):
            i, o = self._local.tokens
            self._local.tokens = (i + result.input_tokens, o + result.output_tokens)
        if depth == 0:
            self._record(start, True)
        return result

    def chat(self, *args: Any, **kwargs: Any) -> LLMResponse:
        return self._traced(super().chat, *args, **kwargs)

    def structured(self, *args: Any, **kwargs: Any):
        return self._traced(super().structured, *args, **kwargs)

    def version(self) -> str:
        """The concrete model behind an alias, cached for an hour; the alias itself when it cannot be resolved."""
        now = time.time()
        if self._version and now - self._version[0] < self.VERSION_TTL:
            return self._version[1]
        try:
            served = self.served_model
            self.__dict__.pop("served_model", None)
        except Exception:
            served = self.model
        self._version = (now, served)
        return served


def model_configured() -> bool:
    return bool(os.getenv("LLM_DEFAULT")) and bool(os.getenv("LLM_PROVIDERS"))
