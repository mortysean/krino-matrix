"""LLM zero-shot baseline for Krino Matrix: one deepseek flash call per decision case, the usage of a deployed system
that asks a large model instead of running MatrixEvaluator's single forward pass.

    python experiments/llm-zeroshot/run.py --limit 3          # trial run on the first 3 cases of each set
    python experiments/llm-zeroshot/run.py                    # every test case of zh and en
    python experiments/llm-zeroshot/run.py --sets zh          # one set (zh or en, or name=dir)
    python experiments/llm-zeroshot/run.py --probe --latency-probe 50    # only the concurrency-1 latency probe
    python experiments/llm-zeroshot/run.py --cost --cost-cases 100       # only the token / cost measurement

Per case the model (LLM_DEFAULT of .env, temperature 0) is asked once, with the teacher's own prompt and output
schema from scripts/build_data.py (LABEL_PROMPT, GOAL_TASK, CONSTRAINTS_TASK, BEST_TASK, teacher_output,
levels_text, constraints_list, normalized), so what differs from the labels is the sampling, not the instructions.
The action order is shuffled as in label(), with a fixed seed, and recorded with every case. An answer that takes
longer than ATTEMPT_TIMEOUT, whose goal is not 5 probabilities summing to 1, whose violation probability is outside
[0, 1], or whose best is not a distribution is rejected and the model asked again, at most MAX_ATTEMPTS times in
all -- label()'s own rule, on the same schema. Best may leave some actions at 0. The model runs with reasoning off
(REASONING, MAX_TOKENS), a deployment caller's own settings, which this baseline measures as deployed. A case that
still fails is recorded as failed (no assessment), never dropped, and counted in the report. The length cap is not part of the rejection rule: it ends
a run-on answer sooner (see MAX_TOKENS), and is the caller's own deployment setting, as the timeout is.

Answers are appended to raw/<set>.jsonl as they arrive, so an interrupted run continues where it stopped: a case
whose latest record is an error is asked again on the next run, a successful one is kept (delete its line, or the
file, to ask again). Wall-clock milliseconds and the attempt count are recorded per case, but not tokens:
LLM.astructured returns only the parsed object. Tokens and the latency of a single call come from an audit of the
HTTP answers (the Auditor below, which wraps the HTTP transport and never krino/llm.py). The first
--latency-probe cases of each set are asked one call at a time for the latency_ms of the results, free of queueing,
and --cost-cases cases at --concurrency measure the tokens, delays and price of one call as deployed. A probed call
is not retried, so each is a clean single call.

The answers become assessments in the shape MatrixEvaluator.assess returns -- labels, excluded (every action whose
violation probability of a hard constraint reaches 0.5), choice (the most probable action among the rest, the same
rule as MatrixEvaluator.assess) -- and are scored by scripts/benchmark.py's score(), imported unchanged.
Outputs, under experiments/llm-zeroshot/:
  raw/<set>.jsonl                     every case: shown order, attempt count, wall-clock ms, assessment or error
  results/llm-zeroshot-flash.json     {"model", "sets": {set: {n_cases, **score(), latency_ms, assessments}}}
  results/probe.jsonl                 the concurrency-1 probe: per case, its calls' tokens and latency
  results/cost.jsonl                  the deployment-concurrency probe, same fields
  results/audit.jsonl                 one line per HTTP answer of the run that asked the cases: tokens, ms
  results/audit-cost.jsonl            the same for the cost probe
  results/report.md                   written by report.py from the files above
"""
import argparse
import asyncio
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
import litellm
import numpy as np

from krino.matrix import Labels, load
from krino.evaluator import Assessment
from scripts.build_data import (BEST_TASK, CONSTRAINTS_TASK, GOAL_TASK, LABEL_PROMPT, constraints_list,
                                        levels_text, normalized, teacher_output)
from krino.llm import LLM
from scripts.benchmark import score
from litellm.llms.custom_httpx.aiohttp_transport import LiteLLMAiohttpTransport

