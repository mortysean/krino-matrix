"""Krino Matrix: the format of every labeled decision case, for training and for benchmarks.

A case is a decision problem and its action space:
  state         facts about the current situation
  goal          the end result wanted
  constraints   limits on how the goal may be reached, each hard (never violate) or soft (a preference)
  action_space  the candidate actions
with labels for the three tasks of the evaluator:
  goal          how far each action achieves the goal: a distribution over LEVELS[lang]. Goal attainment only:
                breaking a constraint is the constraints label's business and does not lower this one
  constraints   whether each action violates each constraint: P(violation) per action and constraint
  best          which action to choose, weighing goal attainment, hard constraints and soft preferences together:
                a distribution over action ids
Labels are soft: the mean of several teacher samples, so they stay uncertain where a judgement is. A case may carry
any subset of them, and a missing label is missing, never 0. state, goal, constraints and action_space are the
model input; meta records how the case was built and is never model input. split and group keep every version of
the same underlying case on one side of train / val / test.
"""
import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from .schema import State, Constraint, Problem, Action, ActionSpace

FORMAT = "krino-matrix/1"
# The ordered rubric of the goal task; level i is answer i. It measures goal attainment only, so it never mentions
# constraints. Part of the model input, so keep it fixed.
LEVELS = {
    "zh": [
        "无助于目标：几乎不推进目标，做不到，或让目标更难实现",
        "帮助很小：只轻微推进目标，大概率达不到",
        "部分达成：实质推进目标，但难以完整实现",
        "大概率达成：很可能实现目标，只有小的不确定",
        "几乎确定达成：在当前状态下能最可靠地实现目标",
    ],
    "en": [
        "No help: barely moves toward the goal, cannot be done, or makes the goal harder",
        "Little help: only slightly advances the goal, likely to fall short",
        "Partial: substantially advances the goal but is unlikely to fully achieve it",
        "Likely: will probably achieve the goal, with minor uncertainty",
        "Near certain: the most reliable way to achieve the goal in this state",
    ],
}
SPLITS = ("train", "val", "test")
TOLERANCE = 1e-3


class Labels(BaseModel):
    goal: dict[str, list[float]] = {}
    constraints: dict[str, dict[str, float]] = {}
    best: dict[str, float] = {}


class MatrixCase(BaseModel):
    format: Literal["krino-matrix/1"] = FORMAT
    id: str
    lang: Literal["zh", "en"]
    state: dict[str, Any]
    goal: str
    constraints: list[Constraint]
    action_space: list[Action]
    labels: Labels = Labels()
    split: Literal["train", "val", "test"]
    group: str
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def check(self) -> "MatrixCase":
        actions = [a.id for a in self.action_space]
        constraints = [c.id for c in self.constraints]
        if len(set(actions)) != len(actions) or len(set(constraints)) != len(constraints):
            raise ValueError(f"{self.id}: duplicate action or constraint ids")
        labels = self.labels
        if labels.best:
            if set(labels.best) != set(actions):
                raise ValueError(f"{self.id}: best must cover exactly the action space")
            if any(p < 0 for p in labels.best.values()) or abs(sum(labels.best.values()) - 1) > TOLERANCE:
                raise ValueError(f"{self.id}: best is not a distribution")
        for a, dist in labels.goal.items():
            if a not in actions or len(dist) != len(LEVELS[self.lang]):
                raise ValueError(f"{self.id}: goal label for {a!r} has no action or the wrong length")
            if any(p < 0 for p in dist) or abs(sum(dist) - 1) > TOLERANCE:
                raise ValueError(f"{self.id}: goal label for {a!r} is not a distribution")
        for a, per_constraint in labels.constraints.items():
            if a not in actions or not set(per_constraint) <= set(constraints):
                raise ValueError(f"{self.id}: constraints label for {a!r} names an unknown action or constraint")
            if any(not 0 <= p <= 1 for p in per_constraint.values()):
                raise ValueError(f"{self.id}: constraints label for {a!r} is not a probability")
        return self

    def problem(self) -> Problem:
        return Problem(state=State(data=self.state), goal=self.goal, constraints=self.constraints)

    def actions(self) -> ActionSpace:
        return ActionSpace(actions=self.action_space)


def load(path: str | Path) -> list[MatrixCase]:
    """One case per line of a JSONL file."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [MatrixCase.model_validate_json(line) for line in lines if line.strip()]


def save(cases: list[MatrixCase], path: str | Path):
    with Path(path).open("w", encoding="utf-8") as f:
        f.writelines(case.model_dump_json() + "\n" for case in cases)


def group_split(group: str, val_fraction: float) -> Literal["train", "val"]:
    """A stable train / val assignment by group, so every case of a group lands on the same side."""
    bucket = int.from_bytes(hashlib.sha256(group.encode("utf-8")).digest()[:8], "big") / 2 ** 64
    return "val" if bucket < val_fraction else "train"


def language(text: str) -> Literal["zh", "en"]:
    return "zh" if any("一" <= ch <= "鿿" for ch in text) else "en"
