from pydantic import BaseModel

from .schema import Problem, Decision
from .formulator.formulator import Formulator
from .observer.observer import Observer
from .generator.generator import Generator
from .evaluator.evaluator import Evaluator


class PipelineResult(BaseModel):
    problem: Problem
    decisions: list[Decision]   # every candidate action with its score, best first, excluded actions last

    @property
    def decision(self) -> Decision | None:
        """The best action that is not excluded, or None when every action breaks a hard constraint."""
        return next((d for d in self.decisions if not d.excluded_by), None)


class Pipeline:
    """Natural-language request → Formulator → Observer → Generator → Evaluator → Decision.

    The observer is optional: without one, the state is only what the formulator read from the request.
    """

    def __init__(
        self,
        formulator: Formulator,
        generator: Generator,
        evaluator: Evaluator,
        observer: Observer | None = None,
        max_workers: int = 8
    ):
        self.formulator = formulator
        self.observer = observer
        self.generator = generator
        self.evaluator = evaluator
        self.max_workers = max_workers     # for evaluators that score actions one at a time, concurrently

    def run(
        self,
        request: str
    ) -> PipelineResult:
        problem = self.formulator.formulate(request)
        if self.observer:
            problem = problem.model_copy(update={"state": self.observer.observe(problem)})
        space = self.generator.generate(problem.state, problem.goal, problem.constraints)
        if not space.actions:
            raise ValueError("Generator returned no actions")
        decisions = self.evaluator.decide(problem, space.actions, self.max_workers)
        return PipelineResult(problem=problem, decisions=decisions)
