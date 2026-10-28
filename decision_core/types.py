"""The contract between the Decision Core and every client (web today, phone and glasses later).

A turn always ends in exactly one of three responses, so swapping the model never changes the pages:
  clarification  one key question the core needs answered before it can recommend
  decision       the recommended next action and the alternatives, as cards
  error          what went wrong and what the user can do about it
"""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.schema import Action, Constraint

CORE_VERSION = "decision-core/0.1"


# ---------- input ----------

class Answer(BaseModel):
    question_id: str
    question: str
    values: list[str] = []          # chosen options
    text: str = ""                  # "other / free input"
    skipped: bool = False

    def as_text(self) -> str:
        if self.skipped:
            return "(skipped)"
        return "; ".join([*self.values, *([self.text] if self.text.strip() else [])]) or "(no answer)"


class CoreInput(BaseModel):
    """What a client sends to the core for one turn. source / timestamp / context are reserved for devices and
    sensors: the core passes them through untouched."""
    objective: str                                  # the user's own words
    answers: list[Answer] = []                      # clarification answers so far in this decision
    memories: list[str] = []                        # facts the user confirmed about themselves
    history: list[str] = []                         # short summaries of earlier decisions in the conversation
    max_questions: int = 3
    source: str = "web"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = {}


# ---------- output ----------

class ProblemView(BaseModel):
    """The structured problem extracted from the input: state, objective, constraints."""
    state: dict[str, Any]
    objective: str
    constraints: list[Constraint]


class Question(BaseModel):
    id: str
    text: str
    kind: Literal["single", "multi", "text"]
    options: list[str] = []
    allow_other: bool = True
    required: bool = False
    why: str = ""                   # one line: how the answer could change the recommendation


class ClarificationResponse(BaseModel):
    type: Literal["clarification"] = "clarification"
    question: Question
    problem: ProblemView
    asked: int                      # questions asked so far in this decision, including this one
    max_questions: int


class ActionCard(BaseModel):
    id: str
    title: str                      # starts with a verb
    description: str
    why: str = ""                   # one sentence
    difference: str = ""            # what sets it apart from the others
    risks: list[str] = []
    excluded_by: list[str] = []     # hard constraints the evaluator judged likely broken
    requires_confirmation: bool = False


class EvaluatorInfo(BaseModel):
    mode: Literal["matrix", "baseline"]
    name: str
    version: str
    experimental: bool
    score_meaning: str = ""         # what action_scores / confidence mean, shown next to them


class DecisionResponse(BaseModel):
    type: Literal["decision"] = "decision"
    headline: str                   # "建议下一步", a verb-led sentence
    explanation: str                # at most one sentence
    best_action: str | None         # None: every candidate breaks a hard constraint
    actions: list[ActionCard]       # recommended first
    action_scores: dict[str, float] | None = None   # only from a real model output
    confidence: float | None = None                 # only from a real model output
    warnings: list[str] = []
    problem: ProblemView
    evidence: list[str] = []        # how the evaluator reached the choice
    evaluator: EvaluatorInfo
    model_version: str
    core_version: str = CORE_VERSION


ErrorCode = Literal["model_unavailable", "call_failed", "quota_exceeded", "invalid_input", "no_actions"]


class ErrorResponse(BaseModel):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str
    retryable: bool = True
    suggestions: list[Literal["retry", "edit", "later"]] = ["retry", "edit"]


CoreResponse = ClarificationResponse | DecisionResponse | ErrorResponse

Stage = Literal["understand", "clarify", "compare"]


def clean_id(raw: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in raw.lower()).strip("_") or "q"


__all__ = [
    "CORE_VERSION", "Answer", "CoreInput", "ProblemView", "Question", "ClarificationResponse", "ActionCard",
    "EvaluatorInfo", "DecisionResponse", "ErrorCode", "ErrorResponse", "CoreResponse", "Stage", "Action", "clean_id",
]
