#!/usr/bin/env bash
# 把 Python SDK（sdk/python，包名 krino-world）发布到 PyPI，之后谁都能 pip install krino-world。
#   scripts/publish_pypi.sh            只打包和检查（不上传）：打出 wheel 和源码包，twine check，装进干净环境试导入
#   scripts/publish_pypi.sh --test     上传到 TestPyPI（test.pypi.org，先试一次）
#   scripts/publish_pypi.sh --upload   上传到正式 PyPI
# 令牌：环境变量 PYPI_TOKEN（TestPyPI 用 TEST_PYPI_TOKEN），或 ~/.pypirc。别把令牌写进仓库。
# 发新版本：改 sdk/python/pyproject.toml 和 krino_world/__init__.py 里的版本号（两处要一样；PyPI 不允许重复上传同一个版本）。
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-check}
PY=${PYTHON:-python3}
SRC=sdk/python
ver=$(sed -nE 's/^version = "([^"]+)"/\1/p' $SRC/pyproject.toml)
ver_init=$(sed -nE 's/^__version__ = "([^"]+)"/\1/p' $SRC/krino_world/__init__.py)
[ "$ver" = "$ver_init" ] || { echo "版本号不一致：pyproject.toml 是 $ver，__init__.py 是 $ver_init"; exit 1; }

case "$MODE" in
  check) INDEX="" ;;
  --test) INDEX=https://test.pypi.org; UPLOAD=https://test.pypi.org/legacy/; REPO=testpypi; TOKEN=${TEST_PYPI_TOKEN:-} ;;
  --upload) INDEX=https://pypi.org; UPLOAD=https://upload.pypi.org/legacy/; REPO=pypi; TOKEN=${PYPI_TOKEN:-} ;;
  *) echo "用法：$0 [--test|--upload]"; exit 1 ;;
esac
if [ -n "$INDEX" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' "$INDEX/pypi/krino-world/$ver/json")" = 200 ]; then
  echo "$INDEX 上已经有 krino-world $ver 了：先改版本号"; exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cp -r $SRC "$work/pkg"
cp LICENSE "$work/pkg/LICENSE"
find "$work/pkg" -name __pycache__ -prune -exec rm -rf {} +
"$PY" -m venv "$work/venv"
"$work/venv/bin/pip" install -q --upgrade pip build twine
(cd "$work/pkg" && "$work/venv/bin/python" -m build -q --outdir "$work/dist" .)
"$work/venv/bin/twine" check --strict "$work/dist"/*
ls -la "$work/dist"

# 装进一个干净环境，确认能导入、版本对、类型标记在
"$PY" -m venv "$work/try"
"$work/try/bin/pip" install -q "$work/dist"/*.whl
"$work/try/bin/python" -I -c "import krino_world, importlib.resources as r; assert krino_world.__version__ == '$ver'; assert r.files('krino_world').joinpath('py.typed').is_file(); print('导入正常：krino_world', krino_world.__version__)"

[ -z "$INDEX" ] && { echo "只做了检查。上传：$0 --test（TestPyPI）或 $0 --upload（正式）"; exit 0; }
if [ -n "$TOKEN" ]; then
  TWINE_USERNAME=__token__ TWINE_PASSWORD="$TOKEN" "$work/venv/bin/twine" upload --repository-url "$UPLOAD" --non-interactive "$work/dist"/*
else
  "$work/venv/bin/twine" upload --repository "$REPO" "$work/dist"/*   # 用 ~/.pypirc
fi
echo "已发布：$INDEX/project/krino-world/$ver/"
