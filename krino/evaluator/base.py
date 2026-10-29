from abc import ABC, abstractmethod

from pydantic import BaseModel

from ..contract import EvaluatorInfo
from ..common.schema import Problem, Action


class Evaluation(BaseModel):
    """How an evaluator ranked the candidates.

    order        every action id, best first, excluded actions last
    choice       the recommended action, None when every action is excluded
    scores       per-action scores, only when the evaluator outputs real numbers; meaning in info.score_meaning
    confidence   only when the evaluator outputs one
    excluded     action id -> hard constraint ids it likely breaks
    pending      constraint ids the evaluator could not decide either way
    reason       one sentence on why the choice, when the evaluator gives one
    notes        action id -> one short comparison note
    """
    order: list[str]
    choice: str | None
    scores: dict[str, float] | None = None
    confidence: float | None = None
    excluded: dict[str, list[str]] = {}
    pending: list[str] = []
    reason: str = ""
    notes: dict[str, str] = {}
    checks_constraints: bool = False    # True when every hard constraint was checked against every action


class Evaluator(ABC):
    """The one evaluator interface the engine depends on; MatrixModelEvaluator implements it, tests use fakes."""

    info: EvaluatorInfo

    @abstractmethod
    def evaluate(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Evaluation:
        pass
