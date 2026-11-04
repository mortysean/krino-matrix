#!/usr/bin/env bash
# 后端测试（KRINO WORLD），等同于 scripts/world.sh test。不调用真实模型。
#
#     bash scripts/test.sh [pytest 参数]
exec "$(dirname "${BASH_SOURCE[0]}")/world.sh" test "$@"
