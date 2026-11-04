#!/usr/bin/env bash
# 生成 KRINO WORLD 的 Caddy 配置并重新加载（以 root 运行；server_setup.sh 最后会调用，也可以单独运行）。
#
# 环境变量：
#   SITES      本机提供的站点，逗号分隔，比如 "cn.krinomatrix.com, api-cn.krinomatrix.com"
#   LANDING=1  同时提供 krinomatrix.com 品牌首页（海外服务器）
#   WWW_TO     www.krinomatrix.com 跳到哪里（本机的站点）。DNS 按线路把 www 分给两台服务器：境内 → 国内，其余 → 海外
#   PEER_ACME  另一台服务器的 IP:80。证书机构从境外验证，www 的验证请求总会到海外服务器；
#              海外服务器把它不认识的验证请求转给国内服务器，国内的 www 证书才申请得下来
set -euo pipefail
log() { echo "[caddy] $*" >&2; }
SNIPPET=/etc/caddy/krino-world.caddy
{
  echo "# KRINO WORLD（scripts/caddy_setup.sh 生成，重新部署会覆盖）"
  echo "$SITES {"
  echo "	tls {"
  echo "		issuer acme"
  echo "	}"
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
  fi
  if [ -n "${WWW_TO:-}" ]; then
    # 302 而不是 301：同一个地址按地区去不同的站，不能让浏览器永久缓存
    if [ -n "${PEER_ACME:-}" ]; then
      echo "http://www.krinomatrix.com {"
      echo "	handle /.well-known/acme-challenge/* {"
      echo "		reverse_proxy ${PEER_ACME}   # 本机不认识的验证请求（国内服务器的）转过去"
      echo "	}"
      echo "	handle {"
      echo "		redir ${WWW_TO}{uri} 302"
      echo "	}"
      echo "}"
    fi
    echo "www.krinomatrix.com {"
    echo "	tls {"
    echo "		issuer acme"
    echo "	}"
    echo "	redir ${WWW_TO}{uri} 302"
    echo "}"
  fi
} > "$SNIPPET"

CF=/etc/caddy/Caddyfile
# 只有 Caddy 安装包自带的欢迎页配置（:80 + /usr/share/caddy）也算空的，可以接管
stock() { [ "$(grep -vE '^\s*(#|$)' "$CF" | tr -d ' \t\n')" = ':80{root*/usr/share/caddyfile_server}' ]; }
if [ ! -s "$CF" ] || grep -q "^# managed-by: krino-world" "$CF" || stock; then
  printf '# managed-by: krino-world\nimport %s\n' "$SNIPPET" > "$CF"
  caddy validate --config "$CF" >/dev/null 2>&1 || { caddy validate --config "$CF"; exit 1; }
  systemctl enable --now caddy >/dev/null
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  log "已配置：$SITES${WWW_TO:+；www → $WWW_TO}"
elif grep -qF "import $SNIPPET" "$CF"; then
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  log "已经引用了 $SNIPPET，已重新加载"
else
  log "这台机器上已有别的 Caddy 配置（$CF），没有改动它。"
  log "要启用 KRINO WORLD，请在 $CF 末尾加一行：  import $SNIPPET  然后重新加载 Caddy。"
fi
