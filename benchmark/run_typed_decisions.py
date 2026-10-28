"""Score the value evaluator on the Typed Decisions test split and write report.md, results.json, comparison.png:

    python benchmark/run_typed_decisions.py
    python benchmark/run_typed_decisions.py --training-data data/exp_C_opus1000 --out benchmark/results/typed_decisions

Inference only, with the pinned model revision; the train split is never downloaded.
"""
import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
import transformers

from core.evaluator.value_evaluator import ValueModel
from benchmark.typed_decisions import load_test, load_model, native_compatibility, predict_case
from benchmark.typed_decisions import leakage
from benchmark.typed_decisions.adapter import state_tokens
from benchmark.typed_decisions.metrics import decision, official_metrics, laya_metrics, latency, grouped
from benchmark.typed_decisions.references import REFERENCES, BASELINES

SEED = 0
TYPES = ["noul", "choice", "score"]


def code_version() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    files = sorted((ROOT / "benchmark").rglob("*.py"))
    return {
        "git_head": git("rev-parse", "HEAD"),
        "benchmark_tracked_and_clean": git("status", "--porcelain", "--", "benchmark") == "",
        "files_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "model_code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted((ROOT / "core/evaluator/value_evaluator").glob("*.py"))},
    }


def uniform_check(cases) -> dict:
    """The input-free Uniform baseline through the same metric code, against the dataset card's numbers."""
    rows = [decision(c.workflow, qid, g, {"probabilities": {k: 1.0 for k in g["probabilities"]}})
            for c in cases for qid, g in c.gold.items()]
    return {"recomputed": official_metrics(rows), "published": BASELINES["Uniform"]}


def fmt(v, digits=3):
    return "–" if v is None else (f"{v:.{digits}f}" if isinstance(v, float) else str(v))


