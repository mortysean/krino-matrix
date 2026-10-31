"""One decision turn: input → Formulator → Clarifier → Generator → Evaluator → rules → response."""
import os
from collections.abc import Callable
from pathlib import Path

from .common.schema import Problem
from .common.tracing import TracedLLM
from .evaluator.base import Evaluator, Evaluation
from .evaluator.matrix import MatrixModelEvaluator
from .evaluator.rules import MESSAGES, lang_of, requires_confirmation
from .steps.clarifier import Clarifier
from .steps.formulator import APIFormulator, Formulator
from .steps.generator import CardGenerator, CandidateAction
from .style import PACE_LIMIT
from .contract import (
    ActionCard, ClarificationResponse, CoreInput, CoreResponse, DecisionResponse, ErrorResponse, ProblemView, Stage,
)

ROOT = Path(__file__).resolve().parents[1]
# The mmBERT-base Matrix model trained with uncertainty loss weighting; KRINO_MATRIX_CHECKPOINT overrides it
DEFAULT_CHECKPOINT = ROOT / "model/checkpoints/mmbert-uncertainty"

# Exceptions that mean the model endpoint itself is unreachable or refuses us, matched by name so the core does
# not depend on any one SDK
UNAVAILABLE = {
    "AuthenticationError", "PermissionDeniedError", "APIConnectionError", "ServiceUnavailableError",
    "RateLimitError", "Timeout", "APITimeoutError", "NotFoundError", "InternalServerError", "BadGatewayError",
}

ERRORS = {
    "zh": {
        "model_unavailable": "模型服务暂时不可用。请稍后再试；你的输入已保留。",
        "call_failed": "这次处理没有成功完成，没有生成任何结论。可以重试或修改输入。",
        "no_actions": "没能生成可行的候选行动。可以把目标描述得更具体一些再试。",
        "invalid_input": "请先输入你想实现的目标。",
    },
    "en": {
        "model_unavailable": "The model service is unavailable right now. Try again later; your input is kept.",
        "call_failed": "This run did not finish, so no conclusion was produced. Retry or edit your input.",
        "no_actions": "No feasible candidate actions came out. Try describing the goal more specifically.",
        "invalid_input": "Please enter the goal you want to reach first.",
    },
}


def compose_request(data: CoreInput) -> str:
    """Everything the user has told us for this decision, as one request for the formulator."""
    parts = [data.objective.strip()]
    if data.history:
        parts.append("Earlier in this conversation:\n" + "\n".join(f"- {h}" for h in data.history))
    if data.memories:
        parts.append("Facts the user has confirmed about themselves:\n" + "\n".join(f"- {m}" for m in data.memories))
    answered = [a for a in data.answers if not a.skipped]
    if answered:
        parts.append("Answers to follow-up questions:\n" + "\n".join(f"- {a.question}: {a.as_text()}" for a in answered))
    return "\n\n".join(parts)


def problem_view(problem: Problem) -> ProblemView:
    return ProblemView(state=problem.state.data, objective=problem.goal, constraints=problem.constraints)


