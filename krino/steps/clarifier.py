import json

from pydantic import BaseModel, Field

from ..common.llm import LLM
from ..common.schema import Problem, constraints_text
from ..contract import Answer, Question, clean_id
from ..style import PACES, Style, persona, voice


# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
PROMPT = """You are the clarification step of a decision assistant. The assistant will propose a few candidate \
next actions and recommend one. The user is narrowing down, step by step, what they really want, one question per \
turn and with no fixed number of turns. Decide whether ONE more piece of information would likely change which \
action gets recommended, or make the recommendation clearly more specific to this user. Ask about it only if so.

Rules:
- Build on the answers so far: each question should narrow things down further, not restart or repeat.
- Ask nothing once the request and answers already allow a specific, well-fitted recommendation; the user can \
also ask for a decision at any point.
- How readily to ask: {pace}
- Never ask about something already stated, already answered, or skipped below.
- Never ask for preferences that would not change the recommendation, or for details only needed later.
- The question must be short, in the same language as the request.
- Prefer kind "single" (one choice) or "multi" (several may apply) with 2 to 5 short, mutually distinct options; \
use "text" only when options cannot cover the likely answers. Do not include an "other" option, it is added for you.
- required: true only when no reasonable recommendation is possible without it.
- why: one short line, same language, on how the answer could change the recommendation.
- Write the question and options in the writing style below. The question may carry a touch of Krino's \
personality; the options stay plain.

{voice}

{persona}

Request:
{request}

Extracted state:
{state}

Goal:
{goal}

Constraints:
{constraints}

Already asked:
{asked}"""


class Clarification(BaseModel):
    needed: bool
    id: str = Field("", description="English snake_case name of the missing information")
    text: str = ""
    kind: str = "single"
    options: list[str] = []
    required: bool = False
    why: str = ""


class Clarifier:
    """Asks for the single piece of missing information that could change the recommendation, or nothing."""

    def __init__(
        self,
        llm: LLM
    ):
        self.llm = llm

    def clarify(
        self,
        request: str,
        problem: Problem,
        answers: list[Answer],
        style: Style = Style()
    ) -> Question | None:
        result = self.llm.structured(PROMPT.format(
            pace=PACES[style.pace], voice=voice(style), persona=persona(style),
            request=request,
            state=json.dumps(problem.state.data, ensure_ascii=False, indent=2),
            goal=problem.goal,
            constraints=constraints_text(problem.constraints),
            asked="\n".join(f"- {a.question} -> {a.as_text()}" for a in answers) or "None",
        ), Clarification)
        if not result.needed or not result.text.strip():
            return None
        asked_ids = {a.question_id for a in answers}
        qid = clean_id(result.id or result.text)
        if qid in asked_ids:
            return None
        kind = result.kind if result.kind in ("single", "multi", "text") else "single"
        options = [o.strip() for o in result.options if o.strip()][:5]
        if kind != "text" and len(options) < 2:
            kind, options = "text", []
        return Question(id=qid, text=result.text.strip(), kind=kind, options=options,
                        required=result.required, why=result.why.strip())
