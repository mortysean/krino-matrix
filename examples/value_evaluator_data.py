"""Synthesize labeled cases for the value evaluator, the way the typed-decisions benchmark behind Laya was built
(https://huggingface.co/datasets/LocalLLaMA/typed-decisions):

    python examples/value_evaluator_data.py                         # 400 cases → data/value/{train,test}.jsonl
    python examples/value_evaluator_data.py --cases 50              # a quick, cheap first batch
    python examples/value_evaluator_data.py --relabel data/value --out data/value_opus --teacher anthropic/claude-opus-5.5

1. factors:  each case starts from independently sampled latent factors (domain, difficulty, resources,
             time pressure, and the intended quality level of every action)
2. render:   a generator turns the factors into a state, an objective and the actions, without revealing quality
3. gold:     a teacher labels every action TEACHER_SAMPLES times at temperature 0.7, each time a distribution
             over LEVELS; gold is their mean, so it stays soft where a judgement is genuinely ambiguous
4. audit:    the gold must track the intended levels; the split into train / test is by case

Rerun the same command to continue after an interruption: finished cases are kept.
"""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field

from core.schema import State, Action
from core.evaluator.value_evaluator import LEVELS, Case
from services.llm import LLM

DOMAINS = [
    "日常出行与通勤", "个人储蓄与理财", "A 股股票投资", "基金与 ETF 配置", "职业选择与跳槽",
    "学习与考试规划", "租房与买房", "大件消费与购物", "健康与运动", "家庭与育儿",
    "小微企业经营", "电商运营", "项目管理与团队协作", "软件开发与技术选型", "旅行规划",
    "时间管理", "保险与风险保障", "餐饮店经营", "求职面试", "个人债务处理",
]
FACTORS = {
    "difficulty": ["简单，有明显的好办法", "中等，需要权衡", "困难，各个办法都有代价"],
    "resources": ["宽裕", "一般", "紧张"],
    "time_pressure": ["不急", "几周内", "当天或几天内"],
}
ACTIONS_PER_CASE = 5
TEACHER_SAMPLES = 3
TEST_FRACTION = 0.15

# Kept in the user turn rather than the system prompt: some gateways replace the system prompt
RENDER_PROMPT = """You are building training data for an action evaluator. Write one realistic decision case \
in Simplified Chinese from these latent factors:

Domain: {domain}
Difficulty: {difficulty}
Resources: {resources}
Time pressure: {time_pressure}

Write:
- state: a JSON object with the concrete facts the decision depends on (figures, resources, deadlines, \
preferences, risks), 4 to 10 fields with English snake_case keys.
- objective: one sentence saying what the person wants. Write any hard limit (budget, deadline, risk ceiling) \
into the objective or the state, since the evaluator sees nothing else.
- actions: exactly {count} candidate actions, in this order, at these intended quality levels:
{intended}

Quality levels:
{levels}

Every action must read as a sincere proposal: never reveal or hint at its level. Make a low level come from \
the facts of the state (it breaks a limit, ignores a fact, costs too much), not from obviously silly wording.
- id: a short English snake_case verb phrase naming the action, unique within the case.
- description: a few sentences: what to do and why."""

TEACHER_PROMPT = """You are an expert evaluator. For each candidate action, judge how much value it brings \
toward the objective, given the state, on this ordered scale:

{levels}

Answer with a probability distribution over the levels for each action (5 numbers summing to 1): put the \
mass where you believe the level is, and spread it only as far as you are genuinely unsure. Judge each \
action on its own merit against the state. Give the reason before the probabilities.

State:
{state}

Objective:
{objective}

Actions:
{actions}"""


class Draft(BaseModel):
    state: dict
    objective: str
    actions: list[Action]


class Judgment(BaseModel):
    id: str
    reason: str = Field(description="One short sentence")
    probabilities: list[float] = Field(description="One probability per level, level 0 first")


class Judgments(BaseModel):
    judgments: list[Judgment]


