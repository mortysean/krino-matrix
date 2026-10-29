"""Unify the zh and en Krino Matrix datasets before joint training.

    python scripts/unify_data.py relabel-en --data data/krino_matrix/en --target-constraints 7
    python scripts/unify_data.py resplit --data data/krino_matrix --seed 0

relabel-en brings the en set to the zh structure and label semantics in two steps per case:
  1. constraints: the teacher proposes the constraints the state implies (per-case count drawn to match zh's
     mean), which are then labeled as violations like every other constraint. Cases that already carry
     constraints keep them and are topped up; the state keys that only held a limit are dropped.
  2. best: relabeled by the same teacher that labels goal and constraints, so the three tasks share one
     standard. The typed-decisions gold stays in meta.previous_best.
Rerunning continues after an interruption: finished cases keep a meta.unified marker.

resplit puts every language on the same train / val / test proportions, stratified by group so no group
straddles two splits, and rewrites the three files of each language in place.
"""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, ConfigDict, Field, create_model

from krino.matrix import LEVELS, SPLITS, Labels, MatrixCase, load
from krino.schema import Constraint
from scripts.build_data import (
    BEST_TASK, CONSTRAINTS_TASK, GOAL_TASK, TEACHER_SAMPLES, constraints_list, label, levels_text, mean,
    normalized, retry,
)
from krino.llm import LLM

VAL_FRACTION = 0.1
TEST_FRACTION = 0.15

PROPOSE_PROMPT = """A decision case is being brought to a fixed structure for training. The state holds facts \
(and possibly limits stranded inside it); the goal holds what is wanted.

Name the constraints this decision is subject to: every limit on HOW the goal may be reached that the state or \
the goal states or clearly implies, whether a hard prohibition or a preference. One limit per entry, in English, \
phrased as a rule on the action. Do not invent limits that nothing supports, and do not restate the goal.
Return between {low} and {high} of them.

State:
{state}

Goal:
{goal}

Constraints already recorded (do not repeat these):
{existing}"""


class Proposal(BaseModel):
    constraint_keys: list[str]


class Proposed(BaseModel):
    constraints: list[Constraint]


def judge_schema(n_actions: int, n_constraints: int) -> type[BaseModel]:
    """The teacher's answer with best only: a required field per action, so nothing can be skipped or renamed."""
    config = ConfigDict(populate_by_name=True)

    def fields(names, annotation, description):
        return {f"f{i}": (annotation, Field(alias=name, description=description)) for i, name in enumerate(names)}

    violations = create_model(
        "Violations", __config__=config,
        **fields([f"c{i}" for i in range(n_constraints)], float, "Probability that the action violates this constraint"))
    judgment = create_model(
        "Judgment", __config__=config,
        reason=(str, Field(description="One short sentence")),
        goal=(list[float], Field(description="Exactly 5 probabilities, one per level, level 0 first, summing to 1")),
        violations=(violations, ...))
    names = [f"a{i}" for i in range(n_actions)]
    return create_model(
        "Teacher", **{
            "judgments": (create_model("Judgments", __config__=config,
                                       **fields(names, judgment, "The judgment of this action")), ...),
            "best_reason": (str, Field(description="One short sentence on which action to choose and why")),
            "best": (create_model("Best", __config__=config,
                                  **fields(names, float, "Probability that this is the action to choose")), ...),
        })


async def propose(llm: LLM, case: MatrixCase, low: int, high: int) -> list[Constraint]:
    """Constraints the state and goal imply beyond the ones recorded, ids unique against the existing ones."""
    prompt = PROPOSE_PROMPT.format(low=low, high=high, state=json.dumps(case.state, ensure_ascii=False, indent=2),
                                   goal=case.goal, existing=constraints_list(case.constraints))
    result = await retry(lambda: llm.astructured(prompt, Proposed, temperature=0.3))
    taken = {c.id for c in case.constraints}
    out = []
    for c in result.constraints:
        if not c.text.strip() or c.id in taken:
            continue
        taken.add(c.id)
        out.append(c)
    return out[:max(0, high)]


