import torch
from pydantic import BaseModel

from ...matrix import Labels
from ...schema import State, Problem, Action, Decision
from ..evaluator import Evaluator
from .model import MatrixModel, TASKS


class Assessment(BaseModel):
    """What the model says about an action space, and the decision that follows.

    labels holds the model's calibrated outputs for all three tasks, in the label format. excluded maps every
    action that likely breaks a hard constraint to those constraints; choice is the action selected among the
    rest, or None when every action is excluded.
    """
    labels: Labels
    excluded: dict[str, list[str]]
    choice: str | None


class MatrixEvaluator(Evaluator):
    """Assesses an action space with a MatrixModel in one forward pass.

    The decision filters before it selects: an action whose P(violation) of any hard constraint reaches
    hard_threshold is excluded, whatever its goal level or selection probability, and the choice is the most
    probable remaining action under the selection head. Training weights never enter this rule. A model trained
    without the goal or constraints head (an ablation) reports no labels for it, and without the constraints head
    excludes nothing.
    """

    def __init__(
        self,
        path: str,
        device: str | None = None,
        hard_threshold: float = 0.5
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = MatrixModel(path).to(self.device).eval()
        self.hard_threshold = hard_threshold
        self.tasks = set(self.model.config.get("tasks", TASKS))

    def assess(
        self,
        problem: Problem,
        actions: list[Action]
    ) -> Assessment:
        with torch.autocast(self.device, dtype=torch.bfloat16, enabled=self.device == "cuda"):
            p = self.model.probabilities(self.model.collate([self.model.encode(problem, actions)]))
        goal, constraints, selection = (p[k][0].float().cpu() for k in ("goal", "constraints", "selection"))
        has_constraints = "constraints" in self.tasks and problem.constraints
        labels = Labels(
            goal={a.id: goal[i].tolist() for i, a in enumerate(actions)} if "goal" in self.tasks else {},
            constraints={a.id: {c.id: float(constraints[i, j]) for j, c in enumerate(problem.constraints)}
                         for i, a in enumerate(actions)} if has_constraints else {},
            best={a.id: float(selection[i]) for i, a in enumerate(actions)},
        )
        excluded = {}
        for i, a in enumerate(actions if has_constraints else []):
            broken = [c.id for j, c in enumerate(problem.constraints)
                      if c.hard and float(constraints[i, j]) >= self.hard_threshold]
            if broken:
                excluded[a.id] = broken
        feasible = [a.id for a in actions if a.id not in excluded]
        choice = max(feasible, key=labels.best.get) if feasible else None
        return Assessment(labels=labels, excluded=excluded, choice=choice)

    def decide(
        self,
        problem: Problem,
        actions: list[Action],
        max_workers: int = 8
    ) -> list[Decision]:
        """assess() as decisions: the score is the selection probability; the actions it keeps come first, best
        first, then the excluded ones, each with the hard constraints it likely breaks."""
        assessment = self.assess(problem, actions)
        decisions = [Decision(action=a, score=assessment.labels.best[a.id], excluded_by=assessment.excluded.get(a.id, []))
                     for a in actions]
        return sorted(decisions, key=lambda d: (bool(d.excluded_by), -d.score))

    def evaluate(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> float:
        """The expected goal level of one action, scaled to [0, 1]."""
        if "goal" not in self.tasks:
            raise ValueError("this model was trained without the goal head")
        dist = self.assess(Problem(state=state, goal=goal, constraints=[]), [action]).labels.goal[action.id]
        return sum(i * p for i, p in enumerate(dist)) / (len(dist) - 1)