EXP = ROOT / "experiments/llm-zeroshot"
SETS = {"zh": ROOT / "data/krino_matrix/zh", "en": ROOT / "data/krino_matrix/en"}
MODEL = "llm-zeroshot-flash"
TEACHER = "deepseek/deepseek-v4.1-flash-1017"   # the version recorded in meta.*_teacher of data/krino_matrix
MAX_ATTEMPTS = 4            # one call and up to three retries
ORDER_SEED = 0
HARD = 0.5
CONCURRENCY = 16
PROBE = 50                  # cases per set in the latency probe
COST_CASES = 100            # cases per set at full concurrency for the token / cost measurement
# A deployment caller's own settings, not part of the evaluation. Left to reason at its default depth, deepseek flash
# thinks through reasoning tokens beyond any cap, and 6k-10k of text tokens on this prompt, almost never closing the
# JSON (3 of 3 test cases truncated at max_tokens 4000, retried); a caller asking for a structured judgement turns
# that off. The cap only bounds the answer; whether the answer is usable is judged by `checked`. Measured on three
# cases: reasoning none 5-9 s, low 37-51 s, medium still 52 s on the first case.
MAX_TOKENS = 4000
REASONING = {"effort": "none"}
ATTEMPT_TIMEOUT = 120       # seconds one answer may take before the attempt is abandoned
CROSS_ATTEMPT = 300         # seconds one case may take in all, retries included


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def action_order(case) -> list[str]:
    """The order the model sees the actions in: the same ids on every run."""
    ids = [a.id for a in case.action_space]
    return random.Random(f"{ORDER_SEED}:{case.id}").sample(ids, len(ids))


def prompt(case, shown: list[str]) -> str:
    by_id = {a.id: a for a in case.action_space}
    return LABEL_PROMPT.format(
        tasks=GOAL_TASK.format(levels=levels_text(case.lang))
        + (CONSTRAINTS_TASK if case.constraints else "") + BEST_TASK,
        state=json.dumps(case.state, ensure_ascii=False, indent=2),
        goal=case.goal,
        constraints=constraints_list(case.constraints),
        actions="\n".join(f"- {a}: {by_id[a].description}" for a in shown),
    )


async def retried(make, attempts: int, deadline: float) -> dict:
    """scripts.build_data.retry -- ask again after an unusable answer or a failure, with a growing pause, at
    most `attempts` times -- but with a total deadline instead of a deadline per attempt."""
    for attempt in range(attempts):
        try:
            return await make()
        except Exception as e:
            if attempt == attempts - 1 or time.perf_counter() > deadline:
                raise
            print(f"  retrying after {type(e).__name__}: {' '.join(str(e).split())[:160]}", flush=True)
            await asyncio.sleep(2 ** attempt)


class BadAnswer(ValueError):
    """The model answered, but not with something usable."""


def unusable(error: str) -> bool:
    """Whether a failed decision failed on the model's answer (parsing, validation), not on the call itself."""
    return error.startswith(("BadAnswer:", "ValidationError:", "ValueError: Output truncated"))


