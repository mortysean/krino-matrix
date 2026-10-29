from pathlib import Path

from ..common.contract import EvaluatorInfo
from ..common.schema import Problem, Action
from .base import Evaluator, Evaluation


class MatrixModelEvaluator(Evaluator):
    """The evaluator step backed by the Matrix model (model/inference). Loaded on first use: torch and the checkpoint
    are heavy."""

    PENDING_RANGE = (0.3, 0.5)      # P(violation) of the chosen action that is neither clearly kept nor broken

    def __init__(
        self,
        path: str,
        hard_threshold: float = 0.5
    ):
        self.path = path
        self.hard_threshold = hard_threshold
        self._model = None
        self.info = EvaluatorInfo(
            name="KRINO Matrix（实验）", version=f"krino-matrix/{Path(path).name}", experimental=True,
            score_meaning="分数是模型在这组候选内的相对选择倾向，合计为 1；置信度是推荐项的该数值。"
                          "二者都不是成功概率，也不是收益或安全保证。",
        )

    @property
    def model(self):
        if self._model is None:
            from model.inference import MatrixEvaluator
            self._model = MatrixEvaluator(self.path, hard_threshold=self.hard_threshold)
        return self._model

    def evaluate(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Evaluation:
        assessment = self.model.assess(problem, actions)
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
        return Evaluation(
            order=order, choice=assessment.choice, scores={i: round(best[i], 4) for i in order},
            confidence=round(best[assessment.choice], 4) if assessment.choice else None,
            excluded=assessment.excluded, pending=pending, notes=notes,
            checks_constraints=bool(assessment.labels.constraints),
        )

