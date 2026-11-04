import json

from pydantic import Field

from ..common.llm import LLM
from ..common.schema import State, Constraint, Action, ActionSpace, constraints_text
from ..style import Style, persona, voice


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the action generator of a decision assistant. Given the current state, the goal and the \
constraints, propose {count} candidate answers. Each candidate is a final answer the user can act on right away, \
written as the action that carries it out.

Requirements:
- Commit to answers. Each candidate is itself the answer to what the user asked, not a way to find the answer:
  - "今天下午吃什么" -> "去吃一碗牛肉面", "点一份轻食沙拉", not "打开外卖 App 看看" or "列出想吃的".
  - "我接下来要做什么" -> the concrete task to do, e.g. "写论文第二章的实验部分", not "列一个待办清单".
  - "买 A 还是 B" -> "买 A" and "买 B" (and a third real option if there is one).
- No process or meta actions (make a list, think it over, research, compare, ask someone, set a plan, review \
progress) unless the answer truly depends on a fact nobody in the conversation has, and even then make it \
specific to that one fact.
- When the state lacks a detail, pick the most likely sensible answer rather than stepping back to ask; \
say the assumption in why.
- Candidates are clearly distinct from each other (different answers, not variations of one), each fits the \
current state and can be done now.
- Respect every hard constraint and, where possible, the preferences.
- Do not rank or score the actions; they are evaluated separately.
- Write every text field in the same language as the goal, following the writing style below:
  - id: short English snake_case verb phrase naming the action, unique within the set.
  - title: the answer itself as one short imperative sentence starting with a verb, e.g. "去吃一碗牛肉面".
  - description: two or three short sentences: how to carry out this answer, step by step. Plain and neutral: \
no personality here.
  - why: one sentence on why this moves toward the goal.
  - difference: one short phrase on what sets it apart from the other candidates.
  - risks: 0 to 2 short limits or risks of this action.
  - say: one short line Krino says when handing this action to the user, in Krino's personality below; at most \
about 25 Chinese characters or 15 English words. It may add warmth or attitude, but no new facts or steps.

{voice}

{persona}

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
    say: str = ""


class CandidateSpace(ActionSpace):
    actions: list[CandidateAction]


class CardGenerator:
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
        constraints: list[Constraint],
        style: Style = Style()
    ) -> CandidateSpace:
        prompt = PROMPT.format(
            voice=voice(style),
            persona=persona(style),
            count=self.num_actions,
            state=json.dumps(state.data, ensure_ascii=False, indent=2),
            goal=goal,
            constraints=constraints_text(constraints),
        )
        actions = []
        for _ in range(2):      # a degenerate reply (e.g. every field "好的") is retried once
            actions = usable(self.llm.structured(prompt, CandidateSpace).actions)
            if len(actions) >= 2:
                break
        return CandidateSpace(actions=actions[:4])


def usable(actions: list[CandidateAction]) -> list[CandidateAction]:
    """Distinct candidates whose description actually says how to carry them out."""
    seen, kept = set(), []
    for a in actions:
        title, description = a.title.strip(), a.description.strip()
        if a.id in seen or not title or len(description) < 8 or description == title:
            continue
        seen.add(a.id)
        kept.append(a)
    return kept
