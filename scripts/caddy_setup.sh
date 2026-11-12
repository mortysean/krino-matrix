#!/usr/bin/env bash
# 生成 KRINO WORLD 的 Caddy 配置并重新加载（以 root 运行；server_setup.sh 最后会调用，也可以单独运行）。
#
# 环境变量：
#   SITES      本机提供的应用站点，逗号分隔，比如 "cn.krinomatrix.com"。接口就在应用域名下的 /api/
#   REDIRECTS  只做跳转的旧域名，空格分隔的 旧域名=新地址，比如 "api-cn.krinomatrix.com=https://cn.krinomatrix.com"（308，保留方法和请求体）
#   LANDING=1  同时提供官网 krinomatrix.com（两台都开：DNS 按线路把境内访客分到杭州、其他分到东京）
#   SITE_REGION  本机是哪个地区站的源站：cn（杭州）或 global（东京）。另一个地区的路径（/global/* 或 /cn/*）反代给 PEER_ORIGIN
#   PEER_ORIGIN  另一台服务器的 IP（走 HTTPS，SNI 和 Host 都是 krinomatrix.com）
#   WEB_ROOT     官网静态文件放哪（默认 /var/www/krinomatrix，从 $DEST/app/landing 拷过去；Caddy 读不了用户主目录）
#   WWW_TO     www.krinomatrix.com 跳到哪里：现在两台都跳到公司门户 https://krinomatrix.com（DNS 仍按线路把 www 分给两台服务器）
#   PEER_ACME  另一台服务器的 IP:80。证书机构从境外验证，www 和官网的验证请求总会到海外服务器；
#              海外服务器把它不认识的验证请求转给国内服务器，国内的 www 和官网证书才申请得下来
set -euo pipefail
log() { echo "[caddy] $*" >&2; }
SNIPPET=${SNIPPET:-/etc/caddy/krino-world.caddy}
WEB_ROOT=${WEB_ROOT:-/var/www/krinomatrix}
if [ "${LANDING:-0}" = 1 ]; then
  : "${SITE_REGION:?LANDING=1 时要给 SITE_REGION=cn|global}" "${PEER_ORIGIN:?LANDING=1 时要给 PEER_ORIGIN=另一台的 IP}"
  case "$SITE_REGION" in cn) OTHER_REGION=global ;; global) OTHER_REGION=cn ;; *) echo "SITE_REGION 只能是 cn 或 global"; exit 1 ;; esac
  if [ -z "${NO_SITE_COPY:-}" ]; then
    # 换一份新目录再整体替换，访客不会看到拷了一半的站
    mkdir -p "$(dirname "$WEB_ROOT")"
    rm -rf "$WEB_ROOT.new" "$WEB_ROOT.old"
    cp -r "$DEST/app/landing" "$WEB_ROOT.new"
    chmod -R a+rX "$WEB_ROOT.new"
    [ -d "$WEB_ROOT" ] && mv "$WEB_ROOT" "$WEB_ROOT.old"
    mv "$WEB_ROOT.new" "$WEB_ROOT"
    rm -rf "$WEB_ROOT.old"
    log "官网文件已更新：$WEB_ROOT"
  fi
