from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

from .schema import Problem, Action
from .contract import EvaluatorInfo


class Ranking(BaseModel):
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


class Ranker(ABC):
    """The one evaluator interface the engine depends on; MatrixRanker is the implementation, tests use fakes."""

    info: EvaluatorInfo

    @abstractmethod
    def rank(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Ranking:
        pass


class MatrixRanker(Ranker):
    """The KRINO Matrix evaluator. Loaded on first use: torch and the checkpoint are heavy."""

    PENDING_RANGE = (0.3, 0.5)      # P(violation) of the chosen action that is neither clearly kept nor broken

    def __init__(
        self,
        path: str,
        hard_threshold: float = 0.5
    ):
        self.path = path
        self.hard_threshold = hard_threshold
        self._evaluator = None
        self.info = EvaluatorInfo(
            name="KRINO Matrix（实验）", version=f"krino-matrix/{Path(path).name}", experimental=True,
            score_meaning="分数是模型在这组候选内的相对选择倾向，合计为 1；置信度是推荐项的该数值。"
                          "二者都不是成功概率，也不是收益或安全保证。",
        )

    @property
    def evaluator(self):
        if self._evaluator is None:
            from .evaluator import MatrixEvaluator
            self._evaluator = MatrixEvaluator(self.path, hard_threshold=self.hard_threshold)
        return self._evaluator

    def rank(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Ranking:
        assessment = self.evaluator.assess(problem, actions)
        best = assessment.labels.best
        order = sorted((a.id for a in actions), key=lambda i: (i in assessment.excluded, -best[i]))
        pending = []
        if assessment.choice and assessment.labels.constraints:
            low, high = self.PENDING_RANGE
            pending = [c for c, p in assessment.labels.constraints[assessment.choice].items() if low <= p < high]
        notes = {}
        for action_id, dist in assessment.labels.goal.items():
            level = sum(i * p for i, p in enumerate(dist))
            notes[action_id] = f"目标达成期望档位 {level:.1f} / {len(dist) - 1}（模型输出）"
        return Ranking(
            order=order, choice=assessment.choice, scores={i: round(best[i], 4) for i in order},
            confidence=round(best[assessment.choice], 4) if assessment.choice else None,
            excluded=assessment.excluded, pending=pending, notes=notes,
            checks_constraints=bool(assessment.labels.constraints),
        )

