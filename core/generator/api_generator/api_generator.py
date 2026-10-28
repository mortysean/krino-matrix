import json

from services.llm import LLM
from ...schema import State, Constraint, ActionSpace, constraints_text
from ..generator import Generator


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the action generator of a decision system. Given the current state, the goal and \
the constraints, propose {count} feasible actions that could move the state toward the goal.

Requirements:
- Each action must be concrete and executable from the current state.
- Be as specific as the request needs: when the user asks which option to choose (which stock, \
product, route, ...), each action must name the concrete options themselves, e.g. stock names and \
codes, not a method for choosing them.
- When the state contains gathered data, base the actions on it: only name options that appear in the data, \
and cite the figures that support them.
- Each action must respect every hard constraint and should respect the preferences.
- Actions must be clearly distinct, covering different strategies rather than variations of one.
- Do not rank or score the actions; they are evaluated separately.
- id: a short English snake_case verb phrase naming the action, unique within the set.
- description: a few sentences: what to do and why, in the same language as the goal.

State:
{state}

Goal:
{goal}

Constraints:
{constraints}"""


class APIGenerator(Generator):
    """Generates actions by calling a hosted LLM through services.llm."""

    def __init__(
        self,
        llm: LLM | None = None,
        num_actions: int | None = None
    ):
        self.llm = llm or LLM()
        self.num_actions = num_actions

    def generate(
        self,
        state: State,
        goal: str,
        constraints: list[Constraint]
    ) -> ActionSpace:
        prompt = PROMPT.format(
            count=self.num_actions or "3 to 5",
            state=json.dumps(state.data, ensure_ascii=False, indent=2),
            goal=goal,
            constraints=constraints_text(constraints),
        )
        return self.llm.structured(prompt, ActionSpace)