async def relabel_best(llm: LLM, case: MatrixCase) -> MatrixCase:
    """goal, violations and best from one teacher with one standard, as scripts/build_data.label does."""
    actions = list(case.action_space)
    order = [c.id for c in case.constraints]
    shown = random.sample(actions, len(actions))
    prompt = "You are an expert evaluator of decisions. Judge every action of the action space against the " \
             "state, the goal and the constraints.\n" + GOAL_TASK.format(levels=levels_text(case.lang)) \
             + CONSTRAINTS_TASK + BEST_TASK + "\nGive the reason before the probabilities.\n\n" \
             + f"State:\n{json.dumps(case.state, ensure_ascii=False, indent=2)}\n\nGoal:\n{case.goal}\n\n" \
             + f"Constraints:\n{constraints_list(case.constraints)}\n\nAction space:\n" \
             + "\n".join(f"- {a.id}: {a.description}" for a in shown)
    schema = judge_schema(len(shown), len(order))
    names = {f"a{i}": a.id for i, a in enumerate(shown)}

    async def judged() -> dict:
        result = (await llm.astructured(prompt, schema, temperature=0.7)).model_dump(by_alias=True)
        for key, j in result["judgments"].items():
            if normalized(j["goal"], len(LEVELS[case.lang])) is None:
                raise ValueError(f"{key}: goal is not a distribution: {j['goal']}")
            if any(not 0 <= float(p) <= 1 for p in j["violations"].values()):
                raise ValueError(f"{key}: a violation probability is outside [0, 1]")
        if normalized([result["best"][k] for k in names], len(names)) is None:
            raise ValueError(f"best is not a distribution: {result['best']}")
        return result

    runs = await asyncio.gather(*(retry(judged, attempts=4) for _ in range(TEACHER_SAMPLES)))
    goal, violations = {}, {}
    for key, action in names.items():
        goal[action] = mean([normalized(r["judgments"][key]["goal"], len(LEVELS[case.lang])) for r in runs])
        violations[action] = {c: round(sum(float(r["judgments"][key]["violations"][f"c{i}"]) for r in runs)
                                       / TEACHER_SAMPLES, 4) for i, c in enumerate(order)}
    # judged() already refused any unusable run, so every entry here is a distribution; fail loudly if not
    averages = [normalized([r["best"][k] for k in names], len(names)) for r in runs]
    if any(a is None for a in averages):
        raise ValueError("a best distribution became unusable after validation")
    best = dict(zip(names.values(), mean(averages)))
    if sorted(best) != sorted(a.id for a in case.action_space):
        raise ValueError(f"best does not cover the action space: {sorted(best)}")
    previous = case.meta.get("previous_best", case.labels.best)
    meta = {**case.meta, "goal_teacher": llm.served_model, "constraints_teacher": llm.served_model,
            "best_teacher": llm.served_model, "previous_best": previous, "unified": True}
    return case.model_copy(update={"labels": Labels(goal=goal, constraints=violations or {}, best=best), "meta": meta})


async def unify_one(llm: LLM, case: MatrixCase, target: int, limit: asyncio.Semaphore) -> MatrixCase:
    async with limit:
        if target > len(case.constraints):
            low = max(1, len(case.constraints))
            added = await propose(llm, case, low, target)
            if added:
                case = case.model_copy(update={"constraints": [*case.constraints, *added]})
        # the state keys that only held a limit are dropped, so the limit is read from one place only
        stranded = [k for k in case.state if k == "constraints"]
        if stranded:
            case = case.model_copy(update={"state": {k: v for k, v in case.state.items() if k not in stranded}})
        return await relabel_best(llm, case)


def compact(out: Path) -> None:
    """Rewrite each split with one case per id, keeping the last copy written.

    relabel-en appends finished cases so nothing is lost on an interruption, which leaves the superseded copy
    behind each time; this collapses them. Safe to run at any point, including after a killed run.
    """
    for name in SPLITS:
        path = out / f"{name}.jsonl"
        if not path.exists():
            continue
        latest: dict[str, MatrixCase] = {}
        for case in load(path):
            latest[case.id] = case
        tmp = path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(case.model_dump_json() + "\n" for case in latest.values())
        tmp.replace(path)
        unified = sum(1 for c in latest.values() if c.meta.get("unified"))
        print(f"{name}: {len(latest)} cases, {unified} unified")


