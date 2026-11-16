#!/usr/bin/env bash
# 把 KRINO WORLD 部署到一台 Ubuntu 22.04 服务器（可重复运行：第一次装好，之后就是更新）。
#
#   scripts/deploy.sh global ubuntu@43.153.189.97     国际站 krinomatrix.com/global/ 的源站，应用在 /global/products/world/
#   scripts/deploy.sh cn     sean@111.229.152.63      中国大陆站 krinomatrix.com/cn/ 的源站，应用在 /cn/products/world/
# 应用不再有自己的子域名（app.、cn.、api.、api-cn. 的 DNS 已删除），全部在 krinomatrix.com 下。
#
# 做的事：同步代码和素材 → 装 PostgreSQL / Python 3.11 / Caddy → 建库、迁移 → systemd 服务 krino-world → Caddy 自动 HTTPS。
# user@host 是能 sudo 的管理账号，只用来装软件、写 systemd/Caddy；代码和服务都在专用的非 sudo 账号 krino 下（APP_USER 可改）：
# 装在 /home/krino/krino-world，配置在 /home/krino/krino-world/.env（第一次从本机的 .env 和模板生成，之后不覆盖，改了要手动同步）。
# 需要：本机能免密 SSH 登录管理账号和 krino，管理账号能 sudo。sudo 要密码时用环境变量传进来（从标准输入交给 sudo，不落盘）：
#   SUDO_PASS=... scripts/deploy.sh cn sean@111.229.152.63
# 只改 Caddy 或只更新官网（不重装应用）：  SUDO_PASS=... scripts/deploy.sh cn sean@... caddy
# 每次部署前自动拍快照（scripts/snapshot.sh：代码、.venv、.env、数据库，保留最近 5 份）。回滚到上一份 / 指定一份：
#   SUDO_PASS=... scripts/deploy.sh cn sean@... rollback [snap-名字]      加 RESTORE_DB=1 连数据库一起回退
#   scripts/deploy.sh cn sean@... snapshots                              列出快照
# 官网两台都要更新；第一次上线先部署海外服务器（它替国内服务器转发证书验证），再部署国内服务器。
# 国内版自动用国内镜像（腾讯云 PyPI、阿里云 PyTorch、hf-mirror）和系统自带的 Python 3.10，国外源在境内太慢。
set -euo pipefail
EDITION="${1:?用法：$0 cn|global user@host}"
TARGET="${2:?用法：$0 cn|global user@host}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${APP_USER:-krino}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$TARGET")
APP_TARGET="$APP_USER@${TARGET#*@}"
APP_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$APP_TARGET")
DEST="$("${APP_SSH[@]}" 'echo $HOME')/krino-world"
log() { echo "[deploy:$EDITION] $*" >&2; }

case "$EDITION" in
  global) SITES=""; LANDING=1; OTHER=https://krinomatrix.com/cn/products/world/
          CADDY="WWW_TO=https://krinomatrix.com SITE_REGION=global PEER_ORIGIN=${CN_IP:-111.229.152.63} PEER_ACME=${CN_IP:-111.229.152.63}:80"; MIRRORS="" ;;
  cn)     SITES=""; LANDING=1; OTHER=https://krinomatrix.com/global/products/world/
          CADDY="WWW_TO=https://krinomatrix.com SITE_REGION=cn PEER_ORIGIN=${GLOBAL_IP:-43.153.189.97}"
          MIRRORS="PYTHON=python3.10 PIP_INDEX=https://mirrors.cloud.tencent.com/pypi/simple TORCH_FIND=https://mirrors.aliyun.com/pytorch-wheels/cpu/ HF_ENDPOINT=https://hf-mirror.com MODEL_SOURCE=modelscope NO_SPACY=1" ;;
  *) echo "版本只能是 cn 或 global"; exit 1 ;;
esac

