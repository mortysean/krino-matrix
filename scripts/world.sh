#!/usr/bin/env bash
# KRINO WORLD 统一管理脚本。不需要先 conda activate。
#
#   scripts/world.sh setup                  首次：装依赖、建 .env、初始化数据库、下载语音模型和 Live2D 示例
#   scripts/world.sh run [--reload]         前台运行（--reload：改后端代码自动重启）
#   scripts/world.sh start|stop|status|logs 后台运行（日志在 .run/world.log）
#   scripts/world.sh db init|start|stop|status|migrate|revision "说明"|psql
#   scripts/world.sh test [pytest 参数]     后端测试（独立的测试库 krino_world_test，离线 mock 模型）
#   scripts/world.sh e2e                    浏览器端到端测试（需要服务在跑，见 app/e2e/README.md）
#
# 环境变量：PYTHON（默认 krino_matrix conda 环境）、PG_BIN（PostgreSQL 可执行文件目录）、PGPORT（默认 5433）
#           HOST / PORT 覆盖 .env；WORLD_MANAGE_PG=0 时 run 不启动/停止数据库
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/.run"
PGDATA="${PGDATA:-$ROOT/data/pgdata}"
PGPORT="${PGPORT:-5433}"
export PGDATA PGPORT
mkdir -p "$RUN"

log() { echo "[world] $*" >&2; }

# ---------- 环境 ----------
PY="${PYTHON:-}"
for c in "$PY" "$HOME"/{anaconda3,miniconda3,miniforge3}/envs/krino_matrix/bin/python; do
  if [ -n "$c" ] && [ -x "$c" ]; then PY="$c"; break; fi
done
[ -x "${PY:-}" ] || PY="$(command -v python3)"

pg_bin() {
  local d
  for d in "${PG_BIN:-}" "$(dirname "$PY")" "$HOME"/{anaconda3,miniconda3,miniforge3}/envs/*/bin /usr/lib/postgresql/*/bin; do
    if [ -n "$d" ] && [ -x "$d/pg_ctl" ] && [ -x "$d/initdb" ]; then echo "$d"; return; fi
  done
  if command -v pg_ctl >/dev/null; then dirname "$(command -v pg_ctl)"; return; fi
  log "找不到 PostgreSQL（pg_ctl / initdb），请安装或设置 PG_BIN"; exit 1
}

load_env() {  # 从 .env 读 HOST / PORT（环境变量优先）
  local key val
  if [ -f "$ROOT/.env" ]; then
    for key in HOST PORT; do
      if [ -z "${!key:-}" ]; then
        val="$(grep -E "^${key}=" "$ROOT/.env" | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//')" || true
        [ -n "$val" ] && export "$key=$val"
      fi
    done
  fi
  HOST="${HOST:-127.0.0.1}"; PORT="${PORT:-8630}"
}

urls() {  # 浏览器能打开的地址：监听 0.0.0.0 时列出局域网 IP
  case "$HOST" in
    0.0.0.0|::) local ip out="http://127.0.0.1:$PORT"
                for ip in $(hostname -I 2>/dev/null); do [[ "$ip" == *:* ]] || out+="  http://$ip:$PORT"; done
                echo "$out" ;;
    *) echo "http://$HOST:$PORT" ;;
  esac
}

# ---------- 数据库 ----------
PSQL() { "$(pg_bin)/psql" -h localhost -p "$PGPORT" -U postgres "$@"; }
pg_running() { "$(pg_bin)/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; }
pg_start() { "$(pg_bin)/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" -o "-p $PGPORT -k /tmp" -w start >&2; }

db_init() {
  local bin; bin="$(pg_bin)"
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    "$bin/initdb" -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8 --locale=C >/dev/null
    log "已初始化数据库目录 $PGDATA"
  fi
  pg_running || pg_start
  PSQL -tc "SELECT 1 FROM pg_roles WHERE rolname='krino'" | grep -q 1 || PSQL -qc "CREATE ROLE krino LOGIN PASSWORD 'krino'"
  local db
  for db in krino_world krino_world_test; do
    PSQL -tc "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 || PSQL -qc "CREATE DATABASE $db OWNER krino"
  done
  db_migrate
  log "PostgreSQL 就绪：端口 $PGPORT，库 krino_world / krino_world_test"
}

db_migrate() { (cd "$ROOT/app/backend" && "$PY" -m alembic upgrade head); }

cmd_db() {
  case "${1:-}" in
    init) db_init ;;
    start) pg_running && log "PostgreSQL 已在运行" || pg_start ;;
    stop) "$(pg_bin)/pg_ctl" -D "$PGDATA" -w stop ;;
    status) "$(pg_bin)/pg_ctl" -D "$PGDATA" status ;;
    migrate) db_migrate ;;
    revision) [ -n "${2:-}" ] || { log "用法：$0 db revision \"说明\""; exit 1; }
              (cd "$ROOT/app/backend" && "$PY" -m alembic revision --autogenerate -m "$2") ;;
    psql) shift; PSQL -d krino_world "$@" ;;
    *) echo "用法: $0 db init|start|stop|status|migrate|revision \"说明\"|psql"; exit 1 ;;
  esac
}

