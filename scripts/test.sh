#!/usr/bin/env bash
# Backend and decision-flow tests; no model is called.
#
#     bash scripts/test.sh [pytest args]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$HOME/anaconda3/envs/krino_matrix/bin/python}"
[ -x "$PY" ] || PY=python
cd "$ROOT"

exec "$PY" -m pytest tests "$@"