def checked(case, shown: list[str], result: dict) -> Assessment:
    """The answer as the assessment MatrixEvaluator.assess would return, refused unless every value is usable.

    The rule is label()'s: every action judged, its goal 5 probabilities summing to 1, every violation probability in
    [0, 1], and best a distribution. best is the one place the schema does not decide: under structured output the
    model may leave actions out of its best object, or give them 0 (a clear choice the teacher itself often makes), so
    a missing action counts as 0, and adding 0 does not change a distribution. Refusing that would reject the answer
    label() accepts and put the two rules of the same task out of step."""
    judgments, best = result.get("judgments") or {}, result.get("best")
    if not isinstance(judgments, dict) or set(judgments) != set(shown):
        raise BadAnswer(f"judgments do not cover every action: {sorted(judgments)}")
    if not isinstance(best, dict) or not set(best) <= set(shown):
        raise BadAnswer(f"best names what is not an action: {best}")
    best = {a: best.get(a, 0) for a in shown}
    n_levels = len(levels_text(case.lang).splitlines())
    goal, violations = {}, {}
    for a in shown:
        j = judgments[a] if isinstance(judgments[a], dict) else {}
        dist = normalized(j.get("goal") or [], n_levels)
        if dist is None:
            raise BadAnswer(f"{a}: goal is not {n_levels} probabilities summing to 1: {j.get('goal')}")
        goal[a] = dist
        per = j.get("violations") or {}
        if set(per) != {c.id for c in case.constraints}:
            raise BadAnswer(f"{a}: violations do not cover every constraint: {sorted(per)}")
        if any(not isinstance(p, (int, float)) or not 0 <= p <= 1 for p in per.values()):
            raise BadAnswer(f"{a}: a violation probability is outside [0, 1]: {per}")
        violations[a] = {c: float(p) for c, p in per.items()}
    selection = normalized([best[a] for a in shown], len(shown))
    if selection is None:
        raise BadAnswer(f"best is not a distribution: {best}")
    labels = Labels(goal=goal, constraints=violations, best=dict(zip(shown, selection)))
    excluded = {a: [c.id for c in case.constraints if c.hard and violations[a][c.id] >= HARD]
                for a in shown if any(c.hard and violations[a][c.id] >= HARD for c in case.constraints)}
    feasible = [a for a in shown if a not in excluded]
    choice = max(feasible, key=labels.best.get) if feasible else None
    return Assessment(labels=labels, excluded=excluded, choice=choice)


async def ask(llm: LLM, case, again: bool = True) -> dict:
    """One deployment decision: one call, plus retries while the answer is unusable unless `again` is False (the
    probes). Only wall-clock time and the attempt count are observable through astructured. One case gets
    CROSS_ATTEMPT seconds in all (a deployer gives up on it then, rather than stack retries), and an attempt that has
    not answered within ATTEMPT_TIMEOUT is abandoned and counted as a failed attempt."""
    shown = action_order(case)
    text = prompt(case, shown)
    output = teacher_output(shown, [c.id for c in case.constraints], True)
    attempts, first = 0, time.perf_counter()

    async def once() -> dict:
        nonlocal attempts
        attempts += 1
        call = llm.astructured(text, output, temperature=0, max_tokens=MAX_TOKENS, reasoning=REASONING)
        return (await asyncio.wait_for(call, min(ATTEMPT_TIMEOUT, max(deadline - time.perf_counter(), 1.0)))
                ).model_dump(by_alias=True)

    deadline = first + CROSS_ATTEMPT
    try:
        answer = await (retried(once, attempts=MAX_ATTEMPTS, deadline=deadline) if again else once())
        assessment = checked(case, shown, answer)
        record = {"id": case.id, "shown": shown, "attempts": attempts, "assessment": assessment.model_dump()}
    except Exception as e:
        # A retried case whose last attempt succeeded keeps that answer; a failed one carries only the error
        record = {"id": case.id, "shown": shown, "attempts": attempts, "error": f"{type(e).__name__}: {str(e)[:800]}"}
    record["latency_ms"] = round((time.perf_counter() - first) * 1000, 1)
    record["prompt_sha256"] = sha256(text)      # the prompt is a function of the case; it is not copied into raw/
    return record


def read_raw(path: Path) -> dict[str, dict]:
    """The latest record of every case in an append-only raw file."""
    records = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["id"]] = record
    return records