# ---------- 运行 ----------
cmd_run() {
  local reload=()
  [ "${1:-}" = "--reload" ] && reload=(--reload --reload-dir app)
  load_env
  local started=0
  if [ "${WORLD_MANAGE_PG:-1}" = 1 ] && ! pg_running; then pg_start; started=1; fi
  log "KRINO WORLD：$(urls)"
  cd "$ROOT/app/backend"
  set +e
  "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers 1 "${reload[@]}"
  local rc=$?
  set -e
  [ "$started" = 1 ] && "$(pg_bin)/pg_ctl" -D "$PGDATA" -w stop >/dev/null 2>&1 || true
  return $rc
}

cmd_start() {
  load_env
  if [ -f "$RUN/world.pid" ] && kill -0 "$(cat "$RUN/world.pid")" 2>/dev/null; then log "已经在运行（$0 status）"; return; fi
  pg_running || pg_start
  WORLD_MANAGE_PG=0 nohup "$0" run >"$RUN/world.log" 2>&1 &
  echo $! >"$RUN/world.pid"
  local i
  for i in $(seq 1 40); do
    if curl -s --max-time 1 --noproxy '*' -o /dev/null "http://$HOST:$PORT/api/health"; then log "已启动：$(urls)"; return; fi
    sleep 0.5
  done
  log "启动超时，看看日志：$0 logs"; exit 1
}

cmd_stop() {
  if [ -f "$RUN/world.pid" ]; then
    local pid; pid="$(cat "$RUN/world.pid")"
    pkill -P "$pid" 2>/dev/null || true; kill "$pid" 2>/dev/null || true
    rm -f "$RUN/world.pid"
    load_env
    local i  # 等端口真正空出来，否则紧接着的 start 会把旧进程当成新启动的
    for i in $(seq 1 20); do
      curl -s --max-time 1 --noproxy '*' -o /dev/null "http://$HOST:$PORT/api/health" || break
      sleep 0.5
    done
    log "已停止"
  else
    log "没有在运行"
  fi
}

cmd_status() {
  load_env
  if curl -s --max-time 2 --noproxy '*' "http://$HOST:$PORT/api/health"; then echo; else log "服务没有响应（http://$HOST:$PORT）"; fi
  pg_running && log "PostgreSQL 运行中（端口 $PGPORT）" || log "PostgreSQL 未运行"
}

# ---------- 测试 ----------
cmd_test() {
  pg_running || pg_start
  cd "$ROOT/app/backend"
  TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg://krino:krino@localhost:$PGPORT/krino_world_test}" \
    "$PY" -m pytest -q "$@"
}

cmd_e2e() {
  load_env
  cd "$ROOT/app/e2e"
  [ -d node_modules ] || npm install --silent
  WORLD_URL="http://$HOST:$PORT" node run.mjs "$@"
}

cmd_setup() {
  "$PY" -m pip install -q -r "$ROOT/requirements.txt"
  [ -f "$ROOT/.env" ] || { cp "$ROOT/.env.example" "$ROOT/.env"; log "已创建 .env，请填写 OPENROUTER_API_KEY（或设 LLM_PROVIDER=mock）"; }
  db_init
  "$PY" "$ROOT/scripts/fetch_assets.py" || log "素材下载失败：语音会退回浏览器朗读，Live2D 示例不可用（之后可以再运行 scripts/fetch_assets.py）"
}

case "${1:-}" in
  setup) cmd_setup ;;
  run) shift; cmd_run "$@" ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  logs) tail -f "$RUN/world.log" ;;
  db) shift; cmd_db "$@" ;;
  test) shift; cmd_test "$@" ;;
  e2e) shift; cmd_e2e "$@" ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
