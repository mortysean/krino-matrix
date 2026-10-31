#!/usr/bin/env bash
# Run the web app: the frontend on its own port, proxying /api to the backend. Open http://127.0.0.1:$WEB_PORT.
# By default it starts in the background and returns; logs go to .run/serve.log.
#
#     bash scripts/serve.sh [start]                  # build the frontend and serve it in the background; web :6180, API :6181
#     bash scripts/serve.sh start --dev              # hot reload: API with --reload, frontend with vite dev
#     bash scripts/serve.sh stop | restart | status
#     bash scripts/serve.sh logs                     # follow the log (Ctrl-C stops following, not the app)
#     bash scripts/serve.sh fg [--dev]               # run in the foreground; Ctrl-C stops both
#     WEB_PORT=3000 API_PORT=8100 bash scripts/serve.sh
#     WEB_HOST=0.0.0.0 bash scripts/serve.sh         # frontend reachable from other machines
#     KRINO_API=http://10.0.0.5:8000 bash scripts/serve.sh   # frontend only, against a backend running elsewhere
#
# Under WSL with mirrored networking, Windows and WSL share ports, so a port held by a Windows program (an editor's
# port forwarding, another dev server) is busy here too; both sides are checked first.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/anaconda3/envs/krino_matrix/bin/python}"
[ -x "$PY" ] || PY=python
cd "$ROOT"

CMD=start
case "${1:-}" in start|stop|restart|status|logs|fg|run) CMD=$1; shift ;; esac
DEV=$([ "${1:-}" = "--dev" ] && echo 1 || echo "")
API_PORT=${API_PORT:-6181}
export WEB_PORT=${WEB_PORT:-6180}
RUN="$ROOT/.run"
PIDFILE="$RUN/serve.pid"
LOG="$RUN/serve.log"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

holder() {   # who listens on the port, or nothing
    local p=$1 pid
    if ss -ltnH 2>/dev/null | awk '{print $4}' | grep -qE ":$p$"; then echo "a process in Linux"; return; fi
    if command -v netstat.exe >/dev/null 2>&1; then
        pid=$(netstat.exe -ano 2>/dev/null | tr -d '\r' | awk -v p=":$p" '$4 == "LISTENING" && $2 ~ p"$" {print $5; exit}')
        if [ -n "$pid" ]; then
            echo "$(tasklist.exe /FI "PID eq $pid" /FO CSV /NH 2>/dev/null | tr -d '\r' | cut -d, -f1 | tr -d '"') (Windows, PID $pid)"
        fi
    fi
}
check() {    # name, port
    local who
    who=$(holder "$2")
    if [ -n "$who" ]; then
        echo "port $2 ($1) is already used by $who; pick another, e.g. ${1^^}_PORT=$(( $2 + 10 )) bash scripts/serve.sh" >&2
        exit 1
    fi
}

serve() {    # the app itself, in the foreground
    check web "$WEB_PORT"
    [ -n "${KRINO_API:-}" ] || check api "$API_PORT"

    (cd frontend && { [ -d node_modules ] || npm install; } && { [ -n "$DEV" ] || npm run build; })

    if [ -z "${KRINO_API:-}" ]; then
        export KRINO_API=http://127.0.0.1:$API_PORT
        "$PY" -m uvicorn backend.main:app --port "$API_PORT" ${DEV:+--reload} &
        API_PID=$!
        trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM
    fi

    echo "frontend: http://${WEB_HOST:-127.0.0.1}:$WEB_PORT  →  API: $KRINO_API"
    cd frontend
    if [ -n "$DEV" ]; then npx vite; else npx vite preview; fi
}

start() {
    if running; then echo "already running (PID $(cat "$PIDFILE")); see: bash scripts/serve.sh status"; return; fi
    mkdir -p "$RUN"
    # its own session, so stop can end the whole group (bash, uvicorn, vite) and closing the terminal leaves it alone
    setsid nohup bash "$0" run ${DEV:+--dev} >"$LOG" 2>&1 < /dev/null &
    echo $! >"$PIDFILE"
    printf "starting in the background (PID %s, log %s)" "$(cat "$PIDFILE")" "${LOG#"$ROOT"/}"
    local url="http://127.0.0.1:$WEB_PORT/api/health"
    for _ in $(seq 180); do
        if ! running; then echo; echo "failed to start:" >&2; tail -n 20 "$LOG" >&2; rm -f "$PIDFILE"; exit 1; fi
        if curl --noproxy "*" -fs -o /dev/null "$url" 2>/dev/null; then
            echo; echo "ready: http://${WEB_HOST:-127.0.0.1}:$WEB_PORT   (stop: bash scripts/serve.sh stop)"; return
        fi
        printf "."; sleep 1
    done
    echo; echo "still starting; follow it with: bash scripts/serve.sh logs"
}

stop() {
    if ! running; then rm -f "$PIDFILE"; echo "not running"; return; fi
    local pid; pid=$(cat "$PIDFILE")
    kill -- "-$pid" 2>/dev/null || kill "$pid"
    for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
    kill -0 "$pid" 2>/dev/null && kill -9 -- "-$pid" 2>/dev/null || true
    rm -f "$PIDFILE"
    echo "stopped"
}

case "$CMD" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  if running; then echo "running (PID $(cat "$PIDFILE")): http://${WEB_HOST:-127.0.0.1}:$WEB_PORT"; else echo "not running"; fi ;;
    logs)    [ -f "$LOG" ] && tail -n 50 -f "$LOG" || echo "no log yet" ;;
    fg|run)  serve ;;
esac
