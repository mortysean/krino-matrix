"""Metrics, each with the definition of the source that publishes it.

Official (the dataset's bench/score_with_jobs.py at the pinned revision, over all 2,000 decisions):
  accuracy  argmax of the prediction == argmax of the gold distribution
  kl        sum over gold > 0 of g * log(g / max(p, 1e-9))
  brier     sum (p - g)^2
  ece       10 equal-width bins of max(p) against correctness
The official scorer defines no soft accuracy or score MAE, so those two follow the Laya benchmark
(research/scripts/step4_benchmark/evaluate.py + metrics.py), whose published numbers they compare with:
  soft_accuracy  mean of sum(p * g) over choice and noul decisions
  score_mae      mean |expected level - gold score| over score decisions (gold score is the gold expected level)
Laya's Brier (choice and noul only) and ECE (15 bins) are reported next to them for the same reason.
"""
import math
from collections import defaultdict

import numpy as np

from core.evaluator.value_evaluator.train import ece as ece15


def decision(
    workflow: str,
    qid: str,
    gold: dict,
    pred: dict
) -> dict:
    """Per-decision scores for one question."""
    keys = list(gold["probabilities"])
    g = [float(gold["probabilities"][k]) for k in keys]
    p = [float(pred["probabilities"].get(k, 0.0)) for k in keys]
    s = sum(p)
    p = [v / s for v in p] if s > 0 else [1.0 / len(keys)] * len(keys)
    out = {
        "workflow": workflow, "question": qid, "type": gold["type"],
        "correct": p.index(max(p)) == g.index(max(g)),
        "kl": sum(gi * math.log(gi / max(pi, 1e-9)) for gi, pi in zip(g, p) if gi > 0),
        "brier": sum((pi - gi) ** 2 for pi, gi in zip(p, g)),
        "confidence": max(p),
        "pred": dict(zip(keys, p)),
    }
    if gold["type"] == "score":
        out["laya_correct"] = str(p.index(max(p))) == str(gold["label"])
        out["score_abs_error"] = abs(sum(i * v for i, v in enumerate(p)) - float(gold["score"]))
    else:
        if gold["type"] == "noul":
            out["laya_correct"] = ("true" if out["pred"].get("true", 0.0) >= 0.5 else "false") == str(gold["label"]).lower()
        else:
            out["laya_correct"] = keys[p.index(max(p))] == str(gold["label"])
        gn = np.array([max(v, 1e-6) for v in g])
        gn = gn / gn.sum()
        out["soft"] = float((np.array(p) * gn).sum())
        out["laya_brier"] = float(((np.array(p) - gn) ** 2).sum())
    return out


def ece10(
    confidence: list[float],
    correct: list[bool]
) -> float:
    n, bins = len(confidence), 10
    hits, total, conf = [0] * bins, [0] * bins, [0.0] * bins
    for ok, c in zip(correct, confidence):
        b = min(int(c * bins), bins - 1)
        total[b] += 1
        hits[b] += int(ok)
        conf[b] += c
    return sum(total[b] / n * abs(hits[b] / total[b] - conf[b] / total[b]) for b in range(bins) if total[b])


def official_metrics(rows: list[dict]) -> dict:
    return {
        "n_decisions": len(rows),
        "accuracy": float(np.mean([r["correct"] for r in rows])),
        "kl_from_gold": float(np.mean([r["kl"] for r in rows])),
        "brier": float(np.mean([r["brier"] for r in rows])),
        "ece": ece10([r["confidence"] for r in rows], [r["correct"] for r in rows]),
    }


def laya_metrics(rows: list[dict]) -> dict:
    soft = [r["soft"] for r in rows if "soft" in r]
    mae = [r["score_abs_error"] for r in rows if "score_abs_error" in r]
    return {
        "accuracy": float(np.mean([r["laya_correct"] for r in rows])),
        "soft_accuracy": float(np.mean(soft)) if soft else None,
        "score_mae": float(np.mean(mae)) if mae else None,
        "brier_choice_noul": float(np.mean([r["laya_brier"] for r in rows if "laya_brier" in r])) if soft else None,
        "ece_15bins": ece15(np.array([r["confidence"] for r in rows]), np.array([r["laya_correct"] for r in rows], float)),
    }


def latency(ms: list[float]) -> dict:
    return {"n_cases": len(ms), "p50_ms": float(np.percentile(ms, 50)), "p95_ms": float(np.percentile(ms, 95)),
            "mean_ms": float(np.mean(ms))}


def grouped(
    rows: list[dict],
    key: str
) -> dict[str, dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    return {k: {"official": official_metrics(v), "laya": laya_metrics(v)} for k, v in sorted(groups.items())}