def append(path: Path, record: dict):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def collect(llm: LLM, name: str, cases, concurrency: int) -> dict[str, dict]:
    """Ask every case not yet answered at `concurrency`; then, at one call at a time, the cases that failed (a case
    failed at concurrency 16 mostly because the endpoint slowed down under load)."""
    path = EXP / "raw" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    todo = [c for c in cases if c.id not in read_raw(path)]
    done = failed = 0
    lock = asyncio.Lock()       # several answers land at once; opening the file per answer interleaves their lines

    async def one(case, semaphore):
        nonlocal done, failed
        async with semaphore:
            record = await ask(llm, case)
        async with lock:
            append(path, record)
            done += 1
            failed += "error" in record
            if done % 25 == 0 or done == len(todo):
                print(f"  {name}: {done}/{len(todo)} done, {failed} failed", flush=True)

    if todo:
        print(f"{name}: {len(todo)} cases to ask, concurrency {concurrency}", flush=True)
        semaphore = asyncio.Semaphore(concurrency)
        await asyncio.gather(*(one(c, semaphore) for c in todo))
    failed_cases = [c for c in cases if "error" in read_raw(path).get(c.id, {})]
    if failed_cases:
        print(f"{name}: {len(failed_cases)} failed cases asked again, one at a time", flush=True)
        for i, case in enumerate(failed_cases):
            record = await ask(llm, case)
            append(path, record)
            print(f"  {name}: again {i + 1}/{len(failed_cases)}: "
                  f"{'still failed' if 'error' in record else 'answered'}", flush=True)
    return read_raw(path)


def unanswered(case) -> Assessment:
    """A stand-in for a case the model has no usable answer for. score() pairs every case with an assessment, and
    indexes the prediction by the gold action ids, so a case without labels would break it; this has all three
    labels and no choice, is scored as a guess (uniform goal and best, 0.5 per constraint) and counted as broken in
    the decision's hard_violation_rate. It is never counted as an answered case in report.md, which reads the raw
    records for the failures."""
    ids = [a.id for a in case.action_space]
    return Assessment(labels=Labels(
        goal={a: [1 / len(levels_text(case.lang).splitlines())] * len(levels_text(case.lang).splitlines()) for a in ids},
        constraints={a: {c.id: 0.5 for c in case.constraints} for a in ids} if case.constraints else {},
        best={a: 1 / len(ids) for a in ids}), excluded={}, choice=None)


def assemble(cases, records: dict[str, dict]) -> tuple[list[Assessment], list[dict], list[dict]]:
    """Assessments in test-file order, and the failed and the retried cases. A case with no record has no answer."""
    assessments, failed, retried = [], [], []
    for case in cases:
        record = records.get(case.id)
        if record is None or "error" in (record or {}):
            failed.append({"id": case.id, "attempts": (record or {}).get("attempts", 0),
                           "error": (record or {}).get("error", "not asked")})
            assessments.append(unanswered(case))
        else:
            assessments.append(Assessment.model_validate(record["assessment"]))
            if record["attempts"] > 1:
                retried.append({"id": case.id, "attempts": record["attempts"]})
    return assessments, failed, retried


# ---------------------------------------------------------------------------------------------- HTTP audit records

