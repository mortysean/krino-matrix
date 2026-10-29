"""Build Krino Matrix datasets (model/dataset.py): every case is state, goal, constraints and action space, labeled
for goal, constraints and best by a teacher LLM.

    python data/build_data.py legacy data/value_opus data/value_more data/value_ds1017 --out data/krino_matrix/zh
    python data/build_data.py typed-decisions --out data/krino_matrix/en
    python data/build_data.py generate --cases 1000 --out data/krino_matrix/zh_generated

legacy           cases of the earlier {state, objective, actions, gold} format: an LLM splits the objective and the
                 state into goal and constraints, and the teacher labels all three tasks afresh (the earlier value
                 labels mixed constraint penalties into the score, so none of them is kept)
typed-decisions  LocalLLaMA/typed-decisions: the question of each case that picks an action (action / disposition)
                 becomes the action space and its gold the best label; the teacher labels goal and constraints. The
                 other questions assess the state rather than choose an action, so they are dropped.
generate         new Chinese cases from latent factors (domain, difficulty, resources, time pressure, the intended
                 goal level of every action), the way the typed-decisions benchmark behind Laya was built

The teacher labels every case TEACHER_SAMPLES times at temperature 0.7 and the labels are the means, so they stay
soft where a judgement is genuinely ambiguous. Splits are by group: legacy keeps each source's test set and holds
VAL_FRACTION of the training groups out as val. Models default to LLM_DEFAULT in .env; the concrete versions are
recorded in meta. Rerun a command to continue after an interruption: finished cases are kept.
"""
import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, ConfigDict, Field, create_model

from krino.common.schema import Constraint, Action
from model.dataset import LEVELS, SPLITS, MatrixCase, Labels, group_split, load
from krino.common.llm import LLM

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
VAL_FRACTION = 0.1
TEST_FRACTION = 0.15
TYPED_DECISIONS = "LocalLLaMA/typed-decisions"
TYPED_DECISIONS_REVISION = "9ee69423ce0b0568c2d2d86e92c72ed7952fd084"
ACTION_QUESTIONS = ("action", "disposition")     # the typed-decisions questions whose options are actions

# Prompts are kept in the user turn rather than the system prompt: some gateways replace the system prompt
GENERATE_PROMPT = """You are building training data for a decision evaluator. Write one realistic decision case \
in Simplified Chinese from these latent factors:

Domain: {domain}
Difficulty: {difficulty}
Resources: {resources}
Time pressure: {time_pressure}

Write:
- state: a JSON object with the concrete facts of the current situation the decision depends on (figures, \
resources, risks), 4 to 10 fields with English snake_case keys. Only what is true now: limits go in constraints.
- goal: one sentence saying the end result the person wants, without the limits on how to get there.
- constraints: 2 to 5 limits on how the goal may be reached (deadline, budget, risk ceiling, rule, preference).
  - id: English snake_case name of the limit, unique within the case.
  - text: the limit itself.
  - hard: true if it must not be broken, false for a preference. At least one must be hard.
- actions: exactly {count} candidate actions, in this order, at these intended levels of goal attainment:
{intended}
  Some actions should break a constraint whatever their level: a strong action that breaks a hard constraint is \
the kind of trade-off the evaluator must learn.

Levels of goal attainment:
{levels}

Every action must read as a sincere proposal: never reveal or hint at its level or at a broken constraint.
- id: a short English snake_case verb phrase naming the action, unique within the case.
- description: a few sentences: what to do and why."""

SPLIT_PROMPT = """You are restructuring a decision case into a fixed format: state, goal and constraints.

Below are the state of the case and the text that says what is to be decided. Write:
- goal: the end result wanted, as one sentence, keeping its targets but none of the limits on how to get there. \
When the text asks what to do, state the outcome the decision should achieve, not "decide ...".
- constraints: every limit on how the goal may be reached that the text or the state gives: deadlines, budgets, \
risk ceilings, rules, policies, preferences. Never invent one; an empty list if there are none.
  - id: English snake_case name of the limit, unique within the case.
  - text: the limit itself, keeping its figures.
  - hard: true if it must not be broken, false for a preference.
- constraint_keys: the keys of the state whose content is only a limit that is now in constraints, so they can be \
removed from the state. Keep every key that also carries facts about the current situation.
Write goal and constraint texts in {language}.

State:
{state}

What is to be decided:
{text}"""

