from abc import ABC, abstractmethod
from ..schema import State, Constraint, ActionSpace


class Generator(ABC):

    @abstractmethod
    def generate(
        self,
        state: State,
        goal: str,
        constraints: list[Constraint]
    ) -> ActionSpace:
        pass