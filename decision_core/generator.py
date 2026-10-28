import json

from pydantic import Field

from services.llm import LLM
from core.schema import State, Constraint, Action, ActionSpace, constraints_text
from core.generator.generator import Generator


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the action generator of a decision assistant. Given the current state, the goal and the \
constraints, propose {count} candidate NEXT actions the user could take now.

Requirements:
- Each action is concrete, executable from the current state, and clearly distinct from the others \
(different strategies, not variations of one).
- When the user asks which option to choose, name the concrete options themselves.
- Respect every hard constraint and, where possible, the preferences.
- Do not rank or score the actions; they are evaluated separately.
- Write every text field in the same language as the goal, short and plain:
  - id: short English snake_case verb phrase naming the action, unique within the set.
  - title: the action as one short imperative sentence starting with a verb, e.g. "先用两周时间验证需求".
  - description: two or three sentences: what exactly to do.
  - why: one sentence on why this moves toward the goal.
  - difference: one short phrase on what sets it apart from the other candidates.
  - risks: 0 to 2 short limits or risks of this action.

State:
{state}

Goal:
{goal}

Constraints:
{constraints}"""


class CandidateAction(Action):
    title: str
    why: str = ""
    difference: str = ""
    risks: list[str] = Field(default_factory=list)


class CandidateSpace(ActionSpace):
    actions: list[CandidateAction]


class CardGenerator(Generator):
    """Generates 2 to 4 candidate actions with the short texts an action card needs."""

    def __init__(
        self,
        llm: LLM,
        num_actions: str = "3 (at most 4, at least 2)"
    ):
        self.llm = llm
        self.num_actions = num_actions

    def generate(
        self,
        state: State,
        goal: str,
        constraints: list[Constraint]
    ) -> CandidateSpace:
        prompt = PROMPT.format(
            count=self.num_actions,
            state=json.dumps(state.data, ensure_ascii=False, indent=2),
            goal=goal,
            constraints=constraints_text(constraints),
        )
        space = self.llm.structured(prompt, CandidateSpace)
        seen, actions = set(), []
        for action in space.actions:
            if action.id not in seen:
                seen.add(action.id)
                actions.append(action)
        return CandidateSpace(actions=actions[:4])
