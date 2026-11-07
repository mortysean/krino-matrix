#!/bin/bash
# 算力服务器上启停自建模型服务。只占两张卡：GPU_MAIN 放生图的两个扩散模型，GPU_AUX 放文本编码器 + 语音。
#   ./run.sh start|stop|status|logs [speech|image]
set -u
cd "$(dirname "$0")"
source ~/miniconda3/etc/profile.d/conda.sh
conda activate krino_matrix
GPU_MAIN=${GPU_MAIN:-2}
GPU_AUX=${GPU_AUX:-4}
LOGS=../logs
mkdir -p "$LOGS"

start_one() {
  local name=$1 port gpus
  case $name in
    speech) port=8640; gpus=$GPU_AUX ;;
    image)  port=8641; gpus=$GPU_MAIN,$GPU_AUX ;;
  esac
  if [ -f "$LOGS/$name.pid" ] && kill -0 "$(cat "$LOGS/$name.pid")" 2>/dev/null; then echo "$name 已在运行"; return; fi
  CUDA_VISIBLE_DEVICES=$gpus nohup python -m uvicorn "${name}_server:app" --host 0.0.0.0 --port $port >"$LOGS/$name.log" 2>&1 &
  echo $! >"$LOGS/$name.pid"
  echo "$name 启动中：端口 $port，显卡 $gpus，日志 $LOGS/$name.log"
}

stop_one() {
  [ -f "$LOGS/$1.pid" ] && kill "$(cat "$LOGS/$1.pid")" 2>/dev/null && echo "$1 已停止"
  rm -f "$LOGS/$1.pid"
}

which=${2:-all}
names=(speech image); [ "$which" != all ] && names=("$which")
case ${1:-status} in
  start) for n in "${names[@]}"; do start_one "$n"; done ;;
  stop) for n in "${names[@]}"; do stop_one "$n"; done ;;
  status) curl -s --noproxy '*' localhost:8640/health; echo; curl -s --noproxy '*' localhost:8641/health; echo
          nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv -i "$GPU_MAIN,$GPU_AUX" ;;
  logs) tail -n 50 -f "$LOGS/${2:-image}.log" ;;
esac
