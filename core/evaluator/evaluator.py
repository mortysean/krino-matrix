from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from ..schema import State, Problem, Action, Decision


class Evaluator(ABC):

    @abstractmethod
    def evaluate(
        self,
        state: State,
        goal: str,
        action: Action
    ) -> float:
        pass

    def decide(
        self,
        problem: Problem,
        actions: list[Action],
        max_workers: int = 8
    ) -> list[Decision]:
        """Every action with its score, best first.

        By default each action is scored alone with evaluate(), concurrently, and the constraints are not read. An
        evaluator that reads the whole action space and the constraints at once overrides this.
        """
        with ThreadPoolExecutor(max_workers) as pool:
            scores = list(pool.map(lambda action: self.evaluate(problem.state, problem.goal, action), actions))
        decisions = [Decision(action=action, score=score) for action, score in zip(actions, scores)]
        return sorted(decisions, key=lambda d: d.score, reverse=True)
