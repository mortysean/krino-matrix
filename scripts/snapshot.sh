#!/usr/bin/env bash
# 部署快照与回滚（在服务器上运行，scripts/deploy.sh 会调用）。快照在 ~APP_USER/deploy-bak/snap-<时间>-<当时的提交>/，保留最近 KEEP 份（默认 5）。
#   snapshot.sh take             以应用账号运行。部署前拍一份：代码和 .venv（硬链接，几乎不占空间）、.env、数据库（pg_dump）
#   snapshot.sh list             以应用账号运行
#   snapshot.sh restore [名字]   以 root 运行。默认最新一份：停服务 → 恢复代码、.venv、.env → 启动、自检 → 重新发布官网（caddy_setup.sh）
#                                RESTORE_DB=1 时数据库也回到快照那一刻（快照之后的新数据会丢）
# 用户上传的 data/media/ 和日志 .run/ 不进快照，也不会被恢复覆盖。
# 硬链接是安全的：rsync 和 pip 写文件都是先写新文件再替换，不会改到快照里那一份。
set -euo pipefail
APP_USER="${APP_USER:-$(id -un)}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
DEST="${DEST:-$APP_HOME/krino-world}"
BAK="${BAK:-$APP_HOME/deploy-bak}"
KEEP="${KEEP:-5}"
log() { echo "[snapshot] $*" >&2; }
db_url() { grep -E '^DATABASE_URL=' "$1" | cut -d= -f2- | sed -E 's#^postgresql\+[a-z0-9]+://#postgresql://#'; }
snaps() { ls -1d "$BAK"/snap-* 2>/dev/null | sort; }

case "${1:-}" in
  take)
    [ -d "$DEST/app" ] || { log "$DEST 还没部署过，不拍快照"; exit 0; }
    rev="$(sed -n 's/^commit=//p' "$DEST/.deployed" 2>/dev/null || true)"
    s="$BAK/snap-$(date +%Y%m%d-%H%M%S)${rev:+-$rev}"
    mkdir -p "$s"; chmod 700 "$BAK"
    rsync -a --link-dest="$DEST/" --exclude=/data/media/ --exclude=/.run/ --exclude=/.env "$DEST/" "$s/code/"
    install -m 600 "$DEST/.env" "$s/env"
    pg_dump -Fc -f "$s/db.dump" "$(db_url "$DEST/.env")"
    snaps | head -n -"$KEEP" | xargs -r rm -rf
    log "已拍快照 $(basename "$s")（数据库 $(du -h "$s/db.dump" | cut -f1)），现有 $(snaps | wc -l) 份"
    ;;
  list)
    for s in $(snaps); do echo "$(basename "$s")  $(sed -n 's/^\(commit\|time\)=//p' "$s/code/.deployed" 2>/dev/null | paste -sd' ')"; done
    ;;
  restore)
    [ "$(id -u)" = 0 ] || { log "restore 要以 root 运行"; exit 1; }
    s="${2:+$BAK/$2}"; s="${s:-$(snaps | tail -1)}"
    [ -d "$s/code" ] && [ -f "$s/env" ] || { log "没有快照 ${s:-（空）}"; exit 1; }
    log "回滚到 $(basename "$s")${RESTORE_DB:+（含数据库）}"
    systemctl stop krino-world
    sudo -u "$APP_USER" rsync -a --delete --exclude=/data/media/ --exclude=/.run/ --exclude=/.env "$s/code/" "$DEST/"
    sudo -u "$APP_USER" install -m 600 "$s/env" "$DEST/.env"
    if [ -n "${RESTORE_DB:-}" ]; then
      db="$(db_url "$DEST/.env" | sed -E 's#.*/([^/?]+).*#\1#')"
      sudo -u postgres dropdb --force --if-exists "$db"
      sudo -u postgres createdb -O krino "$db"
      sudo -u "$APP_USER" pg_restore --no-owner -d "$(db_url "$DEST/.env")" "$s/db.dump"
    fi
    systemctl start krino-world
    for i in $(seq 1 60); do curl -s --max-time 1 -o /dev/null http://127.0.0.1:8630/api/health && break; sleep 1; done
    curl -s http://127.0.0.1:8630/api/health && echo
    bash "$DEST/scripts/caddy_setup.sh"
    log "已回滚到 $(basename "$s")"
    ;;
  *) echo "用法：$0 take | list | restore [名字]"; exit 1 ;;
esac
