import torch

from ...schema import State, Action
from ..evaluator import Evaluator
from .model import ValueModel, as_text


class ValueEvaluator(Evaluator):
    """Scores an action with a ValueModel: a single forward pass, no generated tokens."""

    def __init__(
        self,
        model: ValueModel | None = None,
        device: str | None = None
    ):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = (model or ValueModel()).to(self.device).eval()

    @torch.no_grad()
    def evaluate(
        self,
        state: State,
        objective: str,
        action: Action
    ) -> float:
        return self.model([as_text(state, objective, action)]).item()
