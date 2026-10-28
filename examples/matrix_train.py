"""Train the Krino Matrix evaluator (core/evaluator/matrix_evaluator) on Krino Matrix datasets, from a plain
pretrained encoder: every head starts from scratch and no decision model is inherited.

    python examples/matrix_train.py data/krino_matrix/zh data/krino_matrix/en --weighting uncertainty \
        --out checkpoints/matrix/mmbert-uncertainty
    python examples/matrix_train.py data/krino_matrix/zh data/krino_matrix/en --weighting fixed \
        --out checkpoints/matrix/mmbert-fixed
    python examples/matrix_train.py data/krino_matrix/zh data/krino_matrix/en --base jhu-clsp/mmBERT-base \
        --freeze-below 10 --out checkpoints/matrix/mmbert-uncertainty-frozen
    python examples/matrix_train.py data/krino_matrix/zh data/krino_matrix/en --tasks selection \
        --out checkpoints/matrix/mmbert-selection-only

train.jsonl of every data dir is trained on and val.jsonl picks the epoch and fits the temperatures; test.jsonl is
left to benchmark/run_krino_matrix.py. The run log, with every task's raw loss, effective weight and the total,
is written to <out>/train_log.jsonl.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Make the project root importable when this file is run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from core.matrix import load
from core.evaluator.matrix_evaluator import MatrixModel, TrainConfig, train, calibrate
from core.evaluator.matrix_evaluator.model import TASKS

BASE = "jhu-clsp/mmBERT-base"     # the encoder under Laya's multilingual checkpoint, before any decision training

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data", nargs="+", help="Krino Matrix dirs with train.jsonl / val.jsonl")
    parser.add_argument("--out", required=True)
    parser.add_argument("--base", default=BASE, help="pretrained encoder (HF id or dir) to start from")
    parser.add_argument("--head-layers", type=int, default=2, help="refining transformer layers above the encoder")
    parser.add_argument("--hf-endpoint", default=None,
                        help="Hub endpoint for the base encoder, e.g. https://hf-mirror.com (env HF_ENDPOINT works too)")
    parser.add_argument("--weighting", choices=["uncertainty", "fixed"], default="uncertainty")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--micro-batch", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=16)
    parser.add_argument("--freeze-below", type=int, default=0, help="freeze the embeddings and this many encoder layers")
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--limit", type=int, default=0, help="first N cases per file only, for a smoke run")
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS), help="heads to train, for ablations")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default=None, help="cuda, cpu, or None to pick cuda when it is available")
    args = parser.parse_args()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")

    cases, val = [], []
    for d in args.data:
        cases += load(Path(d) / "train.jsonl")[:args.limit or None]
        val += load(Path(d) / "val.jsonl")[:args.limit or None]
    model = MatrixModel(args.base, max_length=args.max_length, head_layers=args.head_layers,
                        hf_endpoint=args.hf_endpoint or os.environ.get("HF_ENDPOINT") or None).to(device)
    print(f"base {args.base}: encoder from the pretrained weights, all heads from scratch", flush=True)
    config = TrainConfig(weighting=args.weighting, epochs=args.epochs, micro_batch=args.micro_batch,
                         grad_accum=args.grad_accum, freeze_below=args.freeze_below, tasks=tuple(args.tasks),
                         seed=args.seed)
    print(f"device {device}, {len(cases)} train cases, {len(val)} val cases", flush=True)
    summary = train(model, cases, val, config, args.out)

    model = MatrixModel(args.out).to(device)       # the best epoch, as saved
    temperatures = calibrate(model, val)
    model.save(args.out)
    summary["temperature"] = dict(zip(["goal", "constraints", "selection"], temperatures))
    summary["device"] = device
    (Path(args.out) / "train_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"best epoch {summary['best_epoch']}, temperatures {summary['temperature']}, saved to {args.out}")
    if device == "cuda":
        print(f"peak GPU memory {torch.cuda.max_memory_allocated() / 2 ** 30:.1f} GiB")
