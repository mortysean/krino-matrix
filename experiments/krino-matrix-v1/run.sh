#!/usr/bin/env bash
# Krino Matrix v1: three-head model vs. selection-only ablation vs. original Laya, 3 seeds each. See README.md.
#
#     bash experiments/krino-matrix-v1/run.sh
#
# Rerunnable: a run whose checkpoint already has a calibrated train_summary.json is skipped, and the benchmark only
# scores the models it is given, merging them into results/report.md. Refuses to start without a CUDA device.
set -euo pipefail
ROOT=/home/seanhuang2004/Krino-Matrix
EXP=$ROOT/experiments/krino-matrix-v1
PY=~/anaconda3/envs/krino_matrix/bin/python
cd "$ROOT"
mkdir -p "$EXP/checkpoints" "$EXP/logs" "$EXP/results"

if [ -z "$($PY -c 'import torch; print(torch.cuda.is_available() or "")' 2>/dev/null | tail -1)" ]; then
    echo "no CUDA device" >&2
    exit 78
fi

# name, extra training arguments
VARIANTS=(
    "multilingual-uncertainty|--weighting uncertainty"
    "multilingual-fixed|--weighting fixed"
    "multilingual-selection-only|--weighting uncertainty --tasks selection"
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
        --base checkpoints/laya/multilingual-base --freeze-below 0 --max-length 2048 \
        --micro-batch 2 --grad-accum 16 --epochs 4 --seed "$seed" $extra \
        --out "$out" > "$EXP/logs/$(basename "$out").log" 2>&1
    tail -2 "$EXP/logs/$(basename "$out").log"
}

benchmark() {   # checkpoint names; the original Laya baseline is added on the first call
    local dirs=() name
    for name in "$@"; do dirs+=("$EXP/checkpoints/$name"); done
    local laya=()
    [ -f "$EXP/results/laya-typed-decisions-base.json" ] || laya=(--laya checkpoints/laya/typed-decisions-base)
    echo "$(date '+%F %T') benchmarking $*"
    $PY -u benchmark/run_krino_matrix.py "${dirs[@]}" "${laya[@]}" \
        --reference multilingual-uncertainty --out experiments/krino-matrix-v1/results >> "$EXP/logs/benchmark.log" 2>&1
}

# One seed at a time, benchmarked as soon as it is done, so the comparison is readable after the first round
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
