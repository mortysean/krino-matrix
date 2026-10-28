import torch

from ...schema import State, Action
from ..evaluator import Evaluator
from .model import ValueModel, expected_value


class ValueEvaluator(Evaluator):
    """Scores an action with a ValueModel: a single forward pass, no generated tokens."""

    def __init__(
        self,
        model: ValueModel | None = None,
        device: str | None = None
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = (model or ValueModel()).to(self.device).eval()

    def distribution(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> list[float]:
        """Calibrated probability of each level in model.levels."""
        return self.model.probabilities([self.model.encode(state, goal, action)])[0].tolist()

    def evaluate(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> float:
        """The expected level scaled to [0, 1]."""
        return expected_value(torch.tensor(self.distribution(state, goal, action))).item()