LABEL_PROMPT = """You are an expert evaluator of decisions. Judge every action of the action space against the \
state, the goal and the constraints.
{tasks}
Give the reason before the probabilities.

State:
{state}

Goal:
{goal}

Constraints:
{constraints}

Action space:
{actions}"""

GOAL_TASK = """
goal: how far carrying out the action would achieve the goal, given the state, on this ordered scale:
{levels}
This is goal attainment only: do not lower it because the action breaks a constraint, which is judged separately. \
An action that cannot be carried out in this state does not achieve the goal. Answer with a probability \
distribution over the levels (5 numbers summing to 1): put the mass where you believe the level is, and spread it \
only as far as you are genuinely unsure.
"""

CONSTRAINTS_TASK = """
violations: for every constraint, the probability that carrying out the action would violate it: near 1 if it \
clearly would, near 0 if it clearly would not, in between only as far as you are genuinely unsure.
"""

BEST_TASK = """
best: after judging every action, the probability that each action is the one to choose. The one to choose \
achieves the goal best among the actions that respect every hard constraint, with the preferences deciding \
between actions that are otherwise close. If every action breaks a hard constraint, it is the one whose violation \
is least serious. Give every action a probability; together they sum to 1.
"""


class Draft(BaseModel):
    state: dict
    goal: str
    constraints: list[Constraint]
    actions: list[Action]


class Split(BaseModel):
    goal: str
    constraints: list[Constraint]
    constraint_keys: list[str]


def teacher_output(actions: list[str], constraints: list[str], best: bool) -> type[BaseModel]:
    """The teacher's answer for one case as a fixed object: a required field per action, and per action a required
    field per constraint. Free lists let the teacher skip or rename actions under structured output; fixed fields
    leave it nothing to skip or rename."""

    def fields(names: list[str], annotation, description: str) -> dict:
        return {f"f{i}": (annotation, Field(alias=name, description=description)) for i, name in enumerate(names)}

    config = ConfigDict(populate_by_name=True)
    judgment = {
        "reason": (str, Field(description="One short sentence")),
        "goal": (list[float], Field(description="Exactly 5 probabilities, one per level, level 0 first, summing to 1")),
    }
    if constraints:
        violations = create_model("Violations", __config__=config,
                                  **fields(constraints, float, "Probability that the action violates this constraint"))
        judgment["violations"] = (violations, ...)
    judgment_model = create_model("Judgment", **judgment)
    output = {"judgments": (create_model("Judgments", __config__=config,
                                         **fields(actions, judgment_model, "The judgment of this action")), ...)}
    if best:
        output["best_reason"] = (str, Field(description="One short sentence on which action to choose and why"))
        output["best"] = (create_model("Best", __config__=config,
                                       **fields(actions, float, "Probability that this is the action to choose")), ...)
    return create_model("Teacher", **output)


def levels_text(lang: str) -> str:
    return "\n".join(f"- level {i}: {text}" for i, text in enumerate(LEVELS[lang]))


def constraints_list(constraints: list[Constraint]) -> str:
    return "\n".join(f"- {c.id} ({'hard' if c.hard else 'preference'}): {c.text}" for c in constraints) or "None"


async def retry(make, attempts: int = 3):
    for attempt in range(attempts):
        try:
            return await make()
        except Exception as e:
            if attempt == attempts - 1:
                raise
            print(f"  retrying after {type(e).__name__}: {e}")
            await asyncio.sleep(2 ** attempt)


def normalized(probabilities: list[float], n: int) -> list[float] | None:
    if len(probabilities) != n or any(p < 0 for p in probabilities) or sum(probabilities) <= 0:
        return None
    return [p / sum(probabilities) for p in probabilities]


def mean(rows: list[list[float]]) -> list[float]:
    m = [sum(col) / len(col) for col in zip(*rows)]
    return [round(v / sum(m), 4) for v in m]


