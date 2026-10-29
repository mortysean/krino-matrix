"""report.md for the LLM zero-shot baseline: the metrics of results/llm-zeroshot-flash.json per task with 95%
bootstrap intervals, the decision metrics, single-call latency, tokens and the cost of a thousand decisions, the
failed and retried cases, and the served model against the teacher.

    python experiments/llm-zeroshot/report.py

Reads, without asking anything new:
  results/llm-zeroshot-flash.json   the metrics, latency_ms and assessments written by run.py
  raw/<set>.jsonl                   every case: attempts, error or assessment, wall clock
  results/probe.jsonl               the concurrency-1 latency probe: per case, its single calls and their tokens
  results/cost.jsonl                the deployment-concurrency probe: the same, for tokens and price
  results/audit.jsonl               one line per HTTP answer of the run that asked the cases: tokens, ms
  results/audit-cost.jsonl          the same for the cost probe
The price is OpenRouter's for the served version at the time the report is written; its weekday peak surcharges are
listed, not applied.
"""
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))      # run.py sits next to this file, not in a package

import httpx

from krino.matrix import load
from run import EXP, MODEL, MAX_ATTEMPTS, MAX_TOKENS, REASONING, ATTEMPT_TIMEOUT, CROSS_ATTEMPT, PROBE, \
    COST_CASES, CONCURRENCY, TEACHER
from scripts.benchmark import BOOTSTRAP

import numpy as np

PRICING_MODEL = "deepseek/deepseek-v4.1-flash"      # the version LLM_DEFAULT resolves to, the served_model


def boot(per_case: list[list[float]]) -> list[float]:
    """95% percentile interval of the case mean over the test cases, resampling cases (a case keeps its actions and
    constraint pairs), the method of scripts/benchmark.py's bootstrap(): for the goal and constraints
    accuracies, which score() does not interval itself."""
    x = np.array([np.mean(v) for v in per_case], float)
    idx = np.random.default_rng(0).integers(0, len(x), (BOOTSTRAP, len(x)))
    return [float(v) for v in np.percentile(x[idx].mean(1), [2.5, 97.5])]


def boot_items(values: list[int]) -> list[float]:
    """95% percentile interval of a ratio over items (the hard violations the teacher labels), resampling items:
    that is how scripts/benchmark.py reports hard_violation_recall, as a rate over constraint pairs rather
    than over cases."""
    x = np.array(values, float)
    idx = np.random.default_rng(0).integers(0, len(x), (BOOTSTRAP, len(x)))
    return [float(v) for v in np.percentile(x[idx].mean(1), [2.5, 97.5])]


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("{")]


def latest_by_id(records: list[dict]) -> dict[str, dict]:
    latest = {}
    for record in records:
        latest[record["id"]] = record
    return latest


def fmt(value, digits: int = 3) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def fmt_ci(value, ci) -> str:
    return fmt(value) + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")


def pricing() -> dict:
    """OpenRouter's current price of the served version, in USD per token."""
    # Same environment wart as in run.py: HTTPS_PROXY is needed, and the NO_PROXY of this shell lists "[::1]", which
    # httpx cannot parse (an InvalidURL for "[::1]:1")
    for key in ("NO_PROXY", "no_proxy"):
        if "[::1]" in os.environ.get(key, ""):
            os.environ[key] = ",".join(p for p in os.environ[key].split(",") if p.strip() != "[::1]")
    try:
        response = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
        response.raise_for_status()
        model = next(m for m in response.json()["data"] if m["id"] == PRICING_MODEL)
        return {"prompt": float(model["pricing"]["prompt"]), "completion": float(model["pricing"]["completion"]),
                "overrides": model["pricing"].get("overrides") or []}
    except Exception as e:      # the report stays useful without a price, it just cannot price
        print(f"could not fetch the OpenRouter price: {type(e).__name__}: {e}")
        return {}


def cost_of(record: dict, price: dict) -> float | None:
    if not price:
        return None
    return sum((c.get("input_tokens") or 0) * price["prompt"] + (c.get("output_tokens") or 0) * price["completion"]
               for c in record.get("calls", []))


