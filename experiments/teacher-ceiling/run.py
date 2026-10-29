"""Teacher self-consistency ceiling of the Krino Matrix labels: relabel the test sets with exactly the pipeline that
produced the original labels, score the old labels against the new ones.

    python experiments/teacher-ceiling/run.py --limit 3          # trial run on the first 3 cases of each set
    python experiments/teacher-ceiling/run.py                   # all 675 test cases, 2025 samples
    python experiments/teacher-ceiling/run.py --sets zh         # one set
    python experiments/teacher-ceiling/run.py --report-only     # rebuild report.md from raw/, no teacher calls

Every test case was labeled by scripts/build_data.py: label() in three independent teacher runs at
temperature 0.7, the reasons and probabilities in one structured output, the actions in a fresh random order per run,
every run retried (4 attempts) unless every value is usable, and the labels the means of the three runs. This script
repeats that for each test case with the model recorded in meta.goal_teacher, but keeps the three raw runs:

  1. sample     raw/{set}.jsonl gets one line per run (case id, run index, shown action order, served_model, the full
                output, latency, attempts, error). A case whose run indices 0-2 all validate is skipped, so an
                interrupted run continues where it stopped.
  2. assess     the three runs become an Assessment the way MatrixEvaluator.assess does it (hard constraints at 0.5
                exclude, the most probable remaining action is the choice) for four "models": teacher-relabel (the
                mean of the three runs, the original labeling pipeline), teacher-single-s1/-s2/-s3 (one run each).
  3. score      scripts/benchmark.py's score() against the original test labels. The model files are exactly
                what that benchmark writes, so it lists them next to the trained models.
  4. noise      agreement between the runs themselves: argmax of best, expected goal level.
  5. report     results/report.md.

Nothing under krino/, scripts/ or data/ is modified, and no GPU is used.
"""
import argparse
import asyncio
import json
import os
import platform
import random
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
# This machine's proxy settings end in NO_PROXY="...,[::1]": httpx reads "[::1]" as a bracketed host with an invalid
# port and every client fails to build (liteLLM, and httpx in LLM.served_model), so it is dropped before llm.py loads.
for name in ("NO_PROXY", "no_proxy"):
    if os.environ.get(name):
        os.environ[name] = ",".join(p for p in os.environ[name].split(",") if p != "[::1]")

import numpy as np                                                                     # noqa: E402

from krino.matrix import LEVELS, Labels, MatrixCase, load                               # noqa: E402
from krino.evaluator import Assessment                                # noqa: E402
from krino.llm import LLM                                                          # noqa: E402
from scripts.build_data import (                                              # noqa: E402
    BEST_TASK, CONSTRAINTS_TASK, GOAL_TASK, LABEL_PROMPT, constraints_list, levels_text, mean, normalized,
    retry, teacher_output,
)

from scripts import benchmark                                                  # noqa: E402  (import only)

SETS = {"zh": "data/krino_matrix/zh", "en": "data/krino_matrix/en"}
SAMPLES = 3                 # TEACHER_SAMPLES in scripts/build_data.py: label() averages this many runs
ATTEMPTS = 4                # label()'s retry(judged, attempts=4)
TEMPERATURE = 0.7
HARD = 0.5                  # MatrixEvaluator's hard_threshold
TEACHER = "deepseek/deepseek-v4.1-flash-1017"
MODELS = ["teacher-relabel"] + [f"teacher-single-s{i}" for i in range(1, SAMPLES + 1)]
SINGLE = MODELS[1:]

OUT = Path(__file__).resolve().parent
RAW = OUT / "raw"
RESULTS = OUT / "results"
LOGS = OUT / "logs"

# What every raw line must carry to be usable; anything else (the counters) is ignored
RAW_FIELDS = {"set", "id", "sample", "index", "action_order", "constraint_order", "served_model", "output",
              "latency_ms", "attempts", "error"}
# Rows of an earlier version also carry the prompt: they are not kept, only counted
LEGACY_FIELDS = {"set", "id", "sample", "index", "action_order", "constraint_order", "served_model", "output",
                 "latency_ms", "attempts", "error", "prompt"}
# The output of label() is far too big for a size check on every row: the prompt echoed back as the answer is
# megabytes, a real judgment a few kilobytes
BIG = 2 * 1024 * 1024
SMALL = 16 * 1024


# ------------------------------------------------------------------------------------------ sampling

