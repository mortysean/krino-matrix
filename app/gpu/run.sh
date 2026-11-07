#!/bin/bash
# 算力服务器上启停自建模型服务。只占两张卡：GPU_MAIN 放生图的两个扩散模型，GPU_AUX 放文本编码器 + 语音。
#   ./run.sh start|stop|status|logs [tts|speech|image]
#   tts    = vllm-omni 跑 Qwen3-TTS（127.0.0.1:8650，只对本机）
#   speech = 对外的语音接口（8640）：合成转给 tts，识别用 SenseVoice
#   image  = 对外的生图接口（8641）
set -u
cd "$(dirname "$0")"
source ~/miniconda3/etc/profile.d/conda.sh
conda activate krino_matrix
export CUDA_DEVICE_ORDER=PCI_BUS_ID  # 编号和 nvidia-smi 一致（默认最快的卡排前面，会对不上）
export LD_LIBRARY_PATH=$CONDA_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}  # 用环境里的新 libstdc++（系统的太旧，sqlite3/ICU 加载不了）
export VLLM_USE_FLASHINFER_SAMPLER=0  # FlashInfer 采样器要现场用 nvcc 编译，系统的 CUDA 11.5 太旧；用 vllm 自带的
GPU_MAIN=${GPU_MAIN:-2}
GPU_AUX=${GPU_AUX:-4}
MODELS=$(cd .. && pwd)/models
LOGS=../logs
mkdir -p "$LOGS"

start_one() {
  local name=$1
  if [ -f "$LOGS/$name.pid" ] && kill -0 "$(cat "$LOGS/$name.pid")" 2>/dev/null; then echo "$name 已在运行"; return; fi
  case $name in
    tts)
      CUDA_VISIBLE_DEVICES=$GPU_AUX nohup vllm-omni serve "$MODELS/Qwen3-TTS-12Hz-1.7B-Base" --omni --host 127.0.0.1 --port 8650 \
        --served-model-name qwen3-tts --trust-remote-code >"$LOGS/tts.log" 2>&1 & ;;
    speech)
      CUDA_VISIBLE_DEVICES=$GPU_AUX nohup python -m uvicorn speech_server:app --host 0.0.0.0 --port 8640 >"$LOGS/speech.log" 2>&1 & ;;
    image)
      CUDA_VISIBLE_DEVICES=$GPU_MAIN,$GPU_AUX nohup python -m uvicorn image_server:app --host 0.0.0.0 --port 8641 >"$LOGS/image.log" 2>&1 & ;;
  esac
  echo $! >"$LOGS/$name.pid"
  echo "$name 启动中，日志 $LOGS/$name.log"
}

stop_one() {
  [ -f "$LOGS/$1.pid" ] || return 0
  local pid; pid=$(cat "$LOGS/$1.pid")
  pkill -TERM -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null && echo "$1 已停止"
  rm -f "$LOGS/$1.pid"
}

which=${2:-all}
names=(tts speech image); [ "$which" != all ] && names=("$which")
case ${1:-status} in
  start) for n in "${names[@]}"; do start_one "$n"; done ;;
  stop) for n in "${names[@]}"; do stop_one "$n"; done ;;
  status) curl -s --noproxy '*' localhost:8640/health; echo; curl -s --noproxy '*' localhost:8641/health; echo
          nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv -i "$GPU_MAIN,$GPU_AUX" ;;
  logs) tail -n 50 -f "$LOGS/${2:-image}.log" ;;
esac