async def label(teacher: LLM, case: MatrixCase, best: bool = True) -> MatrixCase:
    """goal and constraints labels for every action, and best unless the case brings its own, from TEACHER_SAMPLES
    teacher runs; replaces those labels. Every run must judge every action on every task, or it is asked again."""
    actions = [a.id for a in case.action_space]
    constraint_ids = {c.id for c in case.constraints}
    n_levels = len(LEVELS[case.lang])
    # The teacher sees the actions in a fresh order, so it cannot read anything from their position
    shown = random.sample(case.action_space, len(case.action_space))
    prompt = LABEL_PROMPT.format(
        tasks=GOAL_TASK.format(levels=levels_text(case.lang)) + (CONSTRAINTS_TASK if constraint_ids else "")
        + (BEST_TASK if best else ""),
        state=json.dumps(case.state, ensure_ascii=False, indent=2),
        goal=case.goal,
        constraints=constraints_list(case.constraints),
        actions="\n".join(f"- {a.id}: {a.description}" for a in shown),
    )

    constraint_order = [c.id for c in case.constraints]
    output = teacher_output([a.id for a in shown], constraint_order, best)

    async def judged() -> dict:
        """One teacher run as {"judgments": {action: {...}}, "best": {action: p}}, refused unless every value is usable."""
        result = (await teacher.astructured(prompt, output, temperature=0.7)).model_dump(by_alias=True)
        for a, j in result["judgments"].items():
            if normalized(j["goal"], n_levels) is None:
                raise ValueError(f"{a}: goal is not {n_levels} probabilities: {j['goal']}")
            if any(not 0 <= p <= 1 for p in j.get("violations", {}).values()):
                raise ValueError(f"{a}: a violation probability is outside [0, 1]")
        if best and normalized([result["best"][a] for a in actions], len(actions)) is None:
            raise ValueError(f"best is not a distribution: {result['best']}")
        return result

    runs = await asyncio.gather(*(retry(judged, attempts=4) for _ in range(TEACHER_SAMPLES)))
    goal = {a: mean([normalized(r["judgments"][a]["goal"], n_levels) for r in runs]) for a in actions}
    constraints = {
        a: {c: round(sum(r["judgments"][a]["violations"][c] for r in runs) / TEACHER_SAMPLES, 4) for c in constraint_order}
        for a in actions
    } if constraint_ids else {}
    labels = Labels(goal=goal, constraints=constraints, best=case.labels.best)
    if best:
        labels.best = dict(zip(actions, mean([normalized([r["best"][a] for a in actions], len(actions)) for r in runs])))
    tasks = ["goal", "constraints"] + (["best"] if best else [])
    meta = {**case.meta, **{f"{task}_teacher": teacher.served_model for task in tasks}}
    return case.model_copy(update={"labels": labels, "meta": meta})


async def split(llm: LLM, state: dict, text: str, lang: str) -> tuple[str, list[Constraint], dict]:
    """goal, constraints and the state without the keys that only held a limit."""
    prompt = SPLIT_PROMPT.format(language="Simplified Chinese" if lang == "zh" else "English",
                                 state=json.dumps(state, ensure_ascii=False, indent=2), text=text)
    result = await retry(lambda: llm.astructured(prompt, Split, temperature=0))
    if not result.goal.strip() or len({c.id for c in result.constraints}) != len(result.constraints):
        raise ValueError("empty goal or duplicate constraint ids")
    return result.goal, result.constraints, {k: v for k, v in state.items() if k not in result.constraint_keys}


async def run(jobs: list[tuple[str, object]], work, concurrency: int):
    """work(job) for every (id, payload) job, at most `concurrency` at a time; a failed job is reported and left
    for a rerun."""
    limit = asyncio.Semaphore(concurrency)
    done = failed = 0

    async def one(job):
        nonlocal done, failed
        async with limit:
            try:
                await work(job)
            except Exception as e:
                failed += 1
                print(f"{job[0]}: failed ({type(e).__name__}: {str(e)[:300]}), rerun to fill the gap", flush=True)
                return
        done += 1
        if done % 50 == 0:
            print(f"{done}/{len(jobs)} done, {failed} failed", flush=True)

    await asyncio.gather(*(one(job) for job in jobs))
    print(f"{done}/{len(jobs)} done, {failed} failed", flush=True)


def append(out: Path, case: MatrixCase):
    with (out / f"{case.split}.jsonl").open("a", encoding="utf-8") as f:
        f.write(case.model_dump_json() + "\n")


def finished(out: Path) -> set[str]:
    return {c.id for name in SPLITS if (out / f"{name}.jsonl").exists() for c in load(out / f"{name}.jsonl")}


