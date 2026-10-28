"""From benchmark questions to ValueModel inputs, and back.

The ValueModel was trained on one question only: INSTRUCTION, answered over its five fixed LEVELS.
No benchmark question is that question (native_compatibility counts them), so there is no native score.

What the adapter does instead: the Laya-style head reads each option from its own text at a [MASK],
so every question is asked with the benchmark's own criteria as the option texts, in the benchmark's
order, and the probabilities are returned under the benchmark's own keys. Nothing is mapped onto the
five trained levels and no label is renamed. This is out-of-distribution use of the trained head
(English questions and option sets it never saw), reported as such.

Model input per question: state, the question's instructions (as the objective), the question id
(as the action id) and the option texts. Gold is never passed in.
"""
import json
import time
from contextlib import contextmanager

import torch

from core.schema import State, Action
from core.evaluator.value_evaluator import ValueModel, LEVELS
from core.evaluator.value_evaluator.model import INSTRUCTION

# The two noul questions without criteria get the plain meaning of noul ("probability that the statement is true").
NOUL_DEFAULT = {"false": "The statement is false.", "true": "The statement is true."}


def options(question: dict) -> dict[str, str]:
    """Option key → option text, in the order the benchmark lists them."""
    criteria = question.get("criteria")
    if question["type"] == "score":
        return {str(i): text for i, text in enumerate(criteria)}
    if question["type"] == "noul" and not criteria:
        return dict(NOUL_DEFAULT)
    return {key: f"{key}: {text}" for key, text in criteria.items()}


def native_compatibility(question: dict) -> tuple[bool, str]:
    """Whether the question is the one the model was trained on, and why not."""
    if question["type"] != "score":
        return False, f"{question['type']}: the model only outputs the fixed 5-level value rubric"
    if len(question.get("criteria") or []) != len(LEVELS):
        return False, f"score with {len(question['criteria'])} levels: the model has exactly {len(LEVELS)}"
    if question["criteria"] != LEVELS or question["instructions"] != INSTRUCTION:
        return False, "score with 5 levels, but a different question and rubric than the trained one"
    return True, "identical question and rubric"


@contextmanager
def option_texts(
    model: ValueModel,
    texts: list[str]
):
    """Ask model.encode with these option texts in place of the trained levels (restored afterwards)."""
    saved = model.levels
    model.levels = texts
    try:
        yield
    finally:
        model.levels = saved


def state_tokens(
    model: ValueModel,
    case_state: dict
) -> int:
    return len(model.tokenizer(json.dumps(case_state, ensure_ascii=False), add_special_tokens=False)["input_ids"])


@torch.no_grad()
def predict_case(
    model: ValueModel,
    case_state: dict,
    questions: dict[str, dict]
) -> tuple[dict[str, dict], float]:
    """Answers for every question of one case in one forward pass, and the wall time in ms
    (encoding + forward + softmax), like one /v1/systemone request per case."""
    device = model.temperature.device
    if device.type == "cuda":
        torch.cuda.synchronize()
    start = time.perf_counter()
    state = State(data=case_state)
    encoded, keys = [], []
    for qid, question in questions.items():
        opts = options(question)
        with option_texts(model, list(opts.values())):
            encoded.append(model.encode(state, question["instructions"], Action(id=qid, description="")))
        keys.append((qid, question["type"], list(opts)))
    # one forward pass per option count (a batch needs the same number of [MASK] markers per row)
    probabilities = [None] * len(encoded)
    for n in {len(opts) for _, _, opts in keys}:
        rows = [i for i, (_, _, opts) in enumerate(keys) if len(opts) == n]
        for i, p in zip(rows, model.probabilities([encoded[i] for i in rows]).tolist()):
            probabilities[i] = p
    answers = {}
    for (qid, qtype, opts), p in zip(keys, probabilities):
        answer = {"type": qtype, "probabilities": dict(zip(opts, p))}
        if qtype == "score":
            answer["score"] = sum(i * v for i, v in enumerate(p))
        if qtype == "noul":
            answer["noul"] = answer["probabilities"]["true"]
        answers[qid] = answer
    if device.type == "cuda":
        torch.cuda.synchronize()
    return answers, (time.perf_counter() - start) * 1000