async def relabel_en(args: argparse.Namespace) -> None:
    out = Path(args.data)
    cases = [c for name in SPLITS if (out / f"{name}.jsonl").exists() for c in load(out / f"{name}.jsonl")]
    todo = [c for c in cases if not c.meta.get("unified")]
    print(f"{len(todo)} of {len(cases)} en cases to unify, target constraints {args.target_constraints}")
    llm, limit = LLM(args.model), asyncio.Semaphore(args.concurrency)
    done = 0
    failed = 0

    async def work(case: MatrixCase):
        nonlocal done, failed
        try:
            unified = await unify_one(llm, case, args.target_constraints, limit)
        except Exception as e:
            failed += 1
            print(f"  {case.id} failed ({type(e).__name__}: {str(e)[:120]}), rerun to fill the gap", flush=True)
            return
        # appended one at a time, so an interruption never loses the cases already paid for
        with (out / f"{case.split}.jsonl").open("a", encoding="utf-8") as f:
            f.write(unified.model_dump_json() + "\n")
        done += 1
        if done % 25 == 0:
            print(f"  {done}/{len(todo)} unified, {failed} failed", flush=True)

    # A case that exhausts its retries is reported and skipped, never left to stall the whole batch
    await asyncio.gather(*(work(c) for c in todo), return_exceptions=True)
    print(f"{done}/{len(todo)} unified, {failed} failed")
    compact(out)


def resplit(args: argparse.Namespace) -> None:
    """Same proportions for every language, stratified by group: every version of a case lands on one side."""
    root = Path(args.data)
    for lang in args.langs:
        cases = [c for name in SPLITS if (root / lang / f"{name}.jsonl").exists()
                 for c in load(root / lang / f"{name}.jsonl")]
        groups: dict[str, list[MatrixCase]] = {}
        for case in cases:
            groups.setdefault(case.group, []).append(case)
        order = sorted(groups)
        random.Random(f"{args.seed}-{lang}").shuffle(order)
        n_test = round(len(cases) * TEST_FRACTION)
        n_val = round(len(cases) * VAL_FRACTION)
        target = {"test": n_test, "val": n_val, "train": len(cases) - n_test - n_val}
        buckets: dict[str, list[MatrixCase]] = {name: [] for name in SPLITS}
        for group in order:
            name = max(("test", "val", "train"), key=lambda n: target[n] - len(buckets[n]) if target[n] > 0 else -1e9)
            for case in groups[group]:
                buckets[name].append(case.model_copy(update={"split": name}))
            target[name] -= len(groups[group])
        for name in SPLITS:
            path = root / lang / f"{name}.jsonl"
            tmp = path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.writelines(c.model_dump_json() + "\n" for c in buckets[name])
            tmp.replace(path)
            print(f"{lang}/{name}: {len(buckets[name])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("relabel-en")
    p.add_argument("--data", default="data/krino_matrix/en")
    p.add_argument("--target-constraints", type=int, default=7, help="constraints per case to reach")
    p.add_argument("--model", default=None)
    p.add_argument("--concurrency", type=int, default=12)
    p.set_defaults(func=relabel_en)

    p = sub.add_parser("resplit")
    p.add_argument("--data", default="data/krino_matrix")
    p.add_argument("--langs", nargs="+", default=["zh", "en"])
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=resplit)

    p = sub.add_parser("compact", help="collapse the copies relabel-en appends, keeping the last of each id")
    p.add_argument("--data", default="data/krino_matrix/en")
    p.set_defaults(func=lambda a: compact(Path(a.data)))

    args = parser.parse_args()
    if asyncio.iscoroutinefunction(args.func):
        asyncio.run(args.func(args))
    else:
        args.func(args)
