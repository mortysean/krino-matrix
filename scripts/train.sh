#!/usr/bin/env bash
# Train a Matrix model the way the web app's checkpoint was trained: mmBERT-base encoder, all three heads from
# scratch, uncertainty loss weighting, 4 epochs, on data/krino_matrix/{zh,en}. Needs a GPU.
#
#     bash scripts/train.sh [out_dir] [seed]       # default: model/checkpoints/mmbert-uncertainty-<date>, seed 0
#
# Uses model/checkpoints/mmbert-base when it is there, otherwise downloads jhu-clsp/mmBERT-base.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/anaconda3/envs/krino_matrix/bin/python}"
[ -x "$PY" ] || PY=python
cd "$ROOT"

OUT=${1:-model/checkpoints/mmbert-uncertainty-$(date +%Y%m%d-%H%M)}
SEED=${2:-0}
BASE=model/checkpoints/mmbert-base
[ -f "$BASE/config.json" ] || BASE=jhu-clsp/mmBERT-base
[ -e "$OUT" ] && { echo "$OUT already exists; pass another output directory" >&2; exit 1; }

"$PY" -u model/training/train.py data/krino_matrix/zh data/krino_matrix/en \
    --base "$BASE" --weighting uncertainty --freeze-below 0 --max-length 2048 \
    --micro-batch 2 --grad-accum 16 --epochs 4 --seed "$SEED" --out "$OUT"
