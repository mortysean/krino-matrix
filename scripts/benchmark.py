"""Score Krino Matrix evaluators on the test sets, task by task and on the final decision; write report.md and one
JSON per model:

    python scripts/benchmark.py checkpoints/matrix/mmbert-uncertainty checkpoints/matrix/mmbert-fixed
    python scripts/benchmark.py checkpoints/matrix/mmbert-uncertainty --sets zh=data/krino_matrix/zh en=data/krino_matrix/en

Every model assesses every case with MatrixEvaluator.assess (one forward pass), and is scored on the labels the case
carries; the input-free prior (the mean labels of the training sets) is scored the same way as a floor.
  goal         accuracy (argmax level), KL, Brier, MAE of the expected level, pairwise ranking within a case
  constraints  accuracy at 0.5, Brier, ECE, AUROC; recall of hard violations (gold P ≥ 0.5)
  selection    the selection head alone: accuracy (argmax = gold argmax), KL, Brier, ECE
  decision     after the hard-constraint filter: the choice is the gold best; the choice breaks a hard constraint
               by the gold labels; every action was excluded
Accuracies carry a 95% bootstrap interval over the test cases. The report also gives, per set, the paired bootstrap
difference in decision accuracy of every model from the --reference one (the first model by default), and the
mean ± std over seeds of every model run with several (directories named <name>-s<seed> group with <name>).
The en set is the typed-decisions test split in Krino Matrix form. Its goal, constraints and best labels all come
from the same teacher (see scripts/unify_data.py), so the three heads are scored against one standard; the
original typed-decisions gold, kept in meta.previous_best, is scored as decision original_gold_accuracy.
"""
import argparse
import json
import math
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch

from krino.matrix import Labels, load
from krino.evaluator import MatrixEvaluator, Assessment

SETS = {"zh": "data/krino_matrix/zh", "en": "data/krino_matrix/en"}
HARD = 0.5
BOOTSTRAP = 2000


def bootstrap(per_case: list, other: list | None = None) -> list[float]:
    """95% percentile interval of the mean over resampled cases; with `other`, of the paired difference."""
    x = np.array(per_case, float) - (np.array(other, float) if other is not None else 0)
    idx = np.random.default_rng(0).integers(0, len(x), (BOOTSTRAP, len(x)))
    return [float(v) for v in np.percentile(x[idx].mean(1), [2.5, 97.5])]


