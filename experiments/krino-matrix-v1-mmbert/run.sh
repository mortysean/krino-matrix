#!/usr/bin/env bash
# Krino Matrix from mmBERT-base: three variants, 3 seeds each; the encoder starts from its pretrained weights and every
# head starts from scratch. See README.md.
#
#     bash experiments/krino-matrix-v1-mmbert/run.sh
#
# Rerunnable: a run with a calibrated train_summary.json is skipped, and a model already scored is not scored again.
set -euo pipefail
ROOT=/home/seanhuang2004/Krino-Matrix
EXP=$ROOT/experiments/krino-matrix-v1-mmbert
PY=~/anaconda3/envs/krino_matrix/bin/python
BASE=$ROOT/checkpoints/base/mmbert-base
cd "$ROOT"
mkdir -p "$EXP/checkpoints" "$EXP/logs" "$EXP/results"

[ -f "$BASE/config.json" ] || { echo "missing $BASE: download jhu-clsp/mmBERT-base there first" >&2; exit 78; }
if [ -z "$($PY -c 'import torch; print(torch.cuda.is_available() or "")' 2>/dev/null | tail -1)" ]; then
    echo "no CUDA device" >&2
    exit 78
fi

VARIANTS=(
    "mmbert-uncertainty|--weighting uncertainty"
    "mmbert-fixed|--weighting fixed"
    "mmbert-selection-only|--weighting uncertainty --tasks selection"
)

trained() { grep -q '"temperature"' "$1/train_summary.json" 2>/dev/null; }

train() {   # name, seed, extra arguments
    local name=$1 seed=$2 extra=$3
    local out=$EXP/checkpoints/$name
    [ "$seed" -gt 0 ] && out=$out-s$seed
    if trained "$out"; then
        echo "$(date '+%F %T') skip $(basename "$out"): already trained"
        return
    fi
    echo "$(date '+%F %T') training $(basename "$out")"
    # shellcheck disable=SC2086
    $PY -u examples/matrix_train.py data/krino_matrix/zh data/krino_matrix/en \
        --base "$BASE" --freeze-below 0 --max-length 2048 \
        --micro-batch 2 --grad-accum 16 --epochs 4 --seed "$seed" $extra \
        --out "$out" > "$EXP/logs/$(basename "$out").log" 2>&1
    tail -2 "$EXP/logs/$(basename "$out").log"
}

benchmark() {   # checkpoint names
    local dirs=() name
    for name in "$@"; do dirs+=("$EXP/checkpoints/$name"); done
    echo "$(date '+%F %T') benchmarking $*"
    $PY -u benchmark/run_krino_matrix.py "${dirs[@]}" \
        --reference mmbert-uncertainty --out "$EXP/results" >> "$EXP/logs/benchmark.log" 2>&1
}

# One seed at a time, benchmarked as soon as it is done
for seed in 0 1 2; do
    names=()
    for v in "${VARIANTS[@]}"; do
        name=${v%%|*}
        train "$name" "$seed" "${v#*|}"
        [ "$seed" -gt 0 ] && name=$name-s$seed
        [ -f "$EXP/results/$name.json" ] || names+=("$name")
    done
    [ ${#names[@]} -gt 0 ] && benchmark "${names[@]}"
done
echo "$(date '+%F %T') done: $EXP/results/report.md"