class DecisionEngine:

    def __init__(
        self,
        formulator: Formulator,
        clarifier: Clarifier,
        generator: CardGenerator,
        evaluator: Evaluator,
        generator_version: Callable[[], str] = lambda: "unknown"
    ):
        self.formulator = formulator
        self.clarifier = clarifier
        self.generator = generator
        self.evaluator = evaluator
        self.generator_version = generator_version

    def run(
        self,
        data: CoreInput,
        on_stage: Callable[[Stage], None] = lambda stage: None
    ) -> CoreResponse:
        lang = lang_of(data.objective)
        if not data.objective.strip():
            return ErrorResponse(code="invalid_input", message=ERRORS[lang]["invalid_input"],
                                 retryable=False, suggestions=["edit"])
        try:
            return self._run(data, lang, on_stage)
        except Exception as e:
            code = "model_unavailable" if type(e).__name__ in UNAVAILABLE or isinstance(e, KeyError) else "call_failed"
            return ErrorResponse(code=code, message=ERRORS[lang][code],
                                 suggestions=["retry", "later"] if code == "model_unavailable" else ["retry", "edit"])

    def _run(
        self,
        data: CoreInput,
        lang: str,
        on_stage: Callable[[Stage], None]
    ) -> CoreResponse:
        on_stage("understand")
        request = compose_request(data)
        problem = self.formulator.formulate(request)

        limits = [n for n in (data.max_questions, PACE_LIMIT[data.style.pace]) if n is not None]
        limit = min(limits) if limits else None
        if limit is None or len(data.answers) < limit:
            on_stage("clarify")
            question = self.clarifier.clarify(request, problem, data.answers, data.style)
            if question:
                return ClarificationResponse(question=question, problem=problem_view(problem),
                                             asked=len(data.answers) + 1, max_questions=limit)

        on_stage("compare")
        actions = self.generator.generate(problem.state, problem.goal, problem.constraints, data.style).actions
        if not actions:
            return ErrorResponse(code="no_actions", message=ERRORS[lang]["no_actions"], suggestions=["edit", "retry"])
        evaluation = self.evaluator.evaluate(problem, actions)
        return self._decision(problem, actions, evaluation, lang)

    def _decision(
        self,
        problem: Problem,
        actions: list[CandidateAction],
        evaluation: Evaluation,
        lang: str
    ) -> DecisionResponse:
        msg = MESSAGES[lang]
        by_id = {a.id: a for a in actions}
        order = [i for i in evaluation.order if i in by_id] + [a.id for a in actions if a.id not in evaluation.order]
        cards = []
        for action_id in order:
            a = by_id[action_id]
            cards.append(ActionCard(
                id=a.id, title=a.title, description=a.description, why=a.why, difference=a.difference,
                risks=a.risks, say=a.say, excluded_by=evaluation.excluded.get(a.id, []),
                requires_confirmation=requires_confirmation(f"{a.title} {a.description}"),
            ))

        best = by_id.get(evaluation.choice) if evaluation.choice else None
        warnings = []
        if best is None:
            warnings.append(msg["all_excluded"])
        elif requires_confirmation(f"{best.title} {best.description}"):
            warnings.append(msg["confirm"])
        hard = [c for c in problem.constraints if c.hard]
        if hard and not evaluation.checks_constraints:
            warnings.append(msg["unverified"].format(items="；".join(c.text for c in hard)))
        if evaluation.pending:
            texts = {c.id: c.text for c in problem.constraints}
            warnings.append(msg["pending"].format(items="；".join(texts.get(i, i) for i in evaluation.pending)))
        warnings.append(msg["experimental"])
        info = self.evaluator.info

        titles = {a.id: a.title for a in actions}
        evidence = [f"{titles[i]}：{evaluation.notes[i]}" if lang == "zh" else f"{titles[i]}: {evaluation.notes[i]}"
                    for i in order if evaluation.notes.get(i)]
        return DecisionResponse(
            headline=best.title if best else (cards[0].title if cards else ""),
            explanation=(evaluation.reason or best.why) if best else msg["all_excluded"],
            best_action=best.id if best else None,
            actions=cards,
            action_scores=evaluation.scores,
            confidence=evaluation.confidence,
            warnings=warnings,
            problem=problem_view(problem),
            evidence=evidence,
            evaluator=info,
            model_version=f"{self.generator_version()} · {info.version}",
        )


def build_engine() -> DecisionEngine:
    """The engine the web app runs: hosted-LLM formulator, clarifier and generator, Matrix evaluator."""
    path = Path(os.getenv("KRINO_MATRIX_CHECKPOINT") or DEFAULT_CHECKPOINT)
    if not (path / "matrix_config.json").exists():
        raise FileNotFoundError(f"no Matrix checkpoint at {path}")
    llm = TracedLLM()
    return DecisionEngine(APIFormulator(llm), Clarifier(llm), CardGenerator(llm), MatrixModelEvaluator(str(path)),
                          generator_version=llm.version)
