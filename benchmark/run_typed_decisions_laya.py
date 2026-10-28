"""Score Laya checkpoints on the Typed Decisions test split, next to the public Laya and JEV numbers:

    python benchmark/run_typed_decisions_laya.py checkpoints/laya/multilingual-base
    python benchmark/run_typed_decisions_laya.py checkpoints/laya/multilingual-base checkpoints/laya/multilingual-krino

Laya answers choice, score and noul natively, so every question goes in as the benchmark writes it: no
option-text adaptation. Inference only; the train split is never downloaded. Each model's results go to
<out>/<model dir name>.json, and report.md compares all of them.
"""
import argparse
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import torch

from benchmark.typed_decisions import load_test
from benchmark.typed_decisions.data import sha256
from benchmark.typed_decisions.metrics import decision, official_metrics, laya_metrics, latency, grouped
from benchmark.typed_decisions.references import REFERENCES, BASELINES

TYPES = ["noul", "choice", "score"]


def predict_case(agent, state: dict, questions: dict) -> tuple[dict, float]:
    """All questions of one case in one predict call, and its wall time in ms."""
    torch.cuda.synchronize()
    start = time.perf_counter()
    answers = agent.predict(state, questions)["answers"]
    torch.cuda.synchronize()
    elapsed = (time.perf_counter() - start) * 1000
    for a in answers.values():
        if a["type"] == "noul":     # Laya returns only P(true) for a noul
            a["probabilities"] = {"false": 1 - a["noul"], "true": a["noul"]}
    return answers, elapsed


def run(model_dir: str, cases) -> dict:
    import laya

    agent = laya.load(model_dir, device="cuda")
    predict_case(agent, cases[0].state, cases[0].questions)     # warm-up, not timed
    rows, ms = [], []
    for i, c in enumerate(cases):
        answers, t = predict_case(agent, c.state, c.questions)
        ms.append(t)
        rows += [decision(c.workflow, qid, g, answers[qid]) for qid, g in c.gold.items()]
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(cases)} cases", flush=True)
    files = sorted(p for p in Path(model_dir).rglob("*") if p.is_file() and ".cache" not in p.parts
                   and p.suffix in {".safetensors", ".json"})
    return {
        "model_dir": model_dir,
        "model_sha256": {str(p.relative_to(model_dir)): sha256(p) for p in files},
        "n_decisions": len(rows),
        "overall": {"official": official_metrics(rows), "laya": laya_metrics(rows)},
        "by_workflow": grouped(rows, "workflow"),
        "by_type": {t: grouped(rows, "type")[t] for t in TYPES},
        "latency": latency(ms),
        "decisions": rows,
    }


def fmt(v, digits=3):
    return "–" if v is None else (f"{v:.{digits}f}" if isinstance(v, float) else str(v))


def markdown(results: dict[str, dict], dataset: dict, env: dict) -> str:
    out = [
        "# Typed Decisions：Laya 系列对比",
        "",
        f"- Benchmark：`{dataset['dataset']}` @ `{dataset['revision']}`，`all/test`，400 cases / 2000 decisions，"
        f"sha256 `{dataset['sha256'][:16]}…`",
        f"- 设备：{env['device']}；torch {env['torch']}；单条请求、batch=1",
        "- 本次测量的模型都只推理，没有用这个 Benchmark 的 train 或 test 训练过，属于 zero-shot",
        "",
        "## 总体",
        "",
        "| 模型 | 来源 | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ | Soft Acc ↑ | Score MAE ↓ | p50 延迟 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        o, l = r["overall"]["official"], r["overall"]["laya"]
        out.append(f"| **{name}** | 本次测量 | {fmt(o['accuracy'])} | {fmt(o['kl_from_gold'])} | {fmt(o['brier'])} | "
                   f"{fmt(o['ece'])} | {fmt(l['soft_accuracy'])} | {fmt(l['score_mae'])} | "
                   f"{r['latency']['p50_ms']:.0f} ms |")
    for ref in REFERENCES:
        o = ref["overall"]
        p50 = f"{o['p50_latency_ms']} ms" if "p50_latency_ms" in o else "–"
        out.append(f"| {ref['name']} | 公开数据（{ref['mode']}） | {fmt(o.get('accuracy'))} | {fmt(o.get('kl_from_gold'))} | "
                   f"{fmt(o.get('brier'))} | {fmt(o.get('ece'))} | {fmt(o.get('soft_accuracy'))} | "
                   f"{fmt(o.get('score_mae'))} | {p50} |")
    for name, b in BASELINES.items():
        out.append(f"| {name} | 数据集卡片 | {fmt(b['accuracy'])} | {fmt(b['kl_from_gold'])} | {fmt(b['brier'])} | "
                   f"{fmt(b['ece'])} | – | – | – |")
    out += [
        "",
        "本次测量的 KL / Brier / ECE 按官方 `bench/score_with_jobs.py`（全部决策、10 bins）；Soft Acc / Score MAE 按 Laya 定义。"
        "Laya 两行的 Brier / ECE 是 Laya 定义（仅 choice+noul、15 bins），与官方定义不能直接比，accuracy 两种定义一致。",
        "",
        "## 分组 accuracy",
        "",
        "| 分组 | " + " | ".join(results) + " | Laya fine-tuned（公开） | JEV 1.13.0（公开） |",
        "|---|" + "---|" * (len(results) + 2),
    ]
    laya_ft, jev = REFERENCES[1], REFERENCES[2]
    first = next(iter(results.values()))
    for group, key in [("by_type", t) for t in TYPES] + [("by_workflow", w) for w in first["by_workflow"]]:
        ours = " | ".join(fmt(r[group][key]["official"]["accuracy"]) for r in results.values())
        out.append(f"| `{key}` | {ours} | {fmt(laya_ft[group].get(key, {}).get('accuracy'))} | "
                   f"{fmt(jev[group].get(key, {}).get('accuracy'))} |")
    out += ["", "来源：", *[f"- {ref['name']}：{ref['source']}" for ref in REFERENCES], ""]
    return "\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="+", help="Laya checkpoint directories")
    parser.add_argument("--out", default="benchmark/results/typed_decisions_laya")
    args = parser.parse_args()

    torch.manual_seed(0)
    cases, dataset = load_test()
    env = {"python": platform.python_version(), "torch": torch.__version__, "device": torch.cuda.get_device_name()}
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for model_dir in args.models:
        name = Path(model_dir).name
        print(f"{name}:", flush=True)
        path = out / f"{name}.json"
        r = run(model_dir, cases)
        path.write_text(json.dumps({**r, "dataset": dataset, "environment": env}, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        o = r["overall"]["official"]
        print(f"  accuracy {o['accuracy']:.3f}  kl {o['kl_from_gold']:.3f}  brier {o['brier']:.3f}  "
              f"ece {o['ece']:.3f}  p50 {r['latency']['p50_ms']:.0f} ms", flush=True)
        results[name] = r
        torch.cuda.empty_cache()
    # report.md covers every model measured into this directory, not only this run's
    for path in sorted(out.glob("*.json")):
        if path.stem not in results:
            results[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    (out / "report.md").write_text(markdown(results, dataset, env), encoding="utf-8")
    print(f"wrote {out / 'report.md'}")