def summary(out: Path):
    groups = {}
    for name in SPLITS:
        path = out / f"{name}.jsonl"
        if not path.exists():
            continue
        cases = load(path)
        groups[name] = {c.group for c in cases}
        pairs = sum(len(v) for c in cases for v in c.labels.constraints.values())
        hard = sum(p >= 0.5 for c in cases for per in c.labels.constraints.values()
                   for k, p in per.items() if next(x.hard for x in c.constraints if x.id == k))
        print(f"{name}: {len(cases)} cases, {sum(len(c.action_space) for c in cases)} actions, "
              f"{sum(len(c.constraints) for c in cases)} constraints; labels: goal {sum(len(c.labels.goal) for c in cases)}, "
              f"constraints {pairs} pairs ({hard} hard violations), best {sum(bool(c.labels.best) for c in cases)}")
    names = list(groups)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if shared := groups[a] & groups[b]:
                raise RuntimeError(f"{len(shared)} groups in both {a} and {b}")


# --------------------------------------------------------------------------------------------- legacy

async def legacy(args: argparse.Namespace):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm, teacher = LLM(args.model), LLM(args.teacher or args.model)
    print(f"splitter {llm.model} → {llm.served_model}, teacher {teacher.model} → {teacher.served_model}")
    sources = {"train": [], "test": []}
    for d in args.sources:
        for name in sources:
            lines = (Path(d) / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            sources[name] += [(f"{Path(d).name}-{name}-{i:05d}", json.loads(line)) for i, line in enumerate(lines) if line.strip()]
    # A group is the underlying case, named by its objective: every version of it stays on one side
    test_groups = {case["objective"] for _, case in sources["test"]}
    leaked = [cid for cid, case in sources["train"] if case["objective"] in test_groups]
    print(f"dropped {len(leaked)} train cases whose group is also in a test set: {leaked}")
    jobs = [(cid, (group_split(case["objective"], VAL_FRACTION), case)) for cid, case in sources["train"]
            if case["objective"] not in test_groups] + [(cid, ("test", case)) for cid, case in sources["test"]]
    skip = finished(out)
    jobs = [job for job in jobs if job[0] not in skip][:args.limit or None]

    async def work(job):
        cid, (split_name, old) = job
        goal, constraints, state = await split(llm, old["state"]["data"], old["objective"], "zh")
        factors = old.get("factors", {})
        meta = {"source": cid, "objective": old["objective"], "splitter": llm.served_model,
                "removed_state_keys": sorted(set(old["state"]["data"]) - set(state)),
                "generator": factors.get("generator_version") or factors.get("previous_teacher") or factors.get("teacher"),
                **{k: v for k, v in factors.items() if k in ("domain", "difficulty", "resources", "time_pressure")}}
        case = MatrixCase(id=cid, lang="zh", state=state, goal=goal, constraints=constraints,
                          action_space=[Action(**a) for a in old["actions"]], split=split_name, group=old["objective"],
                          meta=meta)
        append(out, await label(teacher, case))

    print(f"{len(jobs)} to convert")
    await run(jobs, work, args.concurrency)
    summary(out)


# ------------------------------------------------------------------------------------ typed-decisions

async def typed_decisions(args: argparse.Namespace):
    import pyarrow.parquet as pq
    from huggingface_hub import snapshot_download

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm, teacher = LLM(args.model), LLM(args.teacher or args.model)
    print(f"splitter {llm.model} → {llm.served_model}, teacher {teacher.model} → {teacher.served_model}")
    root = Path(snapshot_download(TYPED_DECISIONS, repo_type="dataset", revision=TYPED_DECISIONS_REVISION,
                                  allow_patterns=["all/*.parquet"]))
    jobs = []
    for name in ("train", "test"):
        rows = pq.read_table(next(root.glob(f"all/{name}-*.parquet"))).to_pylist()
        if any(r["split"] != name for r in rows):
            raise RuntimeError(f"rows of another split in the {name} file")
        # Every typed-decisions case is its own group; val comes out of its train split
        jobs += [(r["id"], ("test" if name == "test" else group_split(r["id"], VAL_FRACTION), r)) for r in rows]
    skip = finished(out)
    jobs = [job for job in jobs if job[0] not in skip][:args.limit or None]

    async def work(job):
        cid, (split_name, row) = job
        questions, gold = json.loads(row["questions"]), json.loads(row["gold"])
        qid = next(q for q in ACTION_QUESTIONS if q in questions)
        question = questions[qid]
        actions = [Action(id=k, description=v) for k, v in question["criteria"].items()]
        goal, constraints, state = await split(llm, json.loads(row["state"]), question["instructions"], "en")
        probabilities = gold[qid]["probabilities"]
        total = sum(probabilities[a.id] for a in actions)
        meta = {"source": f"{TYPED_DECISIONS}@{TYPED_DECISIONS_REVISION}", "workflow": row["workflow"],
                "question": qid, "question_text": question["instructions"], "best_teacher": "typed-decisions gold",
                "splitter": llm.served_model, "removed_state_keys": sorted(set(json.loads(row["state"])) - set(state))}
        case = MatrixCase(id=cid, lang="en", state=state, goal=goal, constraints=constraints, action_space=actions,
                          labels=Labels(best={a.id: probabilities[a.id] / total for a in actions}),
                          split=split_name, group=cid, meta=meta)
        append(out, await label(teacher, case, best=False))

    print(f"{len(jobs)} to convert")
    await run(jobs, work, args.concurrency)
    summary(out)


# ------------------------------------------------------------------------------------------- generate

def sample_factors(rng: random.Random) -> dict:
    """Latent factors for one case. The intended levels always include a good and a bad action."""
    factors = {"domain": rng.choice(DOMAINS), **{k: rng.choice(v) for k, v in FACTORS.items()}}
    intended = [rng.randint(3, 4), rng.randint(0, 1)] + [rng.randint(0, 4) for _ in range(ACTIONS_PER_CASE - 2)]
    rng.shuffle(intended)
    factors["intended_levels"] = intended
    return factors


async def generate(args: argparse.Namespace):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    generator, teacher = LLM(args.model), LLM(args.teacher or args.model)
    print(f"generator {generator.model} → {generator.served_model}, teacher {teacher.model} → {teacher.served_model}")
    done = len(finished(out))
    rng = random.Random(args.seed + done)

    async def work(job):
        cid, factors = job
        intended = "\n".join(f"{i + 1}. level {level}" for i, level in enumerate(factors["intended_levels"]))
        prompt = GENERATE_PROMPT.format(**factors, count=ACTIONS_PER_CASE, intended=intended, levels=levels_text("zh"))
        draft = await retry(lambda: generator.astructured(prompt, Draft, temperature=1.0))
        # An open dict schema sometimes comes back as {} under strict structured output: the teacher would label blind
        if not draft.state or not draft.goal.strip():
            raise ValueError("empty state or goal")
        actions = draft.actions[:ACTIONS_PER_CASE]
        if len(actions) != ACTIONS_PER_CASE or len({a.id for a in actions}) != len(actions):
            raise ValueError(f"expected {ACTIONS_PER_CASE} distinct actions, got {[a.id for a in actions]}")
        r = random.Random(cid).random()
        split_name = "test" if r < TEST_FRACTION else "val" if r < TEST_FRACTION + VAL_FRACTION else "train"
        meta = {**factors, "intended_levels": {a.id: level for a, level in zip(actions, factors["intended_levels"])},
                "source": "generate", "generator": generator.served_model}
        case = MatrixCase(id=cid, lang="zh", state=draft.state, goal=draft.goal, constraints=draft.constraints,
                          action_space=actions, split=split_name, group=cid, meta=meta)
        append(out, await label(teacher, case))

    jobs = [(f"{out.name}-{args.seed}-{done + i:05d}", sample_factors(rng)) for i in range(max(0, args.cases - done))]
    await run(jobs, work, args.concurrency)
    summary(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("legacy", "typed-decisions", "generate"):
        p = commands.add_parser(name)
        p.add_argument("--out", required=True)
        p.add_argument("--model", default=None, help="generator / splitter model; None: LLM_DEFAULT in .env")
        p.add_argument("--teacher", default=None, help="teacher model; None: same as --model")
        p.add_argument("--concurrency", type=int, default=16)
        if name == "generate":
            p.add_argument("--cases", type=int, default=400)
            p.add_argument("--seed", type=int, default=0)
        else:
            p.add_argument("--limit", type=int, default=0, help="first N cases only, for a trial run")
        if name == "legacy":
            p.add_argument("sources", nargs="+", help="dirs with train.jsonl / test.jsonl of the earlier format")
    args = parser.parse_args()
    asyncio.run({"legacy": legacy, "typed-decisions": typed_decisions, "generate": generate}[args.command](args))