def main():
    results = json.loads((EXP / "results" / f"{MODEL}.json").read_text(encoding="utf-8"))
    sets = results["sets"]
    probe = read_jsonl(EXP / "results" / "probe.jsonl")
    cost = read_jsonl(EXP / "results" / "cost.jsonl")
    audit = read_jsonl(EXP / "results" / "audit.jsonl") + read_jsonl(EXP / "results" / "audit-cost.jsonl")
    price = pricing()
    served = Counter(a.get("served_model") for a in audit if a.get("served_model"))
    served_model = served.most_common(1)[0][0] if served else "deepseek/deepseek-v4.1-flash-1017"
    raw = {name: latest_by_id(read_jsonl(EXP / "raw" / f"{name}.jsonl")) for name in sets}
    same = served_model == TEACHER

    out = ["# LLM 零样本基线：deepseek flash 每个决策一次调用", ""]
    out += ["## 结论", ""]
    if same:
        out += [f"**`llm.served_model` 解析出来是 `{served_model}`，和 teacher（`{TEACHER}`，见 test 数据 "
                f"`meta.*_teacher`）是同一个模型。** 同模型、同 prompt、同输出 schema，teacher 是 temperature 0.7 "
                f"采样 3 次取平均的标签，这条基线是 temperature 0 的一次调用。它不是“换个更强模型”的对照，"
                f"测的是把 teacher 的合成标注蒸馏进小模型值不值。"]
    else:
        out += [f"`llm.served_model` 是 `{served_model}`，与 teacher `{TEACHER}` 不是同一个模型。"]
    out += [""]
    for name, m in sets.items():
        d = m["decision"]
        out += [f"- {name}（{m['n_cases']} 条）：决策选对 {fmt_ci(d['accuracy'], d['accuracy_ci'])}；"
                f"选中行动按 gold 违反硬约束的比例 {fmt(d['hard_violation_rate'])}；全部行动被排除 {fmt(d['abstain_rate'])}；"
                f"goal 准确率 {fmt(m['goal']['accuracy'])}，constraints 准确率 {fmt(m['constraints']['accuracy'])}，"
                f"约束 AUROC {fmt(m['constraints']['auroc'])}。"]
    failed = {name: [r for r in raw[name].values() if "error" in r] for name in sets}
    out += [f"- 最终失败的 case：{', '.join(f'{name} {len(v)}' for name, v in failed.items())}。", ""]

    out += ["## 设置", "",
            f"- 模型：`.env` 的 `LLM_DEFAULT` 是 `~deepseek/deepseek-flash-latest`，经 `krino/llm.py` 的 `LLM()` "
            f"调用，`served_model` = `{served_model}`；teacher 是 `{TEACHER}`。",
            "- 每条 test case 只问一次，temperature 0（重试时同样）。prompt 和输出 schema 直接 import 自 "
            "`scripts/build_data.py`（`LABEL_PROMPT`、`GOAL_TASK`、`CONSTRAINTS_TASK`、`BEST_TASK`、"
            "`teacher_output`、`levels_text`、`constraints_list`、`normalized`），没有复制改写。",
            "- 行动顺序：每条 case 以固定种子 0 打乱一次，`raw/<set>.jsonl` 的 `shown` 字段记录了模型看到的顺序。",
            f"- 调用方设置（不属于评测本身）：`reasoning = {json.dumps(REASONING)}`，`max_tokens = {MAX_TOKENS}`。"
            "不这样设置、让模型按默认深度思考时，它在这个 prompt 上会先写很长的思维链、再写 6k–10k token 的正文，"
            "几乎不闭合 JSON（max_tokens 4000 下 3 条测试样例全部截断、只能靠重试拿到答案）；关掉后单次 5–9 s。"
            "实测同样 3 条：none 5–9 s，low 37–51 s，medium 第一条 52 s 仍没有可用的 JSON。",
            f"- 超时：单次尝试 {ATTEMPT_TIMEOUT} s，一条 case 累计 {CROSS_ATTEMPT} s，最多 {MAX_ATTEMPTS} 次尝试；"
            "在并发下失败过的 case 会在并发 1 下再问一遍。",
            "- 判为不合法即重试，用的是 `label()` 自己的规则：每个行动都要判、goal 是 5 个和为 1 的概率、"
            "违反概率都在 [0, 1]、best 是分布。另外 JSON 解析失败（含被 max_tokens 截断）也算无效。best 里"
            "缺的行动按 0 计（schema 允许省略，teacher 的答案也常把非选项给 0；加 0 不改变分布）。最终仍失败的 "
            "case 记为失败、单独统计，不静默丢弃。",
            ""]

    out += ["## 指标（对照 teacher 标签）", "",
            "`score()` 只给 selection 和 decision 生成 bootstrap 区间，goal / constraints 的区间这里按同一方法补"
            "（按 test case 重采样 2000 次，见 `report.py` 的 `boot()`）。",
            "", "| 数据 | 任务 | 指标 | n | LLM 零样本 |", "|---|---|---|---|---|"]
    for name, m in sets.items():
        cases = load(ROOT / "data/krino_matrix" / name / "test.jsonl")
        latest = raw[name]
        answered = [c for c in cases if c.id in latest and "assessment" in latest[c.id]]

        def pred(assessment: dict, a: str, dist: list[float]) -> dict:
            return {"goal": assessment["labels"]["goal"][a], "gold": dist}

        goal_ok = [[int(p["goal"].index(max(p["goal"])) == p["gold"].index(max(p["gold"])))
                    for a in c.labels.goal if (p := pred(latest[c.id]["assessment"], a, c.labels.goal[a]))]
                   for c in answered if c.labels.goal]
        cons_ok = [[int((latest[c.id]["assessment"]["labels"]["constraints"][a][k] >= 0.5) == (p >= 0.5))
                    for a, per in c.labels.constraints.items() for k, p in per.items()]
                   for c in answered if c.labels.constraints]
        # Per case, the hard violations the teacher labels at P >= 0.5 and whether the model also puts them there
        hard_ok = [[int(latest[c.id]["assessment"]["labels"]["constraints"][a][k] >= 0.5) for a, per in
                    c.labels.constraints.items() for k, p in per.items()
                    if next(x.hard for x in c.constraints if x.id == k) and p >= 0.5]
                   for c in answered if c.labels.constraints]
        hard_ok = [v for v in hard_ok if v]
        rec = [int(q) for v in hard_ok for q in v]
        g, c, s, d = m["goal"], m["constraints"], m["selection"], m["decision"]
        rows = [
            ("goal", "Accuracy ↑（argmax 档位）", g["n"], fmt_ci(g["accuracy"], boot(goal_ok))),
            ("goal", "KL ↓", g["n"], fmt(g["kl"])),
            ("goal", "Brier ↓", g["n"], fmt(g["brier"])),
            ("goal", "MAE ↓（期望档位）", g["n"], fmt(g["mae"])),
            ("goal", "排序 ↑（gold 期望档位相差 ≥0.5 的行动对）", g["n"], fmt(g["ranking"])),
            ("constraints", "Accuracy ↑（0.5 为界）", c["n"], fmt_ci(c["accuracy"], boot(cons_ok))),
            ("constraints", "Brier ↓", c["n"], fmt(c["brier"])),
            ("constraints", "ECE ↓", c["n"], fmt(c["ece"])),
            ("constraints", "AUROC ↑", c["n"], fmt(c["auroc"])),
            ("constraints", "硬约束违反召回 ↑（gold P ≥ 0.5）", len(rec), fmt_ci(c["hard_violation_recall"], boot_items(rec))),
            ("selection", "Accuracy ↑（argmax 行动）", s["n"], fmt_ci(s["accuracy"], s["accuracy_ci"])),
            ("selection", "KL ↓", s["n"], fmt(s["kl"])),
            ("selection", "Brier ↓", s["n"], fmt(s["brier"])),
            ("selection", "ECE ↓", s["n"], fmt(s["ece"])),
            ("decision", "选对 ↑（硬约束过滤后，与 gold best argmax 一致）", d["n"], fmt_ci(d["accuracy"], d["accuracy_ci"])),
            ("decision", "选中行动按 gold 违反硬约束 ↓", d["n"], fmt(d["hard_violation_rate"])),
            ("decision", "全部行动被排除（弃权）", d["n"], fmt(d["abstain_rate"])),
        ]
        if d.get("original_gold_accuracy") is not None:
            rows.append(("decision", "原 typed-decisions gold 选对 ↑", d["n"],
                         fmt_ci(d["original_gold_accuracy"], d["original_gold_accuracy_ci"])))
        for task, label, n, value in rows:
            out.append(f"| {name} | {task} | {label} | {n} | {value} |")
    out += ["", "- goal：每个行动的目标达成五档分布；constraints：每个行动 × 每条约束的违反概率；selection：best 分布的 argmax。",
            "- decision：先排除任一硬约束违反概率 ≥ 0.5 的行动，再在剩下的行动里取 best 最大的，和 `MatrixEvaluator.assess` "
            "的规则一致。`selection` 是没过滤时的 argmax。",
            "- en 是 typed-decisions test split 转成的 Krino Matrix，它的原 gold 在 `meta.previous_best`，"
            "“原 gold 选对”只对 en 有定义。", ""]

    out += ["## 失败与重试", "",
            "每条 case 的记录在 `raw/<set>.jsonl`（同一 case 以最后一行为准）：`attempts` 是尝试次数，`error` 表示最终"
            "没有可用答案。", "",
            "| 数据 | case 数 | 一次成功 | 重试后成功 | 最终失败 | 没有产出可用答案的尝试 |",
            "|---|---|---|---|---|---|"]
    for name, m in sets.items():
        records = list(raw[name].values())
        answered = [r for r in records if "error" not in r]
        no_answer = sum(r["attempts"] - 1 for r in records)
        out.append(f"| {name} | {m['n_cases']} | {sum(r['attempts'] == 1 for r in answered)} | "
                   f"{sum(r['attempts'] > 1 for r in answered)} | {len(failed[name])} | {no_answer} |")
    out += [""]
    for name in sets:
        if failed[name]:
            out += [f"{name} 最终失败的 case（逐条）：", ""]
            for r in failed[name]:
                out.append(f"- `{r['id']}`：{r['attempts']} 次尝试，{r['error'].splitlines()[0][:220]}")
            out += [""]
        elif not any(r.get("error") for r in raw[name].values()):
            out += [f"{name}：没有最终失败的 case。", ""]
    reasons = Counter()
    for name in sets:
        for r in raw[name].values():
            if "error" in r:
                reasons[r["error"].split(":")[0]] += 1
    if reasons:
        out += ["失败原因：" + "，".join(f"{k} {v}" for k, v in reasons.most_common()) + "。", ""]

    out += ["## 延迟、token 与成本", "",
            f"单次延迟来自并发 1 的探测（每个数据前 {PROBE} 条），不受队列等待影响，也正是结果 JSON 里 `latency_ms` "
            f"的来源。token 和价格为每个数据 {COST_CASES} 条、并发 {CONCURRENCY} 的探测，取每次调用的实际用量。", "",
            "| 数据 | 单次延迟 p50 | p95 | 平均输入 token | 平均输出 token | 单次调用成本 | 每千次决策成本 | "
            f"部署并发 {CONCURRENCY} 下 p50（参考） |",
            "|---|---|---|---|---|---|---|---|"]
    for name, m in sets.items():
        p = [r["latency_ms"] for r in probe if r.get("set") == name and r.get("concurrency") == 1]
        c = [r for r in cost if r.get("set") == name]
        source = c or [r for r in probe if r.get("set") == name]
        calls = [call for r in source for call in r.get("calls", [])]
        # What one decision costs: its calls, and if none is on record (a response without usage), the mean token
        # count of the calls on record
        usable = [r for r in source if r.get("calls")]
        per_call = [x for x in (cost_of(r, price) for r in usable) if x is not None]
        if price and len(usable) < len(source) and calls:
            mean_in_calls = statistics.mean([x.get("input_tokens") or 0 for x in calls])
            mean_out_calls = statistics.mean([x.get("output_tokens") or 0 for x in calls])
            fallback = mean_in_calls * price["prompt"] + mean_out_calls * price["completion"]
            per_call += [fallback] * (len(source) - len(usable))
        mean_in = statistics.mean([x.get("input_tokens") or 0 for x in calls]) if calls else None
        mean_out = statistics.mean([x.get("output_tokens") or 0 for x in calls]) if calls else None
        mean_cost = statistics.mean(per_call) if per_call else None
        cp = [r["latency_ms"] for r in c]
        out.append(f"| {name} | {m['latency_ms']['p50']:.0f} ms | {m['latency_ms']['p95']:.0f} ms | "
                   f"{fmt(mean_in, 0)} | {fmt(mean_out, 0)} | "
                   f"{'$%.5f' % mean_cost if mean_cost is not None else '–'} | "
                   f"{'$%.4f' % (1000 * mean_cost) if mean_cost is not None else '–'} | "
                   f"{'%.0f ms' % statistics.median(cp) if cp else '–'} |")
    out += [""]
    if price:
        out += [f"价格取 OpenRouter `{PRICING_MODEL}` 当前价：${price['prompt'] * 1e6:.4f} / 百万输入 token，"
                f"${price['completion'] * 1e6:.4f} / 百万输出 token（`https://openrouter.ai/api/v1/models`，写报告时读取）。"
                "按实际用量（含重试）算，不按缓存价。"]
        peak = [o for o in price["overrides"] if o.get("prompt") != price["prompt"]]
        if peak:
            out += ["OpenRouter 在工作日部分时段（UTC）加价（上表的基础价只在非加价时段成立），这里只用基础价："
                    + "；".join(f"UTC {o.get('utc_start')}–{o.get('utc_end') or 24}（{','.join(o.get('utc_days') or [])}）"
                               f" ${o['prompt'] * 1e6:.4f} / ${o['completion'] * 1e6:.4f}" for o in peak) + "。"]
        out += [""]
    calls_audit = [a for a in audit if not a.get("aggregate")]
    aggregates = [a for a in audit if a.get("aggregate")]
    if audit:
        tokens_in = sum(a.get("input_tokens") or 0 for a in audit)
        tokens_out = sum(a.get("output_tokens") or 0 for a in audit)
        finishes = Counter(a.get("finish_reason") for a in calls_audit)
        total_cost = sum((a.get("input_tokens") or 0) * price["prompt"] + (a.get("output_tokens") or 0) * price["completion"]
                         for a in audit) if price else None
        summary = ", ".join(f"{a['set']} {a['calls']} 次" for a in aggregates) or "无"
        out += [f"审计记录里的 HTTP 调用共 {len(calls_audit)} 次（成本探测），加上正式跑的汇总 {summary}："
                f"{tokens_in:,} 输入 + {tokens_out:,} 输出 = {tokens_in + tokens_out:,} token"
                + (f"，按上面价格合计 ${total_cost:.3f}" if total_cost is not None else "")
                + ("；结束原因 " + "，".join(f"{k} {v}" for k, v in finishes.most_common())
                   + "（`length` 是 max_tokens 截断，`stop` 是正常结束）" if finishes else "")
                + "。正式跑的逐调用记录在两次正式跑时被覆盖（那是拆分审计文件之前），只留下 `results/audit.jsonl` "
                  "里的 `aggregate` 汇总行；成本探测的逐调用记录在 `results/audit-cost.jsonl`。", ""]
    out += ["## 与小模型对照时要注意", "",
            f"- 同一模型：标签和基线都出自 `{served_model}`，差别只在 temperature 0 与一次采样。",
            "- 延迟是端到端的一次 HTTP 调用（含输出 token 生成），MatrixEvaluator 是一次前向。",
            "- 成本包含重试：一个不合法答案会让这条 case 再多花一次调用的钱。",
            f"- 正式跑用并发 {CONCURRENCY}；并发下延迟见上表最后一列，部署吞吐取决于能并发多少请求。",
            ""]
    (EXP / "results" / "report.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {EXP / 'results/report.md'}")


if __name__ == "__main__":
    main()
