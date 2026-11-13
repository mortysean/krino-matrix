#!/usr/bin/env bash
# 压缩 Q 版小人的动作视频（app/frontend/chibi/<角色>/*.webm），保留透明通道。
#   scripts/compress_chibi.sh [角色...]      不给角色就压全部
# 做法：高最多 576 像素（页面上显示不到更大）、时域降噪（生成的视频每帧有细碎闪动，去掉后好压很多）、VP9 CRF 40，透明通道保留。
# 鲸鱼一段 1.3 MB → 约 0.9 MB，放大两倍看头发略软一点，正常大小看不出差别。
# 压过的角色在 chibi.json 里记 "encoded"，再跑会跳过，不会一遍遍重压掉画质。原片在 git 历史里。
# 需要带 libvpx 的 ffmpeg：默认用 envs/krino_matrix 里 imageio-ffmpeg 自带的那个，也可以用 FFMPEG=… 指定。
set -euo pipefail
cd "$(dirname "$0")/.."
FF=${FFMPEG:-$(ls /home/*/anaconda3/envs/krino_matrix/lib/python3.*/site-packages/imageio_ffmpeg/binaries/ffmpeg-* 2>/dev/null | head -1)}
FF=${FF:-ffmpeg}
H=${HEIGHT:-576}
CRF=${CRF:-40}
TAG="vp9 h${H} crf${CRF} hqdn3d"
roles=("$@")
[ ${#roles[@]} -eq 0 ] && roles=($(ls app/frontend/chibi))
for role in "${roles[@]}"; do
  dir=app/frontend/chibi/$role
  if grep -q '"encoded"' "$dir/chibi.json"; then echo "$role：已压过，跳过"; continue; fi
  tmp=$(mktemp -d)
  before=$(du -sb "$dir" | cut -f1)
  for f in "$dir"/*.webm; do
    # 解码一定要用 libvpx（ffmpeg 自带的 vp9 解码器会把透明通道丢掉）。
    # hqdn3d 不认带透明通道的格式（会悄悄转成不透明的），所以颜色和透明通道分开：颜色降噪缩放，透明通道只缩放，再合回去
    S="scale=-2:'min($H,ih)':flags=lanczos,setsar=1"
    "$FF" -hide_banner -loglevel error -y -c:v libvpx-vp9 -i "$f" \
      -filter_complex "[0:v]format=yuva420p,split[c][a];[c]hqdn3d=0:0:6:6,$S[cs];[a]alphaextract,$S[as];[cs][as]alphamerge,format=yuva420p" \
      -c:v libvpx-vp9 -pix_fmt yuva420p -crf "$CRF" -b:v 0 -row-mt 1 -deadline good -cpu-used 2 -an \
      "$tmp/$(basename "$f")" &
    if [ "$(jobs -r | wc -l)" -ge "$(nproc)" ]; then wait -n; fi
  done
  wait
  for f in "$tmp"/*.webm; do  # 压完反而更大的（很少见）保留原片
    if [ "$(stat -c %s "$f")" -lt "$(stat -c %s "$dir/$(basename "$f")")" ]; then mv "$f" "$dir/"; fi
  done
  rm -rf "$tmp"
  python3 - "$dir/chibi.json" "$TAG" <<'EOF'
import json, sys
p, tag = sys.argv[1], sys.argv[2]
d = json.load(open(p, encoding="utf-8")); d["encoded"] = tag
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
EOF
  echo "$role：$((before / 1024)) KB → $(( $(du -sb "$dir" | cut -f1) / 1024 )) KB"
done
