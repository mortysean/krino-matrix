#!/usr/bin/env bash
# 把开源部分发布到公开库 github.com/mortysean/krino-matrix（git 远程 origin）。完整代码在私有库 krino-matrix-private（远程 private）。
#
#   scripts/publish_public.sh            先在临时目录里组装、扫描密钥、显示改动，不推送
#   scripts/publish_public.sh --push     组装后提交并推送到公开库的 main
#   KEEP=1 scripts/publish_public.sh     保留组装好的目录（会打印路径），用来在推送前单独测试公开库
#
# 公开库里只有下面 FILES 列出的内容：客户端 SDK、接口文档、KRINO Matrix 推理框架、评测报告。
# 公开库自己的 README、requirements.txt 在 public/ 里。公开库的内容整个由这个脚本决定，不要在公开库里直接改。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="$(git -C "$ROOT" remote get-url origin)"
BRANCH=main
WORK="$(mktemp -d)"
[ -n "${KEEP:-}" ] || trap 'rm -rf "$WORK"' EXIT
log() { echo "[public] $*" >&2; }

FILES=(
  LICENSE
  public/README.md:README.md
  public/README.zh-CN.md:README.zh-CN.md
  public/requirements.txt:requirements.txt
  sdk/python
  docs/api
  krino/__init__.py krino/contract.py krino/style.py
  krino/common/__init__.py krino/common/schema.py
  krino/evaluator
  model/__init__.py model/network.py model/dataset.py model/inference
  experiments/krino-matrix-v1-mmbert/README.md
  experiments/krino-matrix-v1-mmbert/results/report.md
)

log "取下公开库 $REMOTE"
git clone -q --depth 1 --branch "$BRANCH" "$REMOTE" "$WORK/repo"
cd "$WORK/repo"
git rm -rq --ignore-unmatch .
for f in "${FILES[@]}"; do
  src="${f%%:*}"; dst="${f#*:}"
  mkdir -p "$(dirname "$dst")"
  if [ -d "$ROOT/$src" ]; then
    mkdir -p "$dst"
    git -C "$ROOT" ls-files -z "$src" | while IFS= read -r -d '' p; do
      mkdir -p "$(dirname "${dst}/${p#"$src"/}")"; cp "$ROOT/$p" "${dst}/${p#"$src"/}"
    done
  else
    cp "$ROOT/$src" "$dst"
  fi
done
# 只发布已提交到私有库的文件：没进 git 的（本地的 .env、权重、缓存）不会带上
git add -A

log "扫描密钥"
if git grep --cached -nIE '(sk-[A-Za-z0-9_-]{20,}|sk-or-v1-[a-f0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY|LTAI[A-Za-z0-9]{12,}|(API_KEY|SECRET|PASSWORD|TOKEN)=[^ $"]{8,})'; then
  log "发现疑似密钥，已停止"; exit 1
fi
if git diff --cached --name-only --diff-filter=ACMR | grep -E '(^|/)\.env|\.pem$|id_rsa|krino_cn_sudo'; then
  log "发现不该公开的文件，已停止"; exit 1
fi

git diff --cached --stat | tail -20
if git diff --cached --quiet; then log "公开库已经是最新的"; exit 0; fi
[ -n "${KEEP:-}" ] && log "组装好的公开库在 $WORK/repo"
if [ "${1:-}" != --push ]; then log "以上是将要发布的改动；确认后加 --push 推送"; exit 0; fi

SRC="$(git -C "$ROOT" rev-parse --short HEAD)"
git -c user.name="$(git -C "$ROOT" config user.name)" -c user.email="$(git -C "$ROOT" config user.email)" \
  commit -q -m "Publish SDK, API docs and inference framework (from private $SRC)"
git push -q origin "HEAD:$BRANCH"
log "已推送到 $REMOTE ($BRANCH)"