class Auditor:
    """Records what LLM does not report: one line per HTTP answer of a chat completion, keyed by the request's first
    user message, so the prompt tokens, the completion tokens (a retry is its own call) and the wait of every single
    call are visible. litellm sends its requests through LiteLLMAiohttpTransport.handle_async_request, so that method
    is wrapped for the duration; krino/llm.py is not touched. Records go to `path` when one is set, and are kept
    in memory by key either way."""

    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self):
        self.path: Path | None = None
        self.records: dict[str, list[dict]] = {}
        self.original = LiteLLMAiohttpTransport.handle_async_request

    def __enter__(self) -> "Auditor":
        async def handle(transport, request):
            if not str(request.url).startswith(self.URL):
                return await self.original(transport, request)
            body = json.loads(request.content)
            key = sha256(body["messages"][0]["content"])
            start = time.perf_counter()
            try:
                response = await self.original(transport, request)
                content = b"".join([chunk async for chunk in response.aiter_raw()])
            except Exception as e:
                self.add(key, {"error": f"{type(e).__name__}: {str(e)[:300]}",
                               "ms": (time.perf_counter() - start) * 1000})
                raise
            usage, finish, model = {}, None, None
            for line in content.decode("utf-8", "replace").splitlines():
                if line.startswith("data: ") and line[6:].strip() not in ("", "[DONE]"):
                    chunk = json.loads(line[6:])
                    model = model or chunk.get("model")
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        finish = choice.get("finish_reason") or finish
            self.add(key, {"http_status": response.status_code, "served_model": model, "finish_reason": finish,
                           "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                           "ms": (time.perf_counter() - start) * 1000})
            return httpx.Response(response.status_code, headers=response.headers, content=content, request=request)

        LiteLLMAiohttpTransport.handle_async_request = handle
        return self

    def __exit__(self, *exc):
        LiteLLMAiohttpTransport.handle_async_request = self.original

    def add(self, key: str, record: dict):
        record = {"key": key, **record}
        if self.path is not None:
            append(self.path, record)
        self.records.setdefault(key, []).append(record)


auditor: Auditor


async def probe(llm: LLM, name: str, cases, count: int, concurrency: int, path: Path, must_pass: bool) -> None:
    """Ask the first `count` cases at `concurrency` at a time -- for the latency (concurrency 1) or for the tokens and
    cost (the deployment concurrency) -- without retrying a call, and log every case with its wall clock and the
    single calls behind it."""
    count = min(count, len(cases))
    if not count:
        return
    # This set's earlier probe is replaced, so the file holds one probe per set, not every attempt at one
    if path.exists():
        kept = [line for line in path.read_text(encoding="utf-8").splitlines() if json.loads(line).get("set") != name]
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
    semaphore = asyncio.Semaphore(concurrency)
    done = 0
    lock = asyncio.Lock()

    async def one(case):
        nonlocal done
        async with semaphore:
            key = sha256(prompt(case, action_order(case)))
            start = len(auditor.records.get(key, []))
            record = await ask(llm, case, again=False)
        calls = auditor.records.get(key, [])[start:]
        async with lock:
            append(path, {"set": name, "id": case.id, "concurrency": concurrency, **record, "calls": calls})
            done += 1
            if done % 10 == 0 or done == count:
                print(f"  {path.stem} {name} @ {concurrency}: {done}/{count}", flush=True)
        # An unusable answer is still a real single call and its latency counts; a timeout, a network error or a 4xx
        # leaves a case without a latency, and then the probe stops rather than report one with a hole in it
        if must_pass and "error" in record and not unusable(record["error"]):
            raise SystemExit(f"latency probe call failed on {case.id}: {record['error'][:300]}; rerun --probe")

    await asyncio.gather(*(one(c) for c in cases[:count]))


def percentiles(values: list[float]) -> dict:
    return {"p50": float(np.percentile(values, 50)), "p95": float(np.percentile(values, 95))} if values else {}


def probe_latency(name: str) -> dict:
    """p50 / p95 of the decision wall clock of the concurrency-1 probe of a set."""
    path = EXP / "results" / "probe.jsonl"
    if not path.exists():
        return {}
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]
    return percentiles([r["latency_ms"] for r in lines if r.get("set") == name and r.get("concurrency") == 1])


# ---------------------------------------------------------------------------------------------------------- main

async def main(args) -> dict:
    # Outbound traffic goes through HTTPS_PROXY, which LLM needs. The NO_PROXY of this environment lists "[::1]",
    # which httpx cannot parse (an InvalidURL for "[::1]:1") and which breaks LLM.served_model's httpx.post; "::1"
    # says the same to httpx.
    for key in ("NO_PROXY", "no_proxy"):
        if "[::1]" in os.environ.get(key, ""):
            os.environ[key] = ",".join(p for p in os.environ[key].split(",") if p.strip() != "[::1]")
    # litellm fetches its model cost table from GitHub in a background thread, which the proxy stalls for minutes and
    # which keeps the interpreter alive at exit; the price here comes from the OpenRouter models endpoint instead,
    # and the one failed fetch it still logs is not worth a line per run
    litellm.model_cost = {}
    logging.getLogger("LiteLLM").addFilter(lambda record: "model cost map" not in record.getMessage())

    sets = {}
    for s in args.sets:
        name, _, directory = s.partition("=")
        if name not in SETS:
            raise SystemExit(f"unknown set {name!r}; sets: {', '.join(SETS)}")
        sets[name] = ROOT / directory if directory else SETS[name]

    llm = LLM()
    print(f"{llm.model} → {llm.served_model}", flush=True)
    results_dir = EXP / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    global auditor
    with Auditor() as auditor:
        # The audit of a probe is written next to that probe's cases (probe.jsonl / cost.jsonl); a run that asks
        # cases writes audit.jsonl, of this run and not of every run before it
        probe_only = args.probe or args.cost
        auditor.path = None if args.no_audit else results_dir / (
            "audit-cost.jsonl" if args.cost and not args.probe else "audit.jsonl")
        if auditor.path is not None and not probe_only:
            auditor.path.unlink(missing_ok=True)
        # The sets probe at the same time; a call at concurrency 1 is still one call at a time, so its latency is its
        # own, and the two probes do not add minutes to each other
        if args.probe:
            await asyncio.gather(*(probe(llm, name, load(sets[name] / "test.jsonl"), args.latency_probe, 1,
                                         results_dir / "probe.jsonl", True) for name in sets))
        if args.cost:
            await asyncio.gather(*(probe(llm, name, load(sets[name] / "test.jsonl"), args.cost_cases,
                                         args.concurrency, results_dir / "cost.jsonl", False) for name in sets))
        if args.probe or args.cost:
            return {}

    results = {}
    for name in sets:
        # Scored on every case of the set, in test-file order; a case the run did not reach has no answer. --limit
        # only narrows what is asked, so a trial run and the full run share one raw file.
        cases = load(sets[name] / "test.jsonl")
        records = await collect(llm, name, cases[:args.limit] if args.limit else cases, args.concurrency)
        assessments, failed, retried = assemble(cases, records)
        results[name] = {"n_cases": len(cases), **score(cases, assessments),
                         "latency_ms": probe_latency(name),
                         "assessments": [{"id": c.id, **a.model_dump()} for c, a in zip(cases, assessments)]}
        if not results[name]["latency_ms"]:
            print(f"warning: no concurrency-1 latency probe for {name}; latency_ms is empty", flush=True)
        print(f"{name}: {len(cases)} cases, {len(failed)} failed, {len(retried)} answered only on a retry", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0, help="first N cases of each set only, for a trial run")
    parser.add_argument("--sets", nargs="+", default=list(SETS), help=f"sets to ask: {', '.join(SETS)}, or name=dir")
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--latency-probe", type=int, default=PROBE,
                        help="the first N cases of each set are also asked one call at a time; their wall clock is "
                             "the latency_ms of the results")
    parser.add_argument("--cost-cases", type=int, default=COST_CASES,
                        help="cases per set at --concurrency whose requests are audited for tokens and cost")
    parser.add_argument("--probe", action="store_true", help="run the latency probe and nothing else")
    parser.add_argument("--cost", action="store_true", help="run the token / cost measurement and nothing else")
    parser.add_argument("--no-audit", action="store_true", help="do not append the per-request records to audit.jsonl")
    parser.add_argument("--out", default=str(EXP / "results" / f"{MODEL}.json"))
    args = parser.parse_args()
    results = asyncio.run(main(args))
    if results:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"model": MODEL, "sets": results}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        for name, r in results.items():
            print(f"  {name}: " + "  ".join(f"{t} {r[t]['accuracy']:.3f}" for t in
                                            ("goal", "constraints", "selection", "decision") if t in r))
        print(f"wrote {out}")
    # Every answer is on disk; litellm's background cost-table fetch can hold the interpreter for minutes, so end
    sys.stdout.flush()
    os._exit(0)
