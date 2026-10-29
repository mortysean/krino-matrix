#!/usr/bin/env bash
# Score checkpoints on the zh / en test sets; the report goes to data/benchmark/report.md. Needs a GPU.
#
#     bash scripts/benchmark.sh [checkpoint ...]   # default: model/checkpoints/mmbert-uncertainty
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/anaconda3/envs/krino_matrix/bin/python}"
[ -x "$PY" ] || PY=python
cd "$ROOT"

[ $# -gt 0 ] || set -- model/checkpoints/mmbert-uncertainty
"$PY" -u model/training/benchmark.py "$@" --out data/benchmark