def levels_text() -> str:
    return "\n".join(f"- level {i}: {text}" for i, text in enumerate(LEVELS))


def sample_factors(rng: random.Random) -> dict:
    """Latent factors for one case. The intended levels always include a good and a bad action."""
    factors = {"domain": rng.choice(DOMAINS), **{k: rng.choice(v) for k, v in FACTORS.items()}}
    intended = [rng.randint(3, 4), rng.randint(0, 1)] + [rng.randint(0, 4) for _ in range(ACTIONS_PER_CASE - 2)]
    rng.shuffle(intended)
    factors["intended_levels"] = intended
    return factors


async def retry(make, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return await make()
        except Exception as e:
            if attempt == attempts - 1:
                raise
            print(f"  retrying after {type(e).__name__}: {e}")
            await asyncio.sleep(2 ** attempt)


def normalized(probabilities: list[float]) -> list[float] | None:
    if len(probabilities) != len(LEVELS) or any(p < 0 for p in probabilities) or sum(probabilities) <= 0:
        return None
    return [p / sum(probabilities) for p in probabilities]


async def build_case(generator: LLM, teacher: LLM, factors: dict) -> Case:
    intended = "\n".join(f"{i + 1}. level {level}" for i, level in enumerate(factors["intended_levels"]))
    prompt = RENDER_PROMPT.format(
        **factors, count=ACTIONS_PER_CASE, intended=intended, levels=levels_text(),
    )
    draft = await retry(lambda: generator.astructured(prompt, Draft, temperature=1.0))
    # An open dict schema sometimes comes back as {} under strict structured output: the teacher would label blind
    if not draft.state or not draft.objective.strip():
        raise ValueError("empty state or objective")
    actions = draft.actions[:ACTIONS_PER_CASE]
    if len(actions) != ACTIONS_PER_CASE or len({a.id for a in actions}) != len(actions):
        raise ValueError(f"expected {ACTIONS_PER_CASE} distinct actions, got {[a.id for a in actions]}")
    factors = {**factors, "intended_levels": {a.id: level for a, level in zip(actions, factors["intended_levels"])},
               "generator": generator.model, "generator_version": generator.served_model}
    case = Case(state=State(data=draft.state), objective=draft.objective, actions=actions, gold={}, factors=factors)
    return await label(teacher, case)


async def label(teacher: LLM, case: Case) -> Case:
    """Gold for every action of the case from TEACHER_SAMPLES teacher runs; replaces any gold it had."""
    # The teacher sees the actions in a fresh order, so it cannot read the intended levels from their position
    shown = random.sample(case.actions, len(case.actions))
    prompt = TEACHER_PROMPT.format(
        levels=levels_text(),
        state=json.dumps(case.state.data, ensure_ascii=False, indent=2),
        objective=case.objective,
        actions="\n".join(f"- {a.id}: {a.description}" for a in shown),
    )
    runs = await asyncio.gather(*(
        retry(lambda: teacher.astructured(prompt, Judgments, temperature=0.7)) for _ in range(TEACHER_SAMPLES)
    ))
    ids = {a.id for a in case.actions}
    samples: dict[str, list[list[float]]] = {}
    for run in runs:
        for j in run.judgments:
            p = normalized(j.probabilities)
            if p and j.id in ids:
                samples.setdefault(j.id, []).append(p)
    gold = {
        action_id: [round(sum(col) / len(col), 4) for col in zip(*ps)]
        for action_id, ps in samples.items()
        if len(ps) == TEACHER_SAMPLES       # the teacher skipped or renamed it in some sample: leave it unlabeled
    }
    return case.model_copy(update={"gold": gold, "factors": {
        **case.factors, "teacher": teacher.model, "teacher_version": teacher.served_model,
    }})


def audit(cases: list[Case]):
    """Does the gold track the intended levels? Laya's benchmark refuses to ship a gold that doesn't."""
    pairs = [
        (case.factors["intended_levels"][a], sum(i * p for i, p in enumerate(g)))
        for case in cases for a, g in case.gold.items()
    ]
    if len(pairs) < 2:
        return
    by_level: dict[int, list[float]] = {}
    for level, value in pairs:
        by_level.setdefault(level, []).append(value)
    print("audit: mean gold level by intended level")
    for level in sorted(by_level):
        values = by_level[level]
        print(f"  intended {level}: gold {sum(values) / len(values):.2f} ({len(values)} actions)")
    argmax = [max(range(len(g)), key=g.__getitem__) for case in cases for g in case.gold.values()]
    print("gold argmax distribution:", {i: argmax.count(i) for i in range(len(LEVELS))})


async def main(args: argparse.Namespace):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    generator = LLM(args.model)
    teacher = LLM(args.teacher or args.model)
    # Resolved once per run, so every case of a run records the same concrete versions
    print(f"generator {generator.model} → {generator.served_model}, teacher {teacher.model} → {teacher.served_model}")
    limit = asyncio.Semaphore(args.concurrency)
    path = out / "cases.jsonl"
    done = sum(1 for line in path.open(encoding="utf-8") if line.strip()) if path.exists() else 0
    rng = random.Random(args.seed + done)

    async def one(factors: dict):
        async with limit:
            try:
                case = await build_case(generator, teacher, factors)
            except Exception as e:
                print(f"case failed ({type(e).__name__}: {e}), rerun to fill the gap")
                return
        with path.open("a", encoding="utf-8") as f:
            f.write(case.model_dump_json() + "\n")
        print(f"{factors['domain']}: {[round(sum(i * p for i, p in enumerate(g)), 2) for g in case.gold.values()]}")

    async def relabel(index: int, case: Case):
        async with limit:
            try:
                case = await label(teacher, case.model_copy(update={"factors": {
                    **case.factors, "source_index": index, "previous_gold": case.gold,
                    "previous_teacher": case.factors.get("teacher", generator.model),
                }}))
            except Exception as e:
                print(f"case {index} failed ({type(e).__name__}: {e}), rerun to fill the gap")
                return
        with path.open("a", encoding="utf-8") as f:
            f.write(case.model_dump_json() + "\n")
        print(f"relabeled {index}: {[round(sum(i * p for i, p in enumerate(g)), 2) for g in case.gold.values()]}")

    if args.relabel:
        source = [Case.model_validate_json(line) for line in (Path(args.relabel) / "cases.jsonl").open(encoding="utf-8") if line.strip()]
        kept = {Case.model_validate_json(line).factors.get("source_index") for line in path.open(encoding="utf-8") if line.strip()} if path.exists() else set()
        await asyncio.gather(*(relabel(i, case) for i, case in enumerate(source) if i not in kept))
    else:
        await asyncio.gather(*(one(sample_factors(rng)) for _ in range(max(0, args.cases - done))))

    cases = [Case.model_validate_json(line) for line in path.open(encoding="utf-8") if line.strip()]
    audit(cases)
    random.Random(args.seed).shuffle(cases)
    n_test = round(len(cases) * TEST_FRACTION)
    for name, part in [("test", cases[:n_test]), ("train", cases[n_test:])]:
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            f.writelines(case.model_dump_json() + "\n" for case in part)
        print(f"{name}: {len(part)} cases, {sum(len(c.gold) for c in part)} labeled actions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=int, default=400)
    parser.add_argument("--out", default="data/value")
    parser.add_argument("--model", default=None, help="generator model; None: LLM_DEFAULT in .env")
    parser.add_argument("--teacher", default=None, help="teacher model, ideally stronger; None: same as --model")
    parser.add_argument("--relabel", default=None, help="directory whose cases.jsonl to relabel with --teacher into --out, "
                        "keeping states and actions; then run again without it to add new cases")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    asyncio.run(main(parser.parse_args()))
