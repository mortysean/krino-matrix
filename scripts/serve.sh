#!/usr/bin/env bash
# Build the frontend and serve the web app at http://localhost:${PORT:-8000}.
#
#     bash scripts/serve.sh          # build frontend/, then serve it with the API
#     bash scripts/serve.sh --dev    # API only, with reload; run (cd frontend && npm run dev) beside it
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/anaconda3/envs/krino_matrix/bin/python}"
[ -x "$PY" ] || PY=python
cd "$ROOT"

PORT=${PORT:-8000}
if [ "${1:-}" = "--dev" ]; then
    exec "$PY" -m uvicorn backend.main:app --reload --port "$PORT"
fi
(cd frontend && { [ -d node_modules ] || npm install; } && npm run build)
exec "$PY" -m uvicorn backend.main:app --port "$PORT"