fi
{
  echo "# KRINO WORLD（scripts/caddy_setup.sh 生成，重新部署会覆盖）"
  if [ -n "${SITES:-}" ]; then
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
  fi
  if [ "${LANDING:-0}" = 1 ]; then
    # 官网：Caddy 直接出静态文件，不经过应用后端（后端挂了官网照常）。
    # 本机地区的路径和根目录、共用资源本机出；另一个地区的路径反代给对方源站，所以 /cn/* 永远来自杭州、/global/* 永远来自东京。
    COOKIE_RE='(?:^|;\s*)km_region=(cn|global)(?:;|$)'
    echo "krinomatrix.com {"
    echo "	tls {"
    echo "		issuer acme"
    echo "	}"
    echo "	encode gzip"
    echo "	root * $WEB_ROOT"
    echo "	request_body {"
    echo "		max_size 16MB"
    echo "	}"
    echo "	header {"
    echo "		X-Content-Type-Options nosniff"
    echo "		Referrer-Policy strict-origin-when-cross-origin"
    echo "		-Server"
    echo "	}"
    echo "	route {"
    echo "		# 产品应用 KRINO WORLD：/<地区>/products/world/ 下。本地区的转给本机后端（去掉前缀），另一个地区的转给对方源站"
    echo "		redir /$SITE_REGION/products/world /$SITE_REGION/products/world/ 308"
    echo "		redir /$OTHER_REGION/products/world /$OTHER_REGION/products/world/ 308"
    echo "		@app path /$SITE_REGION/products/world/*"
    echo "		route @app {"
    echo "			uri strip_prefix /$SITE_REGION/products/world"
    echo "			reverse_proxy 127.0.0.1:8630 {"
    echo "				flush_interval -1"
    echo "				header_up X-Forwarded-Prefix /$SITE_REGION/products/world"
    echo "			}"
    echo "		}"
    echo "		@app_other {"
    echo "			path /$OTHER_REGION/products/world/*"
    echo "			not header X-Krino-Edge *"
    echo "		}"
    echo "		reverse_proxy @app_other https://$PEER_ORIGIN {"
    echo "			flush_interval -1"
    echo "			header_up Host krinomatrix.com"
    echo "			header_up X-Krino-Edge $SITE_REGION"
    echo "			transport http {"
    echo "				tls_server_name krinomatrix.com"
    echo "				dial_timeout 5s"
    echo "			}"
    echo "		}"
    echo "		# 应用的图片、样式、模型都在根目录：/static/ /models/ 两台一样，本机后端出；/media/（用户生成的立绘）本机没有就去对方取"
    echo "		@appfiles path /static/* /models/*"
    echo "		reverse_proxy @appfiles 127.0.0.1:8630"
    echo "		@media path /media/*"
    echo "		reverse_proxy @media 127.0.0.1:8630 {"
    echo "			@missing status 404"
    echo "			handle_response @missing {"
    echo "				@from_peer header X-Krino-Edge *"
    echo "				respond @from_peer 404"
    echo "				reverse_proxy https://$PEER_ORIGIN {"
    echo "					header_up Host krinomatrix.com"
    echo "					header_up X-Krino-Edge $SITE_REGION"
    echo "					transport http {"
    echo "						tls_server_name krinomatrix.com"
    echo "						dial_timeout 3s"
    echo "						response_header_timeout 10s"
    echo "					}"
    echo "				}"
    echo "			}"
    echo "		}"
    echo "		# 另一个地区的官网页面：转给它的源站。带上 X-Krino-Edge，对方看到就只在本机找，不会再转回来"
    echo "		@other {"
    echo "			path /$OTHER_REGION /$OTHER_REGION/*"
    echo "			not path /$OTHER_REGION/products/world*"
    echo "			not header X-Krino-Edge *"
    echo "		}"
    echo "		reverse_proxy @other https://$PEER_ORIGIN {"
    echo "			header_up Host krinomatrix.com"
    echo "			header_up X-Krino-Edge $SITE_REGION"
    echo "			transport http {"
    echo "				tls_server_name krinomatrix.com"
    echo "				dial_timeout 3s"
    echo "				response_header_timeout 5s"
    echo "			}"
    echo "		}"
    echo "		# 根目录不让人选地区：直接进门户首页——记住过的地区，没记住就按到了哪台服务器（DNS 按线路分：境内到杭州、其他到东京）"
    echo "		@root path /"
    echo "		header @root Vary Cookie"
    echo "		header @root Cache-Control \"private, no-store\""
    echo "		@root_saved {"
    echo "			path /"
    echo "			header_regexp saved Cookie $COOKIE_RE"
    echo "		}"
    echo "		redir @root_saved /{re.saved.1}/ 302"
    echo "		redir @root /$SITE_REGION/ 302"
    echo "		# 不带地区的地址（旧地址 /privacy/ 等，或直接敲的 /about/、/products/world/）：去记住的地区，没记住就去本机的地区"
    RL='^/(privacy|terms|cookies|about|contact|developers|products|vision|manifesto|apocalypse)/?(.*)$'
    echo "		@legacy path_regexp legacy $RL"
    echo "		header @legacy Cache-Control \"private, no-store\""
    echo "		@legacy_saved {"
    echo "			path_regexp legacy $RL"
    echo "			header_regexp saved Cookie $COOKIE_RE"
    echo "		}"
    echo "		redir @legacy_saved /{re.saved.1}/{re.legacy.1}/{re.legacy.2} 302"
    echo "		redir @legacy /$SITE_REGION/{re.legacy.1}/{re.legacy.2} 302"
    echo "		# 战略（Krino Tree）的别名"
    echo "		@tree_r path_regexp tree_r ^/(cn|global)/(tree|krino-tree|strategy)/?$"
    echo "		redir @tree_r /{re.tree_r.1}/vision/#tree 301"
    TR='^/(tree|krino-tree|strategy)/?$'
    echo "		@tree path_regexp tree $TR"
    echo "		@tree_saved {"
    echo "			path_regexp tree $TR"
    echo "			header_regexp saved Cookie $COOKIE_RE"
    echo "		}"
    echo "		redir @tree_saved /{re.saved.1}/vision/#tree 302"
    echo "		redir @tree /$SITE_REGION/vision/#tree 302"
    echo "		# 按语言的直觉地址"
    echo "		redir /zh /cn/ 301"
    echo "		redir /zh/ /cn/ 301"
    echo "		redir /en /global/ 301"
    echo "		redir /en/ /global/ 301"
    echo "		# /<地区>/products/ 是官网的产品介绍页（静态文件），应用在 /<地区>/products/world/"
    echo "		# 旧门户用过的后端预览路径"
    echo "		@oldlanding path_regexp oldlanding ^/landing/?(.*)$"
    echo "		redir @oldlanding /{re.oldlanding.1} 301"
    echo "		# 文件名不带哈希：页面、样式、脚本每次先问一下（304 很便宜），图片缓存一天"
    echo "		@assets path /assets/*"
    echo "		header @assets Cache-Control \"public, max-age=86400\""
    echo "		@pages {"
    echo "			not path /assets/* /static/* /models/* /media/*"
    echo "			not path /cn/products/world/* /global/products/world/*"
    echo "		}"
    echo "		header @pages Cache-Control no-cache"
    echo "		file_server"
    echo "	}"
    echo "	handle_errors {"
    echo "		# 跨境偶尔连不上或很慢（杭州↔东京实测会卡几十秒）：对方源站失败时用本机同一份文件（两台来自同一次构建），访客不会看到错误"
    echo "		@peer_down {"
    echo "			path /$OTHER_REGION /$OTHER_REGION/*"
    echo "			not path /$OTHER_REGION/products/world*"
    echo "			expression {err.status_code} in [502, 503, 504]"
    echo "		}"
    echo "		handle @peer_down {"
    echo "			header X-Krino-Fallback local"
    echo "			file_server {"
    echo "				status 200"
    echo "			}"
    echo "		}"
    echo "		@404 expression {err.status_code} == 404"
    echo "		handle @404 {"
    echo "			rewrite * /404.html"
    echo "			file_server"
    echo "		}"
    echo "	}"
    echo "}"
    if [ -n "${PEER_ACME:-}" ]; then
      # 国内服务器的官网证书：验证请求会到这里，转过去（同 www）
      echo "http://krinomatrix.com {"
      echo "	handle /.well-known/acme-challenge/* {"
      echo "		reverse_proxy ${PEER_ACME}"
      echo "	}"
      echo "	handle {"
      echo "		redir https://krinomatrix.com{uri} 308"
      echo "	}"
      echo "}"
    fi
  fi
  for r in ${REDIRECTS:-}; do
    echo "${r%%=*} {"
    echo "	tls {"
    echo "		issuer acme"
    echo "	}"
    echo "	redir ${r#*=}{uri} 308"
    echo "}"
  done
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
[ -n "${GEN_ONLY:-}" ] && { log "只生成了 $SNIPPET（GEN_ONLY）"; exit 0; }

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
  caddy validate --config "$CF" >/dev/null 2>&1 || { caddy validate --config "$CF"; exit 1; }  # 配置有错就别重载，免得把在跑的站带下去
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  log "已经引用了 $SNIPPET，已重新加载"
else
  log "这台机器上已有别的 Caddy 配置（$CF），没有改动它。"
  log "要启用 KRINO WORLD，请在 $CF 末尾加一行：  import $SNIPPET  然后重新加载 Caddy。"
fi
