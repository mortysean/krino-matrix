from pydantic import BaseModel, Field

from services.llm import LLM
from ...schema import State, Constraint, Problem
from ..formulator import Formulator


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the problem formulator of a decision system. Turn the user's request below into \
a decision problem: the current state, the goal and the constraints.

Requirements:
- state: facts about the current situation that matter for the decision, one per entry.
  - Only facts stated or directly implied by the request; never invent missing ones.
  - Only what is true now: deadlines, budgets and preferences belong in the constraints, \
not in the state.
  - key: English snake_case, with the unit in the key when there is one, e.g. distance_to_office_km.
  - value: a number or boolean when the fact is numeric or yes/no, otherwise a short string \
in the same language as the request.
- goal: the single end result the user wants, as specific as the request allows (include the targets \
the user gave), in the same language as the request. Limits on how to get there are constraints, not goal.
- constraints: limits on how the goal may be reached (deadlines, budgets, risk ceilings, rules, preferences), \
one per entry. Do not repeat the goal. Empty if there are none.
  - id: English snake_case name of the limit, e.g. max_drawdown, unique within the problem.
  - text: the limit itself, in the same language as the request.
  - hard: true if the user must not break it, false for a preference ("最好", "ideally").
- Do not propose or recommend actions; they are generated separately.

Request:
{request}"""


class Fact(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
    value: bool | int | float | str


# What the LLM returns: facts as a list, since free-form objects are rejected by some structured output APIs
class Formulation(BaseModel):
    state: list[Fact]
    goal: str
    constraints: list[Constraint]


class APIFormulator(Formulator):
    """Formulates problems by calling a hosted LLM through services.llm."""

    def __init__(
        self,
        llm: LLM | None = None
    ):
        self.llm = llm or LLM()

    def formulate(
        self,
        request: str
    ) -> Problem:
        formulation = self.llm.structured(PROMPT.format(request=request), Formulation)
        return Problem(
            state=State(data={fact.key: fact.value for fact in formulation.state}),
            goal=formulation.goal,
            constraints=formulation.constraints,
        )
