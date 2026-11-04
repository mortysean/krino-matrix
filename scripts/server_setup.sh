#!/usr/bin/env bash
# 在服务器上以 root 运行（scripts/deploy.sh 会调用）。可重复运行。
# 可选：PYTHON（默认 python3.11）、PIP_INDEX / TORCH_FIND / HF_ENDPOINT（国内镜像）、NO_SPACY=1（不装英文分词模型）
# 需要的环境变量：DEST（安装目录，默认 ~APP_USER/krino-world）、SITES（Caddy 站点，逗号分隔）、LANDING（1 = 同时提供 krinomatrix.com 品牌首页）、APP_USER（运行服务的用户）
set -euo pipefail
DEST="${DEST:-$(getent passwd "$APP_USER" | cut -d: -f6)/krino-world}"
cd "$DEST"
log() { echo "[setup] $*" >&2; }
export DEBIAN_FRONTEND=noninteractive

# ---------- 系统软件 ----------
need=()
command -v psql >/dev/null || need+=(postgresql postgresql-contrib)
PYTHON="${PYTHON:-python3.11}"
command -v "$PYTHON" >/dev/null && "$PYTHON" -c "import venv, ensurepip" 2>/dev/null || need+=("$PYTHON" "$PYTHON-venv" "$PYTHON-dev")
dpkg -s espeak-ng >/dev/null 2>&1 || need+=(espeak-ng)   # Kokoro 英文发音的兜底
if [ ${#need[@]} -gt 0 ]; then
  log "安装：${need[*]}"
  cand="$(apt-cache policy "$PYTHON" 2>/dev/null | awk '/Candidate:/ {print $2}')"   # 不用 grep -q：pipefail 下会误判
  if [[ " ${need[*]} " == *"$PYTHON"* ]] && { [ -z "$cand" ] || [ "$cand" = "(none)" ]; }; then
    apt-get update -q && apt-get install -y -q software-properties-common && add-apt-repository -y ppa:deadsnakes/ppa
  fi
  apt-get update -q && apt-get install -y -q "${need[@]}"
fi
if ! command -v caddy >/dev/null; then
  log "安装 Caddy"
  apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https curl gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

# ---------- 数据库 ----------
DBPW="$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2-)"
systemctl enable --now postgresql >/dev/null
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='krino'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE ROLE krino LOGIN PASSWORD '$DBPW'"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='krino_world'" | grep -q 1 \
  || sudo -u postgres psql -qc "CREATE DATABASE krino_world OWNER krino"

# ---------- Python 环境 ----------
chown -R "$APP_USER" "$DEST"
as_app() { sudo -u "$APP_USER" -H "$@"; }
[ -x .venv/bin/python ] || as_app "$PYTHON" -m venv .venv
PIP=(.venv/bin/python -m pip install -q ${PIP_INDEX:+-i "$PIP_INDEX"})
as_app "${PIP[@]}" --upgrade pip
if [ -n "${TORCH_FIND:-}" ]; then   # 只用 CPU 版，体积小得多；国内从阿里云镜像取
  as_app "${PIP[@]}" "torch==2.9.1+cpu" -f "$TORCH_FIND"
else
  as_app "${PIP[@]}" torch --index-url https://download.pytorch.org/whl/cpu
fi
as_app "${PIP[@]}" -r requirements.txt
if [ -z "${NO_SPACY:-}" ]; then  # 英文发音规则（海外版的 Kokoro 英文音色）要用
  as_app .venv/bin/python -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null || as_app .venv/bin/python -m spacy download en_core_web_sm || true
fi
as_app env ${HF_ENDPOINT:+HF_ENDPOINT="$HF_ENDPOINT"} .venv/bin/python scripts/fetch_assets.py || log "素材下载失败：语音会退回浏览器朗读"
(cd app/backend && as_app ../../.venv/bin/python -m alembic upgrade head)

# ---------- 服务 ----------
cat > /etc/systemd/system/krino-world.service <<EOF
[Unit]
Description=KRINO WORLD
After=network.target postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$DEST/app/backend
ExecStart=$DEST/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8630 --workers 1 --proxy-headers
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable krino-world >/dev/null
systemctl restart krino-world
for i in $(seq 1 40); do curl -s --max-time 1 -o /dev/null http://127.0.0.1:8630/api/health && break; sleep 1; done
curl -s http://127.0.0.1:8630/api/health && echo

# ---------- Caddy（自动 HTTPS） ----------
bash "$DEST/scripts/caddy_setup.sh"