def call(teacher: LLM, case: MatrixCase) -> dict:
    """The prompt and the output schema of label() for one teacher run, actions in a fresh random order, and the check
    that every value label() would use is usable."""
    actions = [a.id for a in case.action_space]
    constraint_order = [c.id for c in case.constraints]
    # label() draws the action order once per case and uses it for its three runs; the fresh order per run this
    # experiment wants is drawn here, once per call
    shown = random.sample(case.action_space, len(case.action_space))
    prompt = LABEL_PROMPT.format(
        tasks=GOAL_TASK.format(levels=levels_text(case.lang)) + (CONSTRAINTS_TASK if constraint_order else "") + BEST_TASK,
        state=json.dumps(case.state, ensure_ascii=False, indent=2),
        goal=case.goal,
        constraints=constraints_list(case.constraints),
        actions="\n".join(f"- {a.id}: {a.description}" for a in shown),
    )
    output = teacher_output([a.id for a in shown], constraint_order, True)
    n_levels = len(LEVELS[case.lang])

    async def judged() -> dict:
        """label()'s judged(): one run as {"judgments": {action: {...}}, "best": {action: p}}, refused unless every
        value is usable. The struct holds it raw so the line records what the teacher actually returned."""
        result = (await teacher.astructured(prompt, output, temperature=TEMPERATURE)).model_dump(by_alias=True)
        for a, j in result["judgments"].items():
            if normalized(j["goal"], n_levels) is None:
                raise ValueError(f"{a}: goal is not {n_levels} probabilities: {j['goal']}")
            if any(not 0 <= p <= 1 for p in j.get("violations", {}).values()):
                raise ValueError(f"{a}: a violation probability is outside [0, 1]")
        if normalized([result["best"][a] for a in actions], len(actions)) is None:
            raise ValueError(f"best is not a distribution: {result['best']}")
        return result

    return {"judged": judged, "shown": [a.id for a in shown], "constraints": constraint_order}


async def sample(teacher: LLM, case: MatrixCase, index: int, counters: dict) -> dict:
    """One teacher run of a case: retry() around the call, counters of what it took, the raw line either way."""
    spec = call(teacher, case)
    start = time.perf_counter()
    attempts = 0

    async def once():
        nonlocal attempts
        attempts += 1
        return await spec["judged"]()

    output, error = None, None
    try:
        output = await retry(once, attempts=ATTEMPTS)
        if len(json.dumps(output, ensure_ascii=False)) > SMALL:
            error = f"ValueError: answer of {len(json.dumps(output))} chars is far larger than any judgment"
            output = None
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
    latency = (time.perf_counter() - start) * 1000
    counters["calls"] += attempts
    if error is not None:
        counters["retries"] += attempts - 1               # a failed attempt that came after another one
        counters["failed_calls"] += attempts
        print(f"{case.lang} {case.id} #{index}: gave up after {attempts} attempts ({error[:200]})", flush=True)
    else:
        counters["retries"] += attempts - 1
    return {"set": case.lang, "id": case.id, "sample": index, "index": index,
            "action_order": spec["shown"], "constraint_order": spec["constraints"],
            "served_model": teacher.served_model, "output": output, "latency_ms": round(latency, 1),
            "attempts": attempts, "error": error}


def counted(row: dict) -> dict:
    """The row with the campaign counters of its run, derived from its attempts: calls and retries count the attempts
    the run took, and a run that gave up adds all of its attempts as failed calls. read_raw() replaces the line of a
    given-up run when the same run index is made again, so the counters are recomputed rather than trusted from the
    file, and a run that only exists to fill a former failure reads as 1 call / 0 retries."""
    attempts, error = row["attempts"], row["error"]
    return {**row, "calls": attempts, "retries": max(attempts - 1, 0), "failed_calls": attempts if error else 0}


def read_raw(path: Path) -> dict[str, dict[int, dict]]:
    """The last line per (case, run index). A line that is cut off (the tail of an interrupted run after the last
    complete line) is skipped. Lines of the one earlier version, which also recorded the prompt, land under
    "_legacy": they are not runs."""
    rows, legacy = defaultdict(dict), 0
    if not path.exists():
        return rows
    with path.open("rb") as f:
        for line in f:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(row, dict):
                continue
            if LEGACY_FIELDS <= set(row):
                legacy += 1
            elif RAW_FIELDS <= set(row):
                rows[row["id"]][row["sample"]] = counted(row)
    if legacy:
        read_raw.legacy[path.name] = legacy
    return rows


read_raw.legacy = {}