def chart(ours: dict, path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = [("accuracy", "Accuracy ↑"), ("kl_from_gold", "KL from gold ↓"), ("brier", "Brier ↓"),
              ("ece", "ECE ↓"), ("soft_accuracy", "Soft accuracy ↑"), ("score_mae", "Score MAE ↓")]
    names = ["Krino value evaluator\n(measured here)"] + [f"{r['name']}\n(published)" for r in REFERENCES]
    values = [ours] + [r["overall"] for r in REFERENCES]
    ink, muted, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    colors = ["#2a78d6"] + ["#a8a7a1"] * len(REFERENCES)

    fig, axes = plt.subplots(2, 3, figsize=(13, 7.2), facecolor=surface)
    for ax, (key, title) in zip(axes.flat, panels):
        ax.set_facecolor(surface)
        y = np.arange(len(names))[::-1]
        for yi, v, c in zip(y, values, colors):
            if v.get(key) is None:
                ax.text(0, yi, "  no public number", va="center", fontsize=8.5, color=muted)
            else:
                ax.barh(yi, v[key], height=0.55, color=c)
                ax.text(v[key], yi, f" {v[key]:.3f}", va="center", fontsize=9, color=ink)
        top = max([v[key] for v in values if v.get(key) is not None] + [0.01])
        ax.set_xlim(0, top * 1.3)
        ax.set_yticks(y, names if key in ("accuracy", "ece") else [""] * len(names), fontsize=8.5, color=ink)
        ax.set_title(title, fontsize=11, color=ink, loc="left")
        ax.tick_params(axis="x", labelsize=8, colors=muted, length=0)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color=grid, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(grid)
    fig.suptitle("Typed Decisions test split (400 cases, 2,000 decisions)", x=0.01, ha="left", fontsize=13, color=ink)
    fig.text(0.01, 0.01,
             "Krino: zero-shot, option-text adapter (out of distribution; not its trained 5-level rubric). "
             "Brier/ECE: official definitions for Krino and JEV, Laya's (choice+noul Brier, 15-bin ECE) for both Laya rows.\n"
             "Laya fine-tuned was fitted on the train split, so it is not comparable with the zero-shot rows. "
             "Published numbers are cited from their model/dataset cards, not re-measured.",
             fontsize=8, color=muted, ha="left")
    fig.tight_layout(rect=(0, 0.05, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=surface)


def markdown(r: dict) -> str:
    o, l = r["overall"]["official"], r["overall"]["laya"]
    lat = r["latency"]
    out = [
        "# Typed Decisions 评测报告：Krino value evaluator",
        "",
        f"- Benchmark：`{r['dataset']['dataset']}` @ `{r['dataset']['revision']}`，`all/test`，"
        f"{r['n_cases']} cases / {r['n_decisions']} decisions；test 文件 sha256 `{r['dataset']['sha256'][:16]}…`",
        f"- 模型：`{r['model']['repo']}` @ `{r['model']['revision']}`（即 `exp_C_opus1000_base_e20`），只推理，无额外训练、无调参",
        f"- 设备：{r['environment']['device']}；评测代码见 `benchmark/`，各文件 sha256 记录在 results.json",
        "",
        "## 1. 接口兼容性（必读）",
        "",
        f"模型原生只回答一个问题：*{r['native']['trained_question']}*，输出固定的 5 档价值分布。",
        f"Benchmark 的 {r['n_decisions']} 个决策中，**原生兼容 {r['native']['compatible']} 个**，"
        "因此 **原生接口下没有可报告的 Benchmark 成绩**。不兼容原因：",
        "",
        "| 原因 | 决策数 |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in r["native"]["reasons"].items()],
        "",
        "下文成绩来自**选项文本适配**：模型的决策头在每个选项自己的 [MASK] 处读取选项文本，"
        "所以直接把 Benchmark 自带的 criteria 作为选项文本输入，按 Benchmark 的选项顺序和键名输出概率。"
        "没有把任何选项映射到 5 档，没有改写标签含义，也没有用 gold 或 test 拟合温度（沿用模型自带的 "
        f"temperature {r['model']['temperature']:.3f}）。两个没有 criteria 的 noul 问题（invoice `duplicate`、"
        "security `credential_compromise`）使用固定文本 \"The statement is true/false.\"。",
        "",
        "这属于**分布外的零样本用法**：模型只在中文、单一“行动价值”问题上训练过，从未见过这些英文问题和选项集。"
        f"另外中文 BERT 分词器把英文切得很碎，{r['truncation']['cases_truncated']}/{r['n_cases']} 个 case 的 state "
        f"被截断（state token 中位数 {r['truncation']['median_state_tokens']}，上限约 {r['truncation']['approx_state_room']}）。"
        "成绩覆盖全部 2,000 个决策，不是部分样本。",
        "",
        "## 2. 整体结果（本次测量）",
        "",
        "| Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ | Soft Acc ↑ | Score MAE ↓ | p50 延迟 | p95 延迟 |",
        "|---|---|---|---|---|---|---|---|",
        f"| {fmt(o['accuracy'])} | {fmt(o['kl_from_gold'])} | {fmt(o['brier'])} | {fmt(o['ece'])} | "
        f"{fmt(l['soft_accuracy'])} | {fmt(l['score_mae'])} | {lat['p50_ms']:.1f} ms | {lat['p95_ms']:.1f} ms |",
        "",
        "Accuracy / KL / Brier / ECE 按官方 `bench/score_with_jobs.py` 定义（全部 2,000 决策，ECE 10 bins）。"
        "官方脚本没有定义 Soft Acc 和 Score MAE，这两项按 Laya benchmark 的定义（Soft Acc：choice+noul 上 Σp·g；"
        "Score MAE：score 问题上 |期望档位 − gold score|）。按 Laya 定义的其余指标："
        f"accuracy {fmt(l['accuracy'])}，Brier（仅 choice+noul）{fmt(l['brier_choice_noul'])}，ECE（15 bins）{fmt(l['ece_15bins'])}。"
        f"延迟：每个 case 一次请求（编码 + 前向 + softmax），单条、batch=1、fp32，{r['environment']['device']}。",
        "",
        f"参照：Uniform 基线 accuracy {BASELINES['Uniform']['accuracy']}，Prior 基线 {BASELINES['Prior (ignores the input)']['accuracy']}"
        "（数据集卡片公开数据）。本次 accuracy 低于这两个不看输入的基线；ECE 较低主要是因为输出接近均匀、置信度低，"
        "不代表判断质量好。",
        "",
        "## 3. 分组结果（本次测量）",
        "",
        "| 分组 | n | Accuracy | KL | Brier | ECE | Soft Acc | Score MAE |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for title, groups in (("workflow", r["by_workflow"]), ("type", r["by_type"])):
        for k, g in groups.items():
            go, gl = g["official"], g["laya"]
            out.append(f"| {title}: `{k}` | {go['n_decisions']} | {fmt(go['accuracy'])} | {fmt(go['kl_from_gold'])} | "
                       f"{fmt(go['brier'])} | {fmt(go['ece'])} | {fmt(gl['soft_accuracy'])} | {fmt(gl['score_mae'])} |")
    out += [
        "",
        "## 4. 公开参考数据（引用，非本次重新测量）",
        "",
        "以下数字均摘自公开的模型/数据集卡片，**不是本次重新测量**；评测提示、温度和样本处理可能与本次不同，仅供参考。",
        "",
        "| 模型 | 模式 | 指标定义 | Accuracy | KL | Brier | ECE | Soft Acc | Score MAE | p50 延迟 |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| **Krino value evaluator（本次测量）** | zero-shot，选项文本适配 | 官方 | {fmt(o['accuracy'])} | "
        f"{fmt(o['kl_from_gold'])} | {fmt(o['brier'])} | {fmt(o['ece'])} | {fmt(l['soft_accuracy'])} | "
        f"{fmt(l['score_mae'])} | {lat['p50_ms']:.0f} ms |",
        f"| Krino（同上，Laya 定义） | | Laya | {fmt(l['accuracy'])} | – | {fmt(l['brier_choice_noul'])} | "
        f"{fmt(l['ece_15bins'])} | {fmt(l['soft_accuracy'])} | {fmt(l['score_mae'])} | |",
    ]
    for ref in REFERENCES:
        v = ref["overall"]
        p50 = f"{v['p50_latency_ms']} ms" if "p50_latency_ms" in v else "–"
        out.append(f"| {ref['name']}（公开引用） | {ref['mode']} | {ref['definition']} | {fmt(v.get('accuracy'))} | "
                   f"{fmt(v.get('kl_from_gold'))} | {fmt(v.get('brier'))} | {fmt(v.get('ece'))} | "
                   f"{fmt(v.get('soft_accuracy'))} | {fmt(v.get('score_mae'))} | {p50} |")
    out += ["", "分组的公开 accuracy：", "",
            "| 分组 | Krino（本次） | Laya 微调版（公开） | JEV 1.13.0（公开） |", "|---|---|---|---|"]
    laya_ft, jev = REFERENCES[1], REFERENCES[2]
    for k, g in r["by_workflow"].items():
        out.append(f"| `{k}` | {fmt(g['official']['accuracy'])} | {fmt(laya_ft['by_workflow'].get(k, {}).get('accuracy'))} | – |")
    for k, g in r["by_type"].items():
        out.append(f"| `{k}` | {fmt(g['official']['accuracy'])} | {fmt(laya_ft['by_type'].get(k, {}).get('accuracy'))} | "
                   f"{fmt(jev['by_type'].get(k, {}).get('accuracy'))} |")
    out += ["", "来源：", *[f"- {ref['name']}：{ref['source']}" for ref in REFERENCES],
            "- Laya Base 公开数据中没有 KL 和延迟；Laya 微调版在 train split 上训练，属于数据集卡片的第二张表，与 zero-shot 行不可直接比较。",
            "", "![指标对比](comparison.png)", ""]

    lk, u = r["leakage"], r["metric_check"]
    out += [
        "## 5. 数据泄漏检查",
        "",
        "- 评测进程只下载 `all/test` parquet（加官方评分脚本，仅用于核对指标定义、不执行），train split 不进入本进程。",
        "- 模型从未使用本 Benchmark 的 train 或 test 训练；温度在模型自己的 held-out 数据上拟合，本次未重新拟合。",
    ]
    if lk["checked"]:
        out += [
            f"- 扫描训练数据 {len(lk['training_files'])} 个文件（{', '.join(f'`{Path(f).relative_to(ROOT)}`' for f in lk['training_files'])}）：",
            f"  case id 命中 {len(lk['case_id_hits'])}；≥25 字符的 state/question 字符串 {lk['long_strings_checked']} 条，"
            f"完全匹配命中 {lk['n_long_string_hits']}；state 的 13-gram {lk['state_13grams_checked']} 个，命中 {lk['state_13gram_hits']}。",
            f"  训练数据含 {lk['training_cjk_chars']} 个汉字、{lk['training_latin_letters']} 个拉丁字母（训练语料以中文为主）。",
            f"- 结论：{'未发现泄漏' if lk['clean'] else '**发现重叠，见 results.json 的 leakage 字段**'}。",
        ]
    else:
        out.append(f"- 未能扫描训练数据：{lk['reason']}")
    out += [
        "- 局限：只能检查本地可见的训练数据；预训练骨干（中文 BERT）的预训练语料无法检查。",
        "",
        "## 6. 可复现性",
        "",
        f"- 数据集 revision `{r['dataset']['revision']}`，test 文件 sha256 `{r['dataset']['sha256']}`（不一致时拒绝运行）",
        f"- 模型 `{r['model']['repo']}` revision `{r['model']['revision']}`，各文件 sha256 见 results.json",
        f"- 代码：git HEAD `{r['code']['git_head']}`，benchmark 目录已提交且无改动：{r['code']['benchmark_tracked_and_clean']}；"
        "各源文件 sha256 见 results.json",
        f"- 环境：python {r['environment']['python']}，torch {r['environment']['torch']}，transformers {r['environment']['transformers']}，seed {SEED}",
        f"- 指标代码自检：用同一套代码重算数据集卡片的 Uniform 基线，得到 accuracy {u['recomputed']['accuracy']:.3f} / "
        f"KL {u['recomputed']['kl_from_gold']:.3f} / Brier {u['recomputed']['brier']:.3f} / ECE {u['recomputed']['ece']:.3f}，"
        f"公开值 {u['published']['accuracy']} / {u['published']['kl_from_gold']} / {u['published']['brier']} / {u['published']['ece']}。"
        "KL、Brier 一致；accuracy、ECE 不同是因为均匀分布的 argmax 全部打平，结果取决于打平时取哪个选项"
        "（官方脚本取第一个选项，数据集卡片没有说明它的 Uniform 怎么处理打平），对非均匀的模型输出没有影响。",
        f"- 复现命令：`{r['command']}`",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="benchmark/results/typed_decisions")
    parser.add_argument("--training-data", nargs="+", default=["data/exp_C_opus1000"],
                        help="directories with the model's training data, for the leakage check")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()

    torch.manual_seed(SEED)
    torch.backends.cudnn.deterministic, torch.backends.cudnn.benchmark = True, False
    cases, dataset = load_test()
    model_dir, model_info = load_model()
    model = ValueModel(model_dir).to(args.device).eval()
    model_info["temperature"] = float(model.temperature)

    native = {"trained_question": "How much value does this action bring toward the objective, given the state?",
              "compatible": 0, "reasons": {}}
    for c in cases:
        for q in c.questions.values():
            ok, why = native_compatibility(q)
            native["compatible"] += ok
            native["reasons"][why] = native["reasons"].get(why, 0) + 1

    tokens = [state_tokens(model, c.state) for c in cases]
    room = model.max_length - model.head_max_length
    truncation = {"approx_state_room": room, "median_state_tokens": int(np.median(tokens)),
                  "cases_truncated": sum(t > room for t in tokens)}

    predict_case(model, cases[0].state, cases[0].questions)     # warm-up, not timed
    rows, ms = [], []
    for i, c in enumerate(cases):
        answers, t = predict_case(model, c.state, c.questions)
        ms.append(t)
        rows += [decision(c.workflow, qid, g, answers[qid]) for qid, g in c.gold.items()]
        if (i + 1) % 100 == 0:
            print(f"{i + 1}/{len(cases)} cases", flush=True)

    device = torch.cuda.get_device_name() if args.device.startswith("cuda") else platform.processor() or "cpu"
    result = {
        "n_cases": len(cases), "n_decisions": len(rows),
        "dataset": dataset, "model": model_info, "native": native, "truncation": truncation,
        "overall": {"official": official_metrics(rows), "laya": laya_metrics(rows)},
        "by_workflow": grouped(rows, "workflow"), "by_type": {t: grouped(rows, "type")[t] for t in TYPES},
        "latency": latency(ms),
        "references": REFERENCES, "baselines": BASELINES, "references_note": "public numbers, not re-measured",
        "leakage": leakage.check(cases, [str(ROOT / d) for d in args.training_data]),
        "metric_check": uniform_check(cases),
        "code": code_version(),
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "transformers": transformers.__version__, "device": device},
        "command": "python benchmark/run_typed_decisions.py " + " ".join(sys.argv[1:]),
        "decisions": [{k: v for k, v in r.items()} for r in rows],
    }
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    ours = {**result["overall"]["official"], "soft_accuracy": result["overall"]["laya"]["soft_accuracy"],
            "score_mae": result["overall"]["laya"]["score_mae"]}
    chart(ours, out / "comparison.png")
    (out / "report.md").write_text(markdown(result), encoding="utf-8")
    o = result["overall"]["official"]
    print(f"accuracy {o['accuracy']:.3f}  kl {o['kl_from_gold']:.3f}  brier {o['brier']:.3f}  ece {o['ece']:.3f}  "
          f"p50 {result['latency']['p50_ms']:.1f} ms  native-compatible {native['compatible']}/{len(rows)}")
    print(f"wrote {out / 'report.md'}, {out / 'results.json'}, {out / 'comparison.png'}")
