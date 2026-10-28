"""Implementations of the core's Ranker interface.

baseline  a general LLM compares the candidates; clearly labeled as a test mode, never shows numeric scores
matrix    the KRINO Matrix evaluator (experimental): one forward pass, real selection probabilities
"""
from pathlib import Path

from pydantic import BaseModel

from core.schema import Problem, Action
from decision_core.ranker import Ranker, Ranking
from decision_core.types import EvaluatorInfo
from services.llm import LLM


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
BASELINE_PROMPT = """You compare candidate next actions for a user and pick the one to recommend.

Requirements:
- Pick the action that best reaches the goal from the current state while keeping every hard constraint and, \
where possible, the preferences.
- For each action, list the ids of the hard constraints it likely breaks (excluded) and of the constraints you \
cannot tell either way from the information given (unsure). Never pick an action that likely breaks a hard \
constraint; if every action does, set best to "".
- reason: one sentence on why the pick beats the others. note: one short comparison per action. \
Both in the same language as the goal.

State:
{state}

Goal:
{goal}

Constraints (id: text):
{constraints}

Actions:
{actions}"""


class ActionJudgement(BaseModel):
    id: str
    note: str = ""
    breaks: list[str] = []
    unsure: list[str] = []


class Comparison(BaseModel):
    best: str
    reason: str = ""
    order: list[str]
    actions: list[ActionJudgement]


class BaselineRanker(Ranker):

    def __init__(
        self,
        llm: LLM
    ):
        self.llm = llm
        self.info = EvaluatorInfo(mode="baseline", name="Baseline（通用大模型比较）", version="baseline-llm/0.1",
                                  experimental=True)

    def rank(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Ranking:
        ids = [a.id for a in actions]
        hard = {c.id for c in problem.constraints if c.hard}
        known = {c.id for c in problem.constraints}
        result = self.llm.structured(BASELINE_PROMPT.format(
            state=problem.state.data,
            goal=problem.goal,
            constraints="\n".join(f"- {c.id}: {c.text}" + ("" if c.hard else " (preference)")
                                  for c in problem.constraints) or "None",
            actions="\n".join(f"- {a.id}: {a.description}" for a in actions),
        ), Comparison)
        judged = {j.id: j for j in result.actions if j.id in ids}
        excluded = {i: [c for c in j.breaks if c in hard] for i, j in judged.items()}
        excluded = {i: cs for i, cs in excluded.items() if cs}
        pending = sorted({c for i, j in judged.items() if i not in excluded for c in j.unsure if c in known})
        order = [i for i in dict.fromkeys(result.order) if i in ids] + [i for i in ids if i not in result.order]
        order = [i for i in order if i not in excluded] + [i for i in order if i in excluded]
        choice = result.best if result.best in ids and result.best not in excluded else None
        if choice is None and result.best:
            choice = next((i for i in order if i not in excluded), None)
        if choice:
            order = [choice] + [i for i in order if i != choice]
        return Ranking(order=order, choice=choice, excluded=excluded, pending=pending, reason=result.reason.strip(),
                       notes={i: j.note for i, j in judged.items() if j.note}, checks_constraints=True)


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
            mode="matrix", name="KRINO Matrix（实验）", version=f"krino-matrix/{Path(path).name}", experimental=True,
            score_meaning="分数是模型在这组候选内的相对选择倾向，合计为 1；置信度是推荐项的该数值。"
                          "二者都不是成功概率，也不是收益或安全保证。",
        )

    @property
    def evaluator(self):
        if self._evaluator is None:
            from core.evaluator.matrix_evaluator import MatrixEvaluator
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