def gave_up() -> dict[tuple[str, str], int]:
    """How often a run gave up in every earlier invocation, keyed by (set, case). A rerun replaces the line of a
    given-up run, so the "gave up" lines of logs/ are the only trace left of it. The id of an en case may itself
    contain a space ("customer service"), so the case is matched by suffix against the test sets."""
    count = Counter()
    for path in sorted(LOGS.glob("*.log")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if m := re.match(r"^(.+?) #(\d+): gave up after", line):
                count[m[1]] += 1
    known = {c.id: name for name, path in SETS.items() for c in load(ROOT / path / "test.jsonl")}
    out = Counter()
    for cid, n in count.items():
        if cid in known:
            out[(known[cid], cid)] += n
        else:
            print(f"gave-up line for an unknown case: {cid!r}", flush=True)
    return out


def valid(rows: dict[int, dict]) -> list[int]:
    return [i for i in range(SAMPLES) if i in rows and rows[i]["error"] is None]


def append_raw(path: Path, row: dict):
    """One line per run, counters included, so every attempt of the experiment adds up from raw/ alone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(counted(row), ensure_ascii=False) + "\n")


def compact(path: Path) -> list[dict]:
    """Rewrite raw/ keeping only the last line per (case, run index) and dropping an output larger than any answer
    label() can give (a bypassed response-length limit reports the whole prompt as the answer). Returns what it
    dropped, for the report."""
    if not path.exists():
        return []
    lines, dropped, kept = path.read_text(encoding="utf-8").splitlines(), [], {}
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not RAW_FIELDS <= set(row):
            continue
        output = row.get("output")
        if output is not None and len(json.dumps(output, ensure_ascii=False)) > BIG:
            dropped.append({k: row.get(k) for k in ("id", "sample", "served_model", "attempts", "error", "latency_ms")}
                           | {"output_chars": len(json.dumps(output, ensure_ascii=False))})
            continue
        kept[(row["id"], row["sample"])] = row
    filled = 0
    for row in kept.values():
        if "calls" not in row:
            row["calls"] = row["attempts"]
            row["retries"] = max(row["attempts"] - 1, 0)
            row["failed_attempts"] = row["attempts"] - 1 if row["error"] is None else row["attempts"]
            filled += 1
    if len(lines) != len(kept) or dropped or filled:
        with path.open("w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in kept.values())
        print(f"{path}: {len(lines)} lines → {len(kept)} ({len(dropped)} too large, {filled} without counters)",
              flush=True)
    return dropped


# ------------------------------------------------------------------------------------------ assessment

def assess(case: MatrixCase, goal: dict, constraints: dict, best: dict) -> Assessment:
    """An Assessment from labels, with MatrixEvaluator.assess's rule: every action that likely breaks a hard constraint
    is excluded, and the choice is the most probable action among the rest, or None when every action is excluded."""
    excluded = {}
    for action in (a.id for a in case.action_space):
        broken = [c.id for c in case.constraints if c.hard and constraints[action][c.id] >= HARD]
        if broken:
            excluded[action] = broken
    feasible = [a.id for a in case.action_space if a.id not in excluded]
    return Assessment(labels=Labels(goal=goal, constraints=constraints, best=best), excluded=excluded,
                      choice=max(feasible, key=best.get) if feasible else None)


def relabel(case: MatrixCase, runs: list[dict]) -> Assessment:
    """The runs averaged exactly the way label() averages them."""
    actions = [a.id for a in case.action_space]
    ids = [c.id for c in case.constraints]
    n_levels = len(LEVELS[case.lang])
    goal = {a: mean([normalized(r["output"]["judgments"][a]["goal"], n_levels) for r in runs]) for a in actions}
    constraints = {a: {c: round(sum(r["output"]["judgments"][a]["violations"][c] for r in runs) / len(runs), 4)
                       for c in ids} for a in actions} if ids else {}
    best = dict(zip(actions, mean([normalized([r["output"]["best"][a] for a in actions], len(actions))
                                   for r in runs])))
    return assess(case, goal, constraints, best)


def single(case: MatrixCase, run: dict) -> Assessment:
    """One run on its own, the probabilities as the teacher gave them."""
    actions = [a.id for a in case.action_space]
    ids = [c.id for c in case.constraints]
    out = run["output"]
    return assess(case,
                  {a: normalized(out["judgments"][a]["goal"], len(LEVELS[case.lang])) for a in actions},
                  {a: {c: float(out["judgments"][a]["violations"][c]) for c in ids} for a in actions} if ids else {},
                  dict(zip(actions, normalized([out["best"][a] for a in actions], len(actions)))))


# ------------------------------------------------------------------------------------------ noise

def expected(dist: list[float]) -> float:
    return sum(i * p for i, p in enumerate(dist))


def noise(cases: list[MatrixCase], runs: dict[str, dict[int, dict]]) -> dict:
    """How far the runs of one case disagree with each other: a property of the teacher, independent of the old
    labels. Pairs of runs: argmax of best, and the expected goal level of every action (0-4)."""
    best, gaps, floor = [], [], []
    for case in cases:
        rows, actions = runs[case.id], [a.id for a in case.action_space]
        n_levels = len(LEVELS[case.lang])
        expected_levels, top = [], []
        for i in range(SAMPLES):
            out = rows[i]["output"]
            expected_levels.append([expected(normalized(out["judgments"][a]["goal"], n_levels)) for a in actions])
            top.append(max(actions, key=lambda a: out["best"][a]))
        for i in range(SAMPLES):
            for j in range(i + 1, SAMPLES):
                best.append(top[i] == top[j])
                gaps += [abs(x - y) for x, y in zip(expected_levels[i], expected_levels[j])]
                floor += [int(x) == int(y) for x, y in zip(expected_levels[i], expected_levels[j])]
    return {"cases": len(cases), "pairs_per_case": SAMPLES * (SAMPLES - 1) // 2,
            "best_argmax_agreement": float(np.mean(best)) if best else None,
            "goal_expected_mae": float(np.mean(gaps)) if gaps else None,
            "goal_expected_n": len(gaps),
            "goal_level_agreement": float(np.mean(floor)) if floor else None}


# ------------------------------------------------------------------------------------------ run

async def sample_sets(args: argparse.Namespace, cases: dict[str, list[MatrixCase]]) -> tuple[dict, dict]:
    """Every missing run of every case, at most --concurrency teacher calls in flight."""
    teachers, served = {}, {}
    for name, cs in cases.items():
        recorded = {c.meta.get("goal_teacher") for c in cs}
        if recorded != {TEACHER}:
            raise SystemExit(f"{name}: the cases record the teachers {recorded}, not {TEACHER!r}")
        teachers[name] = LLM(TEACHER)
        served[name] = [teachers[name].served_model]
        if served[name] != [TEACHER]:
            raise SystemExit(f"{name}: the API serves {served[name]!r} for {TEACHER!r}, which is not the recorded "
                             "teacher; nothing is sampled")
        print(f"{name}: {len(cs)} cases, teacher {TEACHER} → {served[name][0]}", flush=True)

    limit = asyncio.Semaphore(args.concurrency)     # flattens the API client too (litellm), so it caps requests
    # An answer of any size is valid, so rows are only compared against much smaller ones. Once by compact(), and again
    # by read_raw() below, so the sampler only ever works from a complete file
    dropped = [row for name in cases for row in compact(RAW / f"{name}.jsonl")]
    counters = {"per_set": Counter(), "skipped": 0, "calls": 0, "retries": 0, "failed_calls": 0, "pending": 0,
                "compacted": dropped}
    pending = []
    for name, cs in cases.items():
        rows = read_raw(RAW / f"{name}.jsonl")
        for case in cs:
            have = valid(rows.get(case.id, {}))
            counters["skipped"] += len(have)
            for index in range(SAMPLES):
                if index not in have:
                    counters["pending"] += 1
                    pending.append((name, case, index))
    print(f"{len(pending)} teacher runs to make ({counters['skipped']} runs already valid), "
          f"concurrency {args.concurrency}", flush=True)

    done, started = [0], time.perf_counter()

    async def one(name: str, case: MatrixCase, index: int):
        async with limit:
            row = await sample(teachers[name], case, index, counters)
        append_raw(RAW / f"{name}.jsonl", row)
        done[0] += 1
        counters["per_set"][(name, row["error"] is None)] += 1
        if done[0] % 25 == 0 or done[0] == len(pending):
            print(f"  {done[0]}/{len(pending)} runs, {counters['retries']} retries, {counters['failed_calls']} failed, "
                  f"{time.perf_counter() - started:.0f}s", flush=True)

    await asyncio.gather(*(one(*job) for job in pending))
    return served, counters


def build_sets(cases: dict[str, list[MatrixCase]], runs: dict[str, dict[str, dict[int, dict]]]
               ) -> tuple[dict[str, dict[str, dict]], list[MatrixCase], dict]:
    """Every model's result per set, in the shape scripts/benchmark.py writes; plus the cases each was
    scored on (the ones with SAMPLES valid runs) and the incomplete ones."""
    results, scored, partial = {model: {} for model in MODELS}, {}, {}
    for name, cs in cases.items():
        complete = [c for c in cs if len(valid(runs[name].get(c.id, {}))) == SAMPLES]
        partial[name] = [(c.id, len(valid(runs[name].get(c.id, {})))) for c in cs if c.id not in {x.id for x in complete}]
        scored[name] = complete
        if len(complete) < len(cs):
            print(f"{name}: {len(cs) - len(complete)} cases without {SAMPLES} valid runs are left unscored", flush=True)
        for model in MODELS:
            if not complete:
                continue
            start = time.perf_counter()
            assessments = [(relabel(c, [runs[name][c.id][i] for i in range(SAMPLES)]) if model == "teacher-relabel"
                            else single(c, runs[name][c.id][int(model[-1]) - 1])) for c in complete]
            ms = (time.perf_counter() - start) * 1000
            latencies = [runs[name][c.id][i]["latency_ms"] for c in complete for i in range(SAMPLES)]
            results[model][name] = {
                "n_cases": len(complete), **benchmark.score(complete, assessments),
                "latency_ms": {"p50": float(np.percentile(ms, 50)), "p95": float(np.percentile(ms, 95))},
                "teacher_latency_ms": {"p50": float(np.percentile(latencies, 50)),
                                       "p95": float(np.percentile(latencies, 95)), "n": len(latencies)},
                "unscored_cases": [cid for cid, _ in partial[name]],
                "assessments": [{"id": c.id, **a.model_dump()} for c, a in zip(complete, assessments)],
            }
    return results, scored, partial


def environment(served: dict, args: argparse.Namespace) -> dict:
    return {"python": platform.python_version(), "numpy": np.__version__, "torch": torch_version(),
            "device": "none: the teacher is called remotely", "teacher": TEACHER, "served_model": served,
            "temperature": TEMPERATURE, "samples": SAMPLES, "hard_threshold": HARD, "retry_attempts": ATTEMPTS,
            "raw": {name: f"raw/{name}.jsonl" for name in served}, "concurrency": args.concurrency,
            "limit": args.limit or None, "git": git(), "created": time.strftime("%Y-%m-%d %H:%M:%S %Z")}


def torch_version() -> str | None:
    try:
        import torch
        return torch.__version__
    except Exception:
        return None


def git() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


# ------------------------------------------------------------------------------------------ report

def fmt(v, digits: int = 3) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def ci_text(m: dict, key: str = "accuracy") -> str:
    if not m:
        return "–"
    ci = m.get(f"{key}_ci")
    return fmt(m.get(key)) + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")


def mean_sd(values: list[float | None]) -> str:
    v = [x for x in values if x is not None]
    return f"{np.mean(v):.3f} ± {np.std(v, ddof=1):.3f}" if len(v) > 1 else (f"{v[0]:.3f}" if v else "–")


def compute_noise(scored: dict, cases: dict, runs: dict) -> dict[str, dict]:
    return {name: {"n_cases": len(scored[name]), "pairs_per_case": SAMPLES * (SAMPLES - 1) // 2,
                   **{k: v for k, v in noise(scored[name], runs[name]).items() if k not in ("cases",)}}
            for name in cases}


def markdown(args, results, stats, counters, env, sets_meta, scored, noise_, partial,
             case_ids: dict[str, list[MatrixCase]]) -> str:
    title = f"（`--limit {args.limit}`：每集前 {args.limit} 条，冒烟测试）" if args.limit else ""
    out = ["# Teacher 自一致上限（teacher ceiling）", "",
           f"用生成原标签的同一套流程重新标注 test 集，与原标签对照。teacher `{env['teacher']}`，OpenRouter，"
           f"温度 {TEMPERATURE}，每 case {SAMPLES} 次独立采样，每次重新打乱动作顺序，同一 prompt 与输出 schema、"
           f"同样的校验与最多 {ATTEMPTS} 次尝试的重试，取平均。{title}", ""]

    # ------------------------------------------------------------------ conclusion
    out += ["## 结论", ""]
    if results:
        out += ["| 数据 | n | teacher-relabel 决策选对 | 选中违反硬约束 | 单次采样均值 | goal acc | 约束 AUROC | "
                "selection acc |", "|---|---|---|---|---|---|---|---|"]
        rows = []
        for name in sets_meta:
            m, d = results["teacher-relabel"].get(name, {}), results["teacher-relabel"].get(name, {}).get("decision", {})
            rows.append(f"| {name} | {m.get('n_cases', 0)} | {ci_text(d)} | {fmt(d.get('hard_violation_rate'))} | "
                        f"{mean_sd([results[s].get(name, {}).get('decision', {}).get('accuracy') for s in SINGLE])} | "
                        f"{fmt(m.get('goal', {}).get('accuracy'))} | {fmt(m.get('constraints', {}).get('auroc'))} | "
                        f"{ci_text(m.get('selection'))} |")
        out += rows + [""]
        for name in sets_meta:
            d = results["teacher-relabel"].get(name, {}).get("decision")
            per = [results[s][name]["decision"]["accuracy"] for s in SINGLE if name in results[s]]
            if d and per:
                gold = (f"；与原 typed-decisions gold 的一致度 {fmt(d.get('original_gold_accuracy'))}"
                        if d.get("original_gold_accuracy") is not None else "")
                out.append(f"- **{name}**：teacher-relabel 决策选对 **{d['accuracy']:.3f}**"
                           f"（95% CI {d['accuracy_ci'][0]:.3f}–{d['accuracy_ci'][1]:.3f}），单次采样 {mean_sd(per)}{gold}。")
        out += ["- 这就是学生模型在这种标签上能对齐到的上限：即使学生输出与 teacher-relabel 完全相同，与原标签的决策"
                "一致率也只有上面的数字，其余部分是 teacher 自身的采样随机性造成的标签噪声，学生无从学习。", ""]

    # ------------------------------------------------------------------ sampling
    out += ["## 采样", "",
            "| 数据 | case 数 | 有效运行 | 重试 | 首次尝试即成功 | 重跑补齐的运行 | 不完整 case | 无有效运行 case | "
            "单次调用 p50 / p95 |", "|---|---|---|---|---|---|---|---|---|"]
    for name, s in stats.items():
        out.append(f"| {name} | {s['cases']} | {s['valid']} | {s['retries']} | {s['valid'] - s['retries']} | "
                   f"{s['refilled']} | {len([x for x in partial[name] if x[1] > 0])} | "
                   f"{len([x for x in partial[name] if x[1] == 0])} | "
                   f"{fmt(s['latency']['p50'], 0)} / {fmt(s['latency']['p95'], 0)} ms |")
    total = {k: sum(s[k] for s in stats.values()) for k in ("calls", "refilled", "valid")}
    per_set = "，".join("{} {} 次".format(name, s["calls"]) for name, s in stats.items())
    out += ["",
            f"`raw/` 里的采样记录合计 **{total['calls']} 次调用**：{per_set}；其中 {total['calls'] - total['valid']} 次是同一次运行内的重试"
            f"（第 2–4 次尝试），{total['valid'] - total['refilled']} 个运行首次尝试即成功，"
            f"{total['refilled']} 个运行是**重跑补齐**的"
            f"（之前那次运行 4 次尝试全部失败，同一命令重跑同一运行编号后成功，只留下 `raw/` 里的成功记录，"
            f"失败记录见 `logs/full.log` 的 `gave up after 4 attempts`）；每个失败的运行额外用掉 4 次调用，"
            f"真实调用总数约为 {total['calls']} + 4×{total['refilled']} = {total['calls'] + 4 * total['refilled']}。"
            f"`raw/` 覆盖 {sum(s['cases'] - len(partial[name]) for name, s in stats.items())}"
            f"/{sum(s['cases'] for s in stats.values())} 个 case，每个 case 3 次有效采样。", ""]
    out += ["| 数据 | served_model（全部有效运行） |", "|---|---|"]
    for name, s in stats.items():
        out.append(f"| {name} | {', '.join(f'`{k}` × {v}' for k, v in s['served'].items())} |")
    out += ["", "重试沿用 `scripts/build_data.py` 的 `retry()`：最多 4 次尝试（含首次），退避 1s、2s、4s。"
                "原始每次运行一条记录，写在 `raw/{zh,en}.jsonl`，包括 `action_order`（该次展示的动作顺序）、"
                "`served_model`、完整输出、`latency_ms`（含重试的总耗时）、`attempts` 和 `error`。", ""]

    # ------------------------------------------------------------------ metrics
    if results:
        out += ["## 决策（硬约束过滤后的最终选择）", "",
                "| 模型 | 数据 | n | 选对 ↑ | 选中违反硬约束 ↓ | 全部排除 | 原 gold 选对 ↑ |", "|---|---|---|---|---|---|---|"]
        for model in MODELS:
            for name in sets_meta:
                d = results[model].get(name, {}).get("decision")
                if d:
                    out.append(f"| {model} | {name} | {d['n']} | {ci_text(d)} | {fmt(d.get('hard_violation_rate'))} | "
                               f"{fmt(d.get('abstain_rate'))} | {ci_text(d, 'original_gold_accuracy')} |")
        out += ["", "## goal（目标达成五档）", "",
                "| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | MAE ↓ | 排序 ↑ |", "|---|---|---|---|---|---|---|---|"]
        for model in MODELS:
            for name in sets_meta:
                m = results[model].get(name, {}).get("goal")
                if m:
                    out.append(f"| {model} | {name} | {m['n']} | {ci_text(m)} | {fmt(m['kl'])} | {fmt(m['brier'])} | "
                               f"{fmt(m['mae'])} | {fmt(m['ranking'])} |")
        out += ["", "## constraints（约束违反）", "",
                "| 模型 | 数据 | n | Accuracy ↑ | Brier ↓ | ECE ↓ | AUROC ↑ | 硬约束违反召回 ↑ |",
                "|---|---|---|---|---|---|---|---|"]
        for model in MODELS:
            for name in sets_meta:
                m = results[model].get(name, {}).get("constraints")
                if m:
                    out.append(f"| {model} | {name} | {m['n']} | {fmt(m['accuracy'])} | {fmt(m['brier'])} | "
                               f"{fmt(m['ece'])} | {fmt(m['auroc'])} | {fmt(m['hard_violation_recall'])} |")
        out += ["", "## selection（选择头，未过滤）", "",
                "| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ |", "|---|---|---|---|---|---|---|"]
        for model in MODELS:
            for name in sets_meta:
                m = results[model].get(name, {}).get("selection")
                if m:
                    out.append(f"| {model} | {name} | {m['n']} | {ci_text(m)} | {fmt(m['kl'])} | {fmt(m['brier'])} | "
                               f"{fmt(m['ece'])} |")

        out += ["", "## 单次采样（s1/s2/s3）：均值 ± 标准差", "",
                "| 数据 | 决策选对 | 选中违反硬约束 | goal accuracy | 约束 AUROC | selection accuracy | 原 gold 选对 |",
                "|---|---|---|---|---|---|---|"]
        for name in sets_meta:
            cells = [mean_sd([results[s].get(name, {}).get("decision", {}).get(k) for s in SINGLE])
                     for k in ("accuracy",)]
            cells.append(mean_sd([results[s].get(name, {}).get("decision", {}).get("hard_violation_rate") for s in SINGLE]))
            cells.append(mean_sd([results[s].get(name, {}).get("goal", {}).get("accuracy") for s in SINGLE]))
            cells.append(mean_sd([results[s].get(name, {}).get("constraints", {}).get("auroc") for s in SINGLE]))
            cells.append(mean_sd([results[s].get(name, {}).get("selection", {}).get("accuracy") for s in SINGLE]))
            cells.append(mean_sd([results[s].get(name, {}).get("decision", {}).get("original_gold_accuracy") for s in SINGLE]))
            out.append(f"| {name} | " + " | ".join(cells) + " |")
        out += ["", "每次采样单独打分：没有平均，单次的 goal/best 不经归一化直接使用（Assessment 用概率），"
                    "所以单次与平均的差距既包含采样随机性，也包含平均带来的平滑收益。", ""]

        out += ["## teacher-single 与 teacher-relabel 并排", "",
                "| 数据 | 指标 | single 均值 | relabel |", "|---|---|---|---|"]
        for name in sets_meta:
            for task, key, label in (("decision", "accuracy", "决策选对"), ("decision", "hard_violation_rate", "选中违反硬约束"),
                                     ("goal", "accuracy", "goal accuracy"), ("constraints", "auroc", "约束 AUROC"),
                                     ("selection", "accuracy", "selection accuracy")):
                vals = [results[s].get(name, {}).get(task, {}).get(key) for s in SINGLE]
                out.append(f"| {name} | {label} | {np.mean([v for v in vals if v is not None]):.3f} | "
                           f"{fmt(results['teacher-relabel'].get(name, {}).get(task, {}).get(key))} |")
        out.append("")

    # ------------------------------------------------------------------ noise
    out += ["## 纯噪声指标（3 次新采样两两之间，与旧标签无关）", "",
            "| 数据 | case 数 | 对数/case | best argmax 一致率 | goal 期望档位平均绝对差 | 档位一致率 | "
            "比较的行动次数 |", "|---|---|---|---|---|---|---|"]
    for name in sets_meta:
        n = noise_.get(name)
        if n:
            out.append(f"| {name} | {n['n_cases']} | {n['pairs_per_case']} | {fmt(n['best_argmax_agreement'])} | "
                       f"{fmt(n['goal_expected_mae'])} | {fmt(n['goal_level_agreement'])} | {n['goal_expected_n']} |")
    out += ["", "goal 期望档位 = Σ i·P(level i)，0–4；平均绝对差是同一行动两次采样的期望档位之差的绝对值平均。"
                "档位一致率 = 同一行动两次采样的期望档位取整（floor，即落在哪一档）相同的比例。"
                "best argmax 一致率低说明 teacher 在同一 case 上会把不同行动选为最优；"
                "这是任何学生模型都无法从单份标签学到的部分。", ""]

    # ------------------------------------------------------------------ latency
    if results:
        out += ["## 延迟", "",
                "| 模型 | 数据 | 每个 case 的 Assessment 构造+打分（ms，benchmark 口径） | 单次 teacher 调用 p50 / p95（ms） |",
                "|---|---|---|---|"]
        for model in MODELS:
            for name in sets_meta:
                m = results[model].get(name, {})
                if m:
                    per_case = m["latency_ms"]["p50"] / m["n_cases"]
                    out.append(f"| {model} | {name} | {fmt(per_case, 2)} | "
                               f"{fmt(m['teacher_latency_ms']['p50'], 0)} / {fmt(m['teacher_latency_ms']['p95'], 0)} |")
        out += ["", "teacher 调用延迟是该集全部采样的 p50/p95（含重试与退避的总耗时）；老师单次输出 3–12k tokens，"
                    "并由网关流式返回，所以单次调用在 1–4 分钟量级。", ""]

    # ------------------------------------------------------------------ incomplete
    if results and all(results["teacher-relabel"].get(n, {}).get("decision", {}).get("abstain_rate") == 0
                       for n in sets_meta):
        out += ["（所有 teacher 模型在 zh 上都没有把整个行动空间排除的情况；en 上的 全部排除 比例见决策表。）", ""]

    out += ["## 未完成的 case", ""]
    left = {n: xs for n, xs in partial.items() if xs}
    if not left:
        out.append("无：每个 case 都有 3 次有效采样。")
    else:
        out.append("| 数据 | case | 有效运行数 |")
        out.append("|---|---|---|")
        for name, xs in left.items():
            for cid, n in xs:
                out.append(f"| {name} | `{cid}` | {n} |")
        out.append("")
        out.append("这些 case 采样不齐，**不参与打分**（报告里的 n 只含采样齐全的 case）；`raw/` 保留已有记录，"
                   "重跑同一命令会补上缺的运行。")
    out.append("")
    if counters.get("compacted"):
        sets_of = {c.id: name for name in sets_meta for c in case_ids[name]}
        out += ["## 被丢弃的运行记录", "",
                "以下运行的输出异常大（整个 prompt 被当成了回答，网关绕过了响应长度限制），不是有效的判断，已从 `raw/` 丢弃，"
                "并按失败重采：", "", "| 数据 | case | 采样序号 | served_model | 输出字符数 | attempts | 耗时 ms |",
                "|---|---|---|---|---|---|---|"]
        for row in counters["compacted"]:
            out.append(f"| {sets_of.get(row['id'], '–')} | `{row['id']}` | {row['sample']} | `{row['served_model']}` | "
                       f"{row.get('output_chars', '–')} | {row['attempts']} | {fmt(row['latency_ms'], 0)} |")
        out.append("")

    # ------------------------------------------------------------------ notes
    out += ["## 口径", "",
            "- teacher-relabel：3 次新采样完全按 `label()` 的方式合并——goal 每次先归一化再取均值，constraints 取均值，"
            "best 每次先归一化再取均值，四舍五入到 4 位；然后与原 test 标签比较。",
            "- teacher-single-sN：第 N 次采样单独作为概率，不平均。",
            "- Assessment：labels.goal / constraints / best 为上述概率；excluded = 任一硬约束违反概率 ≥ 0.5 的行动"
            f"（阈值 {HARD}，同 `MatrixEvaluator.assess`）；choice = 未被排除的行动中 best 最大者，全部被排除时为 null。",
            "- 所有指标由 `scripts/benchmark.py` 的 `score()` 计算（未改动），准确率的方括号为 95% bootstrap 区间。",
            "- en 的 `original_gold_accuracy`：与 typed-decisions 原有 action/disposition gold（`meta.previous_best`）的 "
            "argmax 一致率。它与 teacher 标签的一致度是原 gold 与 teacher 的水平，不是本实验新采样引入的差异。",
            "- `results/<模型>.json` 的结构与 `scripts/benchmark.py` 写出的完全相同（`model` / `sets` / `environment`），"
            "额外附带 `teacher_latency_ms`、`unscored_cases` 两个字段；把它们复制到 `experiments/krino-matrix-v1-mmbert/results/` 后，"
            "主实验的 benchmark 报告会把它们列为额外的模型。", ""]
    return "\n".join(out)


# ------------------------------------------------------------------------------------------ main

async def main(args: argparse.Namespace):
    cases = {}
    for name in args.sets:
        cs = load(ROOT / SETS[name] / "test.jsonl")
        cases[name] = cs[:args.limit] if args.limit else cs
    runs = {name: read_raw(RAW / f"{name}.jsonl") for name in cases}
    counters = {"per_set": Counter(), "skipped": 0, "calls": 0, "retries": 0, "failed_calls": 0, "pending": 0,
                "compacted": []}
    served = {}
    for name, cs in cases.items():
        recorded = {c.meta.get("goal_teacher") for c in cs}
        if recorded != {TEACHER}:
            raise SystemExit(f"{name}: the cases record the teachers {recorded}, not {TEACHER!r}")

    if not args.report_only:
        served, counters = await sample_sets(args, cases)
    else:
        for name in cases:
            print(f"{name}: report only, no teacher calls", flush=True)

    # Everything below works from raw/ alone, so a --report-only rerun reproduces the same results
    runs = {name: read_raw(RAW / f"{name}.jsonl") for name in cases}
    results, scored, partial = build_sets(cases, runs)
    for name in cases:
        served.setdefault(name, [])
        served[name] = sorted({r["served_model"] for cid in runs[name] for r in runs[name][cid].values()}
                              | set(served[name]))
    stats, given = {}, gave_up()
    for name, cs in cases.items():
        rows = [r for c in cs for r in runs[name].get(c.id, {}).values()]
        good = [r for r in rows if r["error"] is None]
        stats[name] = {"cases": len(cs), "valid": len(good), "failed": len(rows) - len(good),
                       "calls": sum(r["calls"] for r in rows), "retries": sum(r["retries"] for r in rows),
                       "refilled": sum(given.get((name, c.id), 0) for c in cs),   # runs a rerun had to fill
                       "served": Counter(r["served_model"] for r in rows),
                       "latency": {"p50": float(np.percentile([r["latency_ms"] for r in good], 50)) if good else None,
                                   "p95": float(np.percentile([r["latency_ms"] for r in good], 95)) if good else None}}
    noise_ = compute_noise(scored, cases, runs)
    env = environment(served, args)

    RESULTS.mkdir(parents=True, exist_ok=True)
    for model, by_set in results.items():
        (RESULTS / f"{model}.json").write_text(
            json.dumps({"model": model, "sets": by_set, "environment": env}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        for name, m in by_set.items():
            print(f"{model} {name}: " + "  ".join(
                f"{t} {fmt(m[t]['accuracy'])}" for t in ("decision", "goal", "constraints", "selection") if t in m),
                flush=True)
    (RESULTS / "report.md").write_text(
        markdown(args, results, stats, counters, env, list(cases), scored, noise_, partial, cases), encoding="utf-8")
    print(f"wrote {RESULTS / 'report.md'}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--concurrency", type=int, default=16, help="teacher calls in flight (default 16)")
    parser.add_argument("--limit", type=int, default=0, help="first N cases of each set only, for a trial run")
    parser.add_argument("--sets", nargs="+", default=list(SETS), choices=list(SETS), help="which test sets")
    parser.add_argument("--report-only", action="store_true", help="rescore raw/ and rebuild report.md, no teacher calls")
    asyncio.run(main(parser.parse_args()))
