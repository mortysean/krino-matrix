#!/usr/bin/env bash
# 在服务器上以 root 运行（scripts/deploy.sh 会调用）。可重复运行。
# 需要的环境变量：DEST（安装目录，默认 ~APP_USER/krino-world）、SITES（Caddy 站点，逗号分隔）、LANDING（1 = 同时提供 krinomatrix.com 品牌首页）、APP_USER（运行服务的用户）
set -euo pipefail
DEST="${DEST:-$(getent passwd "$APP_USER" | cut -d: -f6)/krino-world}"
cd "$DEST"
log() { echo "[setup] $*" >&2; }
export DEBIAN_FRONTEND=noninteractive

# ---------- 系统软件 ----------
need=()
command -v psql >/dev/null || need+=(postgresql postgresql-contrib)
command -v python3.11 >/dev/null || need+=(python3.11 python3.11-venv python3.11-dev)
dpkg -s espeak-ng >/dev/null 2>&1 || need+=(espeak-ng)   # Kokoro 英文发音的兜底
if [ ${#need[@]} -gt 0 ]; then
  log "安装：${need[*]}"
  if [[ " ${need[*]} " == *python3.11* ]] && ! apt-cache policy python3.11 | grep -q Candidate:.*[0-9]; then
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
[ -x .venv/bin/python ] || as_app python3.11 -m venv .venv
as_app .venv/bin/python -m pip install -q --upgrade pip
as_app .venv/bin/python -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu   # 只用 CPU，体积小得多
as_app .venv/bin/python -m pip install -q -r requirements.txt
as_app .venv/bin/python -c "import spacy; spacy.load('en_core_web_sm')" 2>/dev/null || as_app .venv/bin/python -m spacy download en_core_web_sm || true
as_app .venv/bin/python scripts/fetch_assets.py || log "素材下载失败：语音会退回浏览器朗读"
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
SNIPPET=/etc/caddy/krino-world.caddy
{
  echo "# KRINO WORLD（scripts/server_setup.sh 生成，重新部署会覆盖）"
  echo "$SITES {"
  echo "	encode gzip"
  echo "	reverse_proxy 127.0.0.1:8630 {"
  echo "		flush_interval -1   # SSE 流式回复：不缓冲"
  echo "	}"
  echo "	request_body {"
  echo "		max_size 16MB"
  echo "	}"
  echo "}"
  if [ "${LANDING:-0}" = 1 ]; then
    # 品牌首页也由后端提供（app/landing，挂在 /landing/）：Caddy 读不了用户主目录，也不用放宽权限
    echo "krinomatrix.com {"
    echo "	encode gzip"
    echo "	handle /static/* {"
    echo "		reverse_proxy 127.0.0.1:8630"
    echo "	}"
    echo "	handle {"
    echo "		rewrite * /landing{uri}"
    echo "		reverse_proxy 127.0.0.1:8630"
    echo "	}"
    echo "}"
    echo "www.krinomatrix.com {"
    echo "	redir https://krinomatrix.com{uri} permanent"
    echo "}"
  fi
} > "$SNIPPET"
CF=/etc/caddy/Caddyfile
# 只有 Caddy 安装包自带的欢迎页配置（:80 + /usr/share/caddy）也算空的，可以接管
stock() { [ "$(grep -vE '^\s*(#|$)' "$CF" | tr -d ' \t\n')" = ':80{root*/usr/share/caddyfile_server}' ]; }
if [ ! -s "$CF" ] || grep -q "^# managed-by: krino-world" "$CF" || stock; then
  printf '# managed-by: krino-world\nimport %s\n' "$SNIPPET" > "$CF"
  systemctl enable --now caddy >/dev/null
  systemctl reload caddy || systemctl restart caddy
  log "Caddy 已配置：$SITES"
elif grep -qF "import $SNIPPET" "$CF"; then
  (systemctl reload caddy 2>/dev/null || true)
  log "Caddy 已经引用了 $SNIPPET，已重新加载"
else
  log "这台机器上已有别的 Caddy 配置（$CF），没有改动它。"
  log "要启用 KRINO WORLD，请在 $CF 末尾加一行：  import $SNIPPET  然后重新加载 Caddy。"
fi
