#!/bin/bash
# 算力服务器上启停自建模型服务。只占两张卡：GPU_AUX 只放语音（常驻，不和生图抢算力），GPU_MAIN 只放生图（用时才上卡，闲置退回内存）。
#   ./run.sh start|stop|status|logs [tts|speech|image]
#   tts    = vllm-omni 跑 Qwen3-TTS（127.0.0.1:8650，只对本机）
#   speech = 对外的语音接口（8640）：合成转给 tts，识别用 SenseVoice
#   image  = 对外的生图接口（8641）（现在生图走百炼，默认不启动）
#   design = vllm-omni 跑 Qwen3-TTS VoiceDesign（127.0.0.1:8651，只对本机）：按一句描述设计角色的专属声音，
#            设计出的参考音频再交给 tts 克隆，之后每句话都是这个声音
#   omni   = Qwen3-Omni 直接听（127.0.0.1:8660，只对本机；经隧道映射到网站服务器的 18660）
#   tunnel = 把语音接口、生图接口反向映射到两台网站服务器的 127.0.0.1:18640、18641（算力服务器在内网，网站服务器连不进来）
#            用受限密钥 ~/.ssh/krino_tunnel：在网站服务器上只能开这两个端口，不能登录执行命令。断线自动重连。
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
TUNNEL_HOSTS=${TUNNEL_HOSTS:-"ubuntu@43.153.189.97 sean@111.229.152.63"}  # 海外版、国内版

tunnel_loop() {  # 一个网站服务器一个循环：ssh 断了 5 秒后重连
  local host=$1
  while true; do
    env -u LD_LIBRARY_PATH /usr/bin/ssh -N -i ~/.ssh/krino_tunnel -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -o StrictHostKeyChecking=accept-new -R 127.0.0.1:18640:127.0.0.1:8640 -R 127.0.0.1:18641:127.0.0.1:8641 \
      -R 127.0.0.1:18660:127.0.0.1:8660 "$host"
    echo "$(date '+%F %T') $host 隧道断开，5 秒后重连"
    sleep 5
  done
}

tts_deploy() {  # 官方配置上只改显存：默认两段各按整卡 30% 预留（48G 卡上光缓存就 9.5G，够 21 路长句同时合成），用不了这么多
  cat >"$LOGS/tts_deploy.yaml" <<EOF
base_config: $CONDA_PREFIX/lib/python3.11/site-packages/vllm_omni/deploy/qwen3_tts.yaml
stages:
  - stage_id: 0
    gpu_memory_utilization: ${TTS_MEM:-0.16}  # 48G 卡：权重 4.1G + 运行约 1G + 缓存约 2.5G（够 5 路长句、十几路短句同时说）
    max_num_seqs: 16
  - stage_id: 1
    max_num_seqs: 16
EOF
}

design_deploy() {  # 设计声音很少用：显存给少一点，一次只设计一个
  cat >"$LOGS/design_deploy.yaml" <<EOF
base_config: $CONDA_PREFIX/lib/python3.11/site-packages/vllm_omni/deploy/qwen3_tts.yaml
stages:
  - stage_id: 0
    gpu_memory_utilization: ${DESIGN_MEM:-0.13}
    max_num_seqs: 2
  - stage_id: 1
    max_num_seqs: 2
EOF
}

start_one() {
  local name=$1
  if [ -f "$LOGS/$name.pid" ] && kill -0 "$(cat "$LOGS/$name.pid")" 2>/dev/null; then echo "$name 已在运行"; return; fi
  case $name in
    tts)
      tts_deploy
      CUDA_VISIBLE_DEVICES=$GPU_AUX nohup vllm-omni serve "$MODELS/Qwen3-TTS-12Hz-1.7B-Base" --omni --host 127.0.0.1 --port 8650 \
        --served-model-name qwen3-tts --trust-remote-code --deploy-config "$LOGS/tts_deploy.yaml" >"$LOGS/tts.log" 2>&1 & ;;
    design)
      design_deploy
      CUDA_VISIBLE_DEVICES=$GPU_AUX nohup vllm-omni serve "$MODELS/Qwen3-TTS-12Hz-1.7B-VoiceDesign" --omni --host 127.0.0.1 --port 8651 \
        --served-model-name qwen3-tts-design --trust-remote-code --deploy-config "$LOGS/design_deploy.yaml" >"$LOGS/design.log" 2>&1 & ;;
    speech)
      CUDA_VISIBLE_DEVICES=$GPU_AUX nohup python -m uvicorn speech_server:app --host 0.0.0.0 --port 8640 >"$LOGS/speech.log" 2>&1 & ;;
    image)
      CUDA_VISIBLE_DEVICES=$GPU_MAIN nohup python -m uvicorn image_server:app --host 0.0.0.0 --port 8641 >"$LOGS/image.log" 2>&1 & ;;
    omni)  # “直接听”：Qwen3-Omni 只跑听和理解（thinker），OpenAI 兼容接口，8660
      CUDA_VISIBLE_DEVICES=$GPU_MAIN nohup vllm-omni serve "$MODELS/Qwen3-Omni-30B-A3B-Instruct-AWQ" --omni --host 127.0.0.1 --port 8660 \
        --served-model-name qwen3-omni --trust-remote-code --deploy-config omni_thinker_1gpu.yaml --dtype float16 \
        --stage-init-timeout 1800 --init-timeout 2400 >"$LOGS/omni.log" 2>&1 & ;;  # 机器忙时读权重很慢：给足启动时间；权重本来就是 fp16
    tunnel)
      (for h in $TUNNEL_HOSTS; do tunnel_loop "$h" & done; wait) >"$LOGS/tunnel.log" 2>&1 &
      ;;
  esac
  echo $! >"$LOGS/$name.pid"
  echo "$name 启动中，日志 $LOGS/$name.log"
}

stop_one() {
  [ -f "$LOGS/$1.pid" ] || return 0
  local pid; pid=$(cat "$LOGS/$1.pid")
  [ "$1" = tunnel ] && for c in $(pgrep -P "$pid"); do pkill -TERM -P "$c"; kill "$c"; done 2>/dev/null
  pkill -TERM -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null && echo "$1 已停止"
  rm -f "$LOGS/$1.pid"
}

which=${2:-all}
names=(tts design speech omni tunnel); [ "$which" != all ] && names=("$which")  # 生图已改走百炼，默认不启动 image
case ${1:-status} in
  start) for n in "${names[@]}"; do start_one "$n"; done ;;
  stop) for n in "${names[@]}"; do stop_one "$n"; done ;;
  status) curl -s --noproxy '*' localhost:8640/health; echo; curl -s --noproxy '*' localhost:8660/v1/models | head -c 200; echo
          nvidia-smi --query-gpu=index,memory.used,utilization.gpu --format=csv -i "$GPU_MAIN,$GPU_AUX" ;;
  logs) tail -n 50 -f "$LOGS/${2:-image}.log" ;;
esac