MODE="${3:-}"
BAK="$(dirname "$DEST")/deploy-bak"
sudo_run() { printf '%s\n' "${SUDO_PASS:-}" | "${SSH[@]}" "sudo -S -p '' env DEST='$DEST' SITES='$SITES' LANDING=$LANDING APP_USER=$APP_USER $CADDY $*"; }
case "$MODE" in
  snapshots) "${APP_SSH[@]}" "bash $BAK/snapshot.sh list"; exit ;;
  rollback)  sudo_run "${RESTORE_DB:+RESTORE_DB=1} bash $BAK/snapshot.sh restore ${4:-}"; exit ;;
esac

log "部署前拍快照"
"${APP_SSH[@]}" "DEST=$DEST bash -s take" < "$ROOT/scripts/snapshot.sh"
"${APP_SSH[@]}" "mkdir -p $BAK && cat > $BAK/snapshot.sh" < "$ROOT/scripts/snapshot.sh"   # 回滚用这一份：不随代码一起被覆盖

log "生成官网（app/landing_src/build.py）"
"${LANDING_PY:-$(command -v ~/anaconda3/envs/krino_matrix/bin/python || command -v python3)}" "$ROOT/app/landing_src/build.py" >&2

log "同步代码到 $APP_TARGET:$DEST"
"${APP_SSH[@]}" "mkdir -p $DEST"
rsync -az --delete --exclude-from=- "$ROOT/" "$APP_TARGET:$DEST/" <<'EOF'
.git/
.claude/
.deployed
.venv/
*.log
.env
.env.*
!.env.example
!.env.global.example
.run/
.backup/
.pytest_cache/
__pycache__/
data/pgdata/
data/media/
data/models/qwen3-tts/
data/models/voices/
data/models/kokoro-zh/
data/models/anime-seg/
model/__pycache__/
data/krino_matrix/
data/benchmark/
model/checkpoints/
archive/
experiments/
app/e2e/node_modules/
app/e2e/shots/
pet/
EOF

# 服务器上的配置：第一次生成，之后保留（里面有密钥）。
# 写的时候用 noclobber：文件已经在就绝不覆盖。只靠上面这次检查不够——SSH 偶尔连不上时 test 也返回失败，
# 2026-11-13 杭州的 .env 就这样被一份新生成的默认配置盖掉了（数据库密码变了，迁移连不上）
if ! "${APP_SSH[@]}" "test -f $DEST/.env"; then
  KEY="$(grep -E '^(OPENROUTER_API_KEY|LLM_OPENROUTER_API_KEY)=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
  ICP="$(grep -E '^ICP_NUMBER=' "$ROOT/.env" | head -1 | cut -d= -f2-)"
  DBPW="$(openssl rand -hex 16)"
  log "生成服务器配置 $DEST/.env"
  "${APP_SSH[@]}" "umask 077; set -o noclobber; cat > $DEST/.env" <<EOF || { log "$DEST/.env 已经存在，保留原样"; }
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
TTS_PROVIDER=dashscope
# 填上密钥后语音更像真人；没填时自动用本地 Kokoro。改完：sudo systemctl restart krino-world
# DASHSCOPE_API_KEY=
VLM_PROVIDER=mock
STT_PROVIDER=browser
KRINO_POLICY=rules
EOF
fi

# 记下部署的是哪个提交（有没提交的改动时带 -dirty），快照按它命名
REV="$(git -C "$ROOT" rev-parse --short HEAD)$(git -C "$ROOT" diff --quiet HEAD || echo -dirty)"
"${APP_SSH[@]}" "printf 'commit=%s\ntime=%s\n' $REV $(date +%Y%m%d-%H%M%S) > $DEST/.deployed"

log "安装与配置（服务器上执行 scripts/server_setup.sh）"
STEP="server_setup"; [ "$MODE" = caddy ] && STEP="caddy_setup"
sudo_run "$MIRRORS ${SKIP_ASSETS:+SKIP_ASSETS=1} bash $DEST/scripts/$STEP.sh"
log "完成：krinomatrix.com/$EDITION/（应用在 /$EDITION/products/world/）"
