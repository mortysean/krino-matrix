#!/usr/bin/env bash
# 把 KRINO WORLD 部署到一台 Ubuntu 22.04 服务器（可重复运行：第一次装好，之后就是更新）。
#
#   scripts/deploy.sh global ubuntu@43.153.189.97     海外版：app.krinomatrix.com、api.krinomatrix.com，加品牌首页 krinomatrix.com
#   scripts/deploy.sh cn     sean@111.229.152.63      国内版：cn.krinomatrix.com、api-cn.krinomatrix.com
#
# 做的事：同步代码和素材 → 装 PostgreSQL / Python 3.11 / Caddy → 建库、迁移 → systemd 服务 krino-world → Caddy 自动 HTTPS。
# 装在服务器用户的主目录下：~/krino-world。配置在 ~/krino-world/.env（第一次从本机的 .env 和模板生成，之后不覆盖，改了要手动同步）。
# 需要：本机能免密 SSH 登录，服务器用户能 sudo。sudo 要密码时用环境变量传进来（从标准输入交给 sudo，不落盘）：
#   SUDO_PASS=... scripts/deploy.sh cn sean@111.229.152.63
# 国内版自动用国内镜像（腾讯云 PyPI、阿里云 PyTorch、hf-mirror）和系统自带的 Python 3.10，国外源在境内太慢。
set -euo pipefail
EDITION="${1:?用法：$0 cn|global user@host}"
TARGET="${2:?用法：$0 cn|global user@host}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$TARGET")
DEST="$("${SSH[@]}" 'echo $HOME')/krino-world"
log() { echo "[deploy:$EDITION] $*" >&2; }

case "$EDITION" in
  global) SITES="app.krinomatrix.com, api.krinomatrix.com"; LANDING=1; OTHER=https://cn.krinomatrix.com
          MIRRORS="" ;;
  cn)     SITES="cn.krinomatrix.com, api-cn.krinomatrix.com"; LANDING=0; OTHER=https://app.krinomatrix.com
          MIRRORS="PYTHON=python3.10 PIP_INDEX=https://mirrors.cloud.tencent.com/pypi/simple TORCH_FIND=https://mirrors.aliyun.com/pytorch-wheels/cpu/ HF_ENDPOINT=https://hf-mirror.com NO_SPACY=1" ;;
  *) echo "版本只能是 cn 或 global"; exit 1 ;;
esac

log "同步代码到 $TARGET:$DEST"
"${SSH[@]}" "mkdir -p $DEST"
rsync -az --delete --exclude-from=- "$ROOT/" "$TARGET:$DEST/" <<'EOF'
.git/
.claude/
.env
.env.*
!.env.example
!.env.global.example
.run/
.backup/
.pytest_cache/
__pycache__/
data/pgdata/
data/models/qwen3-tts/
data/models/voices/
data/models/kokoro-zh/
model/__pycache__/
data/krino_matrix/
data/benchmark/
model/checkpoints/
archive/
experiments/
app/e2e/node_modules/
app/e2e/shots/
EOF

# 服务器上的配置：第一次生成，之后保留（里面有密钥）
if ! "${SSH[@]}" "test -f $DEST/.env"; then
  KEY="$(grep -E '^(OPENROUTER_API_KEY|LLM_OPENROUTER_API_KEY)=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
  ICP="$(grep -E '^ICP_NUMBER=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
  DBPW="$(openssl rand -hex 16)"
  log "生成服务器配置 $DEST/.env"
  "${SSH[@]}" "umask 077; cat > $DEST/.env" <<EOF
# KRINO WORLD 服务器配置（$EDITION 版）。由 scripts/deploy.sh 第一次部署时生成，之后不会被覆盖。
SITE_EDITION=$EDITION
DATABASE_URL=postgresql+psycopg://krino:$DBPW@localhost:5432/krino_world
DB_PASSWORD=$DBPW
HOST=127.0.0.1
PORT=8630
OTHER_EDITION_URL=$OTHER
ICP_NUMBER=$( [ "$EDITION" = cn ] && echo "$ICP" )
# POLICE_RECORD_NUMBER=
LLM_PROVIDER=openrouter
LLM_MODEL=~deepseek/deepseek-flash-latest
OPENROUTER_API_KEY=$KEY
LLM_REASONING=off
TTS_PROVIDER=$( [ "$EDITION" = cn ] && echo dashscope || echo openai )
# 填上密钥后语音更像真人；没填时自动用本地 Kokoro。改完：sudo systemctl restart krino-world
$( [ "$EDITION" = cn ] && echo '# DASHSCOPE_API_KEY=' || echo '# OPENAI_API_KEY=' )
VLM_PROVIDER=mock
STT_PROVIDER=browser
KRINO_POLICY=rules
EOF
fi

log "安装与配置（服务器上执行 scripts/server_setup.sh）"
RUN="cd $DEST && sudo -S -p '' env DEST='$DEST' SITES='$SITES' LANDING=$LANDING APP_USER=\$(whoami) $MIRRORS bash scripts/server_setup.sh"
printf '%s\n' "${SUDO_PASS:-}" | "${SSH[@]}" "$RUN"
log "完成。站点：$SITES$( [ "$LANDING" = 1 ] && echo '，krinomatrix.com')"