def ece(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            total += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(total)


def distribution_metrics(pairs: list[tuple[list[float], list[float]]]) -> dict:
    """accuracy / KL / Brier / ECE over (gold, predicted) distributions."""
    g = [np.array(a) for a, _ in pairs]
    p = [np.array(b) / max(sum(b), 1e-12) for _, b in pairs]
    correct = np.array([gi.argmax() == pi.argmax() for gi, pi in zip(g, p)], float)
    return {
        "n": len(pairs),
        "accuracy": float(correct.mean()),
        "kl": float(np.mean([sum(x * math.log(x / max(y, 1e-9)) for x, y in zip(gi, pi) if x > 0) for gi, pi in zip(g, p)])),
        "brier": float(np.mean([((pi - gi) ** 2).sum() for gi, pi in zip(g, p)])),
        "ece": ece(np.array([pi.max() for pi in p]), correct),
    }


def auroc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    pos, neg = scores[labels == 1], scores[labels == 0]
    if not len(pos) or not len(neg):
        return None
    ranks = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def expected(dist: list[float]) -> float:
    return sum(i * p for i, p in enumerate(dist))


def score(cases, assessments: list[Assessment]) -> dict:
    goal, mae, ranking, cons, hard, selection, chosen, broken, abstained, original = [], [], [], [], [], [], [], [], [], []
    for case, a in zip(cases, assessments):
        gold, pred = case.labels, a.labels
        for act, dist in (gold.goal if pred.goal else {}).items():     # a model without a head is not scored on it
            goal.append((dist, pred.goal[act]))
            mae.append(abs(expected(dist) - expected(pred.goal[act])))
        ids = list(gold.goal) if pred.goal else []
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                gx, gy = expected(gold.goal[x]), expected(gold.goal[y])
                if abs(gx - gy) >= 0.5:         # pairs the teacher clearly separates
                    ranking.append((expected(pred.goal[x]) > expected(pred.goal[y])) == (gx > gy))
        is_hard = {c.id: c.hard for c in case.constraints}
        for act, per in (gold.constraints if pred.constraints else {}).items():
            for c, p in per.items():
                q = pred.constraints[act][c]
                cons.append((p, q))
                if is_hard[c] and p >= HARD:
                    hard.append(q >= HARD)
        if gold.best:
            ids = list(gold.best)
            selection.append(([gold.best[x] for x in ids], [pred.best[x] for x in ids]))
            chosen.append(a.choice == max(ids, key=gold.best.get))
            abstained.append(a.choice is None)
            if previous := case.meta.get("previous_best"):
                original.append(a.choice == max(previous, key=previous.get))
            if a.choice is not None and gold.constraints:
                broken.append(any(is_hard[c] and p >= HARD for c, p in gold.constraints.get(a.choice, {}).items()))
    out = {}
    if goal:
        out["goal"] = {**distribution_metrics(goal), "mae": float(np.mean(mae)),
                       "ranking": float(np.mean(ranking)) if ranking else None}
    if cons:
        g = np.array([p for p, _ in cons]); q = np.array([x for _, x in cons])
        correct = ((q >= HARD) == (g >= HARD)).astype(float)
        out["constraints"] = {"n": len(cons), "accuracy": float(correct.mean()), "brier": float(np.mean((q - g) ** 2)),
                              "ece": ece(np.maximum(q, 1 - q), correct), "auroc": auroc(q, (g >= HARD).astype(int)),
                              "hard_violation_recall": float(np.mean(hard)) if hard else None,
                              "violation_rate": float((g >= HARD).mean())}
    if selection:
        picked = [int(np.argmax(g) == np.argmax(q)) for g, q in selection]
        out["selection"] = {**distribution_metrics(selection), "accuracy_ci": bootstrap(picked)}
        out["decision"] = {"n": len(chosen), "accuracy": float(np.mean(chosen)), "accuracy_ci": bootstrap(chosen),
                           "hard_violation_rate": float(np.mean(broken)) if broken else None,
                           "abstain_rate": float(np.mean(abstained)),
                           "original_gold_accuracy": float(np.mean(original)) if original else None,
                           "original_gold_accuracy_ci": bootstrap(original) if original else None}
        # Per case, in test-set order, for the paired comparisons of the report
        out["per_case"] = {"decision": [int(x) for x in chosen], "original": [int(x) for x in original]}
    return out


def prior(train_sets: list[Path]):
    """An assess() that ignores the input: the mean training labels, the same for every action."""
    cases = [c for path in train_sets for c in load(path)]

    def mean(rows):
        return [float(v) for v in np.mean(rows, 0)] if rows else None
    by_lang = {lang: {"goal": mean([d for c in cases if c.lang == lang for d in c.labels.goal.values()]),
                      "violation": float(np.mean([p for c in cases if c.lang == lang
                                                  for per in c.labels.constraints.values() for p in per.values()] or [0]))}
               for lang in {c.lang for c in cases}}

    def assess(case) -> Assessment:
        p = by_lang[case.lang]
        ids = [x.id for x in case.action_space]
        return Assessment(labels=Labels(
            goal={x: p["goal"] for x in ids},
            constraints={x: {c.id: p["violation"] for c in case.constraints} for x in ids} if case.constraints else {},
            best={x: 1 / len(ids) for x in ids}), excluded={}, choice=ids[0])
    return assess


def run(assess, sets: dict[str, list], timed: bool) -> dict:
    result = {}
    for name, cases in sets.items():
        assessments, ms = [], []
        for i, case in enumerate(cases):
            if timed:
                torch.cuda.synchronize()
            start = time.perf_counter()
            assessments.append(assess(case))
            if timed:
                torch.cuda.synchronize()
            ms.append((time.perf_counter() - start) * 1000)
            if (i + 1) % 200 == 0:
                print(f"  {name}: {i + 1}/{len(cases)}", flush=True)
        result[name] = {"n_cases": len(cases), **score(cases, assessments),
                        "latency_ms": {"p50": float(np.percentile(ms, 50)), "p95": float(np.percentile(ms, 95))} if timed else None,
                        "assessments": [{"id": c.id, **a.model_dump()} for c, a in zip(cases, assessments)]}
    return result


def fmt(v):
    return "–" if v is None else f"{v:.3f}"


COLUMNS = {
    "decision": ("decision（硬约束过滤后的最终选择）", [("accuracy", "选对 ↑"), ("hard_violation_rate", "选中违反硬约束 ↓"),
                                                     ("abstain_rate", "全部排除 "), ("original_gold_accuracy", "原 gold 选对 ↑")]),
    "goal": ("goal（目标达成五档）", [("accuracy", "Accuracy ↑"), ("kl", "KL ↓"), ("brier", "Brier ↓"), ("mae", "MAE ↓"),
                                     ("ranking", "排序 ↑")]),
    "constraints": ("constraints（约束违反）", [("accuracy", "Accuracy ↑"), ("brier", "Brier ↓"), ("ece", "ECE ↓"),
                                               ("auroc", "AUROC ↑"), ("hard_violation_recall", "硬约束违反召回 ↑")]),
    "selection": ("selection（选择头，未过滤）", [("accuracy", "Accuracy ↑"), ("kl", "KL ↓"), ("brier", "Brier ↓"),
                                                ("ece", "ECE ↓")]),
}


def cell(m: dict, key: str) -> str:
    ci = m.get(f"{key}_ci")
    return fmt(m.get(key)) + (f" [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else "")


def markdown(results: dict[str, dict], env: dict, reference: str | None) -> str:
    out = ["# Krino Matrix benchmark", "",
           f"- 设备：{env['device']}；torch {env['torch']}；每个 case 一次前向，同时输出三个任务", ""]
    set_names = sorted({s for r in results.values() for s in r["sets"]})
    for task, (title, columns) in COLUMNS.items():
        out += [f"## {title}", "", "| 模型 | 数据 | n | " + " | ".join(h for _, h in columns) + " |",
                "|---|---|---|" + "---|" * len(columns)]
        for name, r in results.items():
            for s in set_names:
                m = r["sets"].get(s, {}).get(task)
                if m:
                    out.append(f"| {name} | {s} | {m['n']} | " + " | ".join(cell(m, k) for k, _ in columns) + " |")
        out.append("")
    if reference in results:
        out += [f"## 决策准确率的配对差异（减去 {reference}，95% bootstrap 区间）", "",
                "| 模型 | 数据 | 选对 | 原 gold 选对 |", "|---|---|---|---|"]
        for name, r in results.items():
            if name in (reference, "prior"):
                continue
            for s in set_names:
                mine, ref = r["sets"].get(s, {}).get("per_case"), results[reference]["sets"].get(s, {}).get("per_case")
                if not mine or not ref:
                    continue
                cells = []
                for key in ("decision", "original"):
                    if mine[key] and len(mine[key]) == len(ref[key]):
                        lo, hi = bootstrap(mine[key], ref[key])
                        diff = np.mean(mine[key]) - np.mean(ref[key])
                        cells.append(f"{diff:+.3f} [{lo:+.3f}, {hi:+.3f}]" + (" *" if lo > 0 or hi < 0 else ""))
                    else:
                        cells.append("–")
                out.append(f"| {name} | {s} | " + " | ".join(cells) + " |")
        out += ["", "\\* 区间不含 0。", ""]
    groups = {}
    for name in results:
        groups.setdefault(re.sub(r"-s\d+$", "", name), []).append(name)
    groups = {g: names for g, names in groups.items() if len(names) > 1}
    if groups:
        metrics = [("decision", "accuracy", "决策选对"), ("decision", "original_gold_accuracy", "原 gold 选对"),
                   ("selection", "accuracy", "选择头"), ("goal", "accuracy", "goal"), ("constraints", "auroc", "约束 AUROC")]
        out += ["## 多种子汇总（均值 ± 标准差）", "", "| 模型 | 种子数 | 数据 | " + " | ".join(h for *_, h in metrics) + " |",
                "|---|---|---|" + "---|" * len(metrics)]
        for g, names in groups.items():
            for s in set_names:
                cells = []
                for task, key, _ in metrics:
                    v = [results[n]["sets"][s][task][key] for n in names
                         if results[n]["sets"].get(s, {}).get(task, {}).get(key) is not None]
                    cells.append(f"{np.mean(v):.3f} ± {np.std(v, ddof=1) if len(v) > 1 else 0:.3f}" if v else "–")
                out.append(f"| {g} | {len(names)} | {s} | " + " | ".join(cells) + " |")
        out.append("")
    out += ["## 延迟（每个 case，p50）", "", "| 模型 | " + " | ".join(set_names) + " |", "|---|" + "---|" * len(set_names)]
    for name, r in results.items():
        cells = [f"{r['sets'][s]['latency_ms']['p50']:.0f} ms" if r["sets"].get(s, {}).get("latency_ms") else "–"
                 for s in set_names]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    out += ["", "说明：",
            "- decision：先排除任一硬约束违反概率 ≥0.5 的行动，再在剩下的行动里按选择头取最优；选对 = 与 gold best 的 argmax 一致。",
            "- goal 的排序：同一 case 内 gold 期望档位相差 ≥0.5 的行动对，模型排对的比例。",
            "- constraints 以 0.5 为界；硬约束违反召回 = gold 判为违反的硬约束里，模型也判为违反的比例。",
            "- prior：不看输入，输出训练集的平均标签，选择均匀分布、决策固定选第一个行动，作为下限参照。",
            "- *-selection-only：同一基座、同样数据，只训选择头的消融；没有 goal / constraint 头，也不做硬约束过滤。",
            "- 方括号是 95% bootstrap 区间（按 test case 重采样）；*-s1、*-s2 是同一配置的其他种子。",
            "- en 是 typed-decisions test split 转成的 Krino Matrix；goal、constraints、best 三个标签由同一个 teacher 打。"
            "原 gold 选对 = 与 typed-decisions 原有 action/disposition gold 的 argmax 一致（仅 en 有）。", ""]
    return "\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="*", help="MatrixModel checkpoint directories")
    parser.add_argument("--reference", default=None, help="model the report's paired differences subtract (default: the first)")
    parser.add_argument("--sets", nargs="+", default=[f"{k}={v}" for k, v in SETS.items()], help="name=dataset dir")
    parser.add_argument("--out", default="data/benchmark")
    args = parser.parse_args()

    torch.manual_seed(0)
    dirs = {s.split("=", 1)[0]: ROOT / s.split("=", 1)[1] for s in args.sets}
    sets = {name: load(d / "test.jsonl") for name, d in dirs.items()}
    env = {"python": platform.python_version(), "torch": torch.__version__, "device": torch.cuda.get_device_name()}
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    runs = {"prior": (prior([d / "train.jsonl" for d in dirs.values()]), False)}
    for model_dir in args.models:
        runs[Path(model_dir).name] = (model_dir, True)
    results = {}
    for name, (target, timed) in runs.items():
        print(f"{name}:", flush=True)
        if isinstance(target, str):
            evaluator = MatrixEvaluator(target)
            assess = lambda case: evaluator.assess(case.problem(), case.action_space)
        else:
            assess = target
        r = {"model": name, "sets": run(assess, sets, timed)}
        (out / f"{name}.json").write_text(json.dumps({**r, "environment": env}, ensure_ascii=False, indent=2), encoding="utf-8")
        for s, m in r["sets"].items():
            print(f"  {s}: " + "  ".join(f"{t} {m[t]['accuracy']:.3f}" for t in COLUMNS if t in m), flush=True)
        results[name] = r
        evaluator = assess = None
        torch.cuda.empty_cache()
    # report.md covers every model scored into this directory, not only this run's
    for path in sorted(out.glob("*.json")):
        if path.stem not in results:
            results[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    reference = args.reference or (Path(args.models[0]).name if args.models else None)
    (out / "report.md").write_text(markdown(results, env, reference), encoding="utf-8")
    print(f"wrote {out / 'report.md'}")
