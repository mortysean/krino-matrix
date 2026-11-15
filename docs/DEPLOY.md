# 部署：国内版和海外版

KRINO WORLD 有两个版本，代码是同一套，用 `SITE_EDITION` 区分：

| | 国内版（`cn`） | 海外版（`global`） |
| --- | --- | --- |
| 商标 | 图形 + “决策矩阵” + KRINO MATRIX | 图形 + KRINO MATRIX |
| 界面、报错 | 中文 | 英文（`app/frontend/i18n/en.json`） |
| 默认角色 | 大肥鱼（中文） | Whale-chan（英文，同一个角色） |
| 工坊 | 大肥鱼、KRINO | Whale-chan、KRINO |
| 语音 | 阿里云百炼 `TTS_PROVIDER=dashscope`（没密钥时用 Kokoro） | OpenAI `TTS_PROVIDER=openai`（没密钥时用 Kokoro） |
| 页脚 | 公司名 + ICP 备案号（浙ICP备2026093639号）+ 公安备案号 | 公司英文名 |
| 配置 | `.env`（模板 `.env.example`） | `.env.global`（模板 `.env.global.example`） |

**两个版本是两套独立部署**：各自的服务器、数据库和账号。用户数据不跨境、也不互通，这样国内版的数据可以留在境内。

## 域名

| 域名 | 服务器 | 内容 |
| --- | --- | --- |
| `krinomatrix.com` | 按线路：境内 → 杭州，默认 → 东京（两台都提供） | 官网：全球入口 `/`、中国大陆站 `/cn/`、国际站 `/global/` |
| `www.krinomatrix.com` | 按线路：境内 → 国内，默认 → 海外 | 两台都 302 跳到 `krinomatrix.com` |

应用没有自己的子域名（`app.`、`cn.`、`api.`、`api-cn.` 的 DNS 已删除），都在主域名下：

| 地址 | 由谁提供 |
| --- | --- |
| `krinomatrix.com/cn/products/world/` | 国内服务器的应用后端（接口 `…/products/world/api/`） |
| `krinomatrix.com/global/products/world/` | 海外服务器的应用后端（接口 `…/products/world/api/`） |
| `krinomatrix.com/static/`、`/models/` | 访客所到的那台（两台内容一样） |
| `krinomatrix.com/media/`（用户生成的立绘） | 先本机，没有再去另一台取 |

前端的接口地址按所在路径自动加前缀（`app/frontend/js/core.js` 的 `BASE`），浏览器存储也按地区分开（`cn.krino_token` / `global.krino_token`），后端不用改。

### 官网 krinomatrix.com

- 源码在 `app/landing_src/`：地区和产品配置 `regions.py`，各地区正文 `content/cn/`、`content/global/`（各写各的，不是翻译），全球入口 `content/entry.html`。共用样式和脚本是 `app/landing/portal.css`、`portal.js`。
  改完运行 `python app/landing_src/build.py`，生成到 `app/landing/`（`deploy.sh` 部署前也会自动生成）。
- 信息架构：首页首屏的 **Enter Krino** 和顶栏按钮直接进对应地区的应用；顶栏另外有 产品（`/<地区>/products/`，软件、硬件、开放平台的介绍页）/ 启示与应验（`/<地区>/apocalypse/`，预言与更新通报，宣言是第一条，条目在 `data/apocalypse/entries.json`）/ Krino Tree / 关于。开发者、联系在页脚，旧地址都保留。
- 宣言与 Krino Tree（`/<地区>/vision/`、`/<地区>/manifesto/`）全部由数据生成，和界面分开，在 `app/landing_src/data/`：
  - `manifesto/en.json` 宣言英文原文（官网版，逐段，用 `tools/extract_manifesto.py` 从 `docs/哲学/官网版V3.6.1.docx` 抽取；给投资人的 `使命宣言英文版` 不上官网）
  - `tree/nodes.zh.json` 科技树母版（现为 V5：`docs/长期科技树V5(1).html` 原样抽取，`tools/extract_tree.js`；出新版时重新抽取）；`tree/nodes.en.json` 英文译文（母版改了哪些字段就同步翻译哪些）；`tree/structure.json` 四个阶段与逐条依赖；`tree/labels.json` 界面文字
  - **`tree/status.json` 节点实际进度**：只写核实过的；改了重跑 build。阶段终点和汇合门按前置自动算，写“已完成”必须给依据
- 地区记忆：用户在入口或“切换地区”点了哪个地区，就记在 Cookie `km_region`（Path=/，一年）。再打开根域名时 Caddy 直接 302 到那个地区；`/?choose=1` 不跳。没选过时入口页按 `/edge.json`（到了哪台服务器）推荐，但不跳转，搜索引擎看到的是入口页本身。
- **按路径分源站**：DNS 不能按路径分流，所以靠 Caddy。两台都提供 `krinomatrix.com`，本机地区的路径和共用文件本机出，另一个地区的路径反代给对方源站（HTTPS，SNI/Host 为 `krinomatrix.com`，带 `X-Krino-Edge` 防回环）。结果是不管访客被 DNS 分到哪台，`/cn/*` 一定来自杭州、`/global/*` 一定来自东京。
- Caddy 直接出静态文件（拷到 `/var/www/krinomatrix`），不经过应用后端；后端重启或出错不影响官网。
- 旧地址 `/privacy/`、`/terms/`、`/cookies/` 302 到记住的地区（没记住就去本机地区）的同名页面。
- 浏览器测试：`SITE_URL=https://krinomatrix.com node app/e2e/site.mjs`（只读，不登录）。
- 第一次上线顺序：① 部署海外（`deploy.sh global … caddy`，它会替国内服务器转发官网的证书验证）→ ② 部署国内（`deploy.sh cn … caddy`）→ ③ 确认国内服务器已拿到 `krinomatrix.com` 证书后，在 DNSPod 给 `@` 加一条线路「境内」的 A 记录 → `111.229.152.63`（「默认」那条保持 `43.153.189.97`）。

`www` 在 DNSPod 里是两条 A 记录：线路「境内」→ 国内 IP，线路「默认」→ 海外 IP。证书机构从境外验证，国内服务器的 www 和官网证书验证请求会先到海外服务器，由它转给国内服务器（`scripts/caddy_setup.sh` 的 `PEER_ACME`），所以海外服务器要一直在线。只改 Caddy 或只更新官网：`scripts/deploy.sh cn|global user@host caddy`（两台都要跑）。

每个版本的页脚都有指向另一个版本的链接（`OTHER_EDITION_URL`），用了代理或 VPN 被分错的人也能手动切换。

需要注意：

- **国内服务器必须先办 ICP 备案**，否则 80/443 端口会被云厂商拦截。办好后把备案号填进国内版的 `ICP_NUMBER`，页脚会显示并链接到工信部查询页。网站上线 30 天内还要办公安联网备案，号码填 `POLICE_RECORD_NUMBER`。
- **AI 对话服务在国内上线需要算法备案和生成式 AI 服务备案**（网信办），并且要用已备案的大模型。国内版请先确认 `LLM_PROVIDER` 指向的模型服务符合要求。这一点我没法替你判断，上线前请找法务确认。
- **HTTPS 证书**：两台服务器各自申请同一个域名的证书（比如 Let's Encrypt），互不影响。
- **按 IP 判断地区不是 100% 准确**：用了代理、VPN 或境外漫游的人会被分到另一个版本。所以两个版本的页脚各放一个指向对方的链接，比如国内版放 “Global”、海外版放 “中国大陆”，保证任何人都能手动进入另一个版本。
- **不要在一台服务器上按 IP 跳转**：两个版本分别部署，DNS 解析就已经分好流量，应用里不需要判断地区。

## 一台机器上同时跑两个版本（开发、测试）

```bash
cp .env.global.example .env.global          # 海外版：端口 8631，数据库 krino_world_global
scripts/world.sh db init                    # 会同时建好 krino_world 和 krino_world_global
scripts/world.sh start                      # 国内版  http://<IP>:8630
ENV_FILE=.env.global scripts/world.sh start # 海外版  http://<IP>:8631
ENV_FILE=.env.global scripts/world.sh logs  # 海外版的日志在 .run/world-global.log
```

## 正式部署一台服务器

一条命令（Ubuntu 22.04，本机能免密 SSH 登录，服务器用户能 sudo；可重复运行，之后就是更新）：

```bash
scripts/deploy.sh global ubuntu@<海外 IP>   # app（接口 /api/）/ 官网 /global/
scripts/deploy.sh cn     sean@<国内 IP>     # cn（接口 /api/）/ 官网 /cn/
```

- 装在服务器用户的主目录：`~/krino-world`，配置在 `~/krino-world/.env`（第一次部署时生成，之后不覆盖）。改完配置：`sudo systemctl restart krino-world`。
- 装好 PostgreSQL、Python 3.11、Caddy，建库迁移，注册 systemd 服务 `krino-world`，Caddy 自动申请 HTTPS 证书。
- 官网由 Caddy 直接提供（每次部署从 `app/landing/` 拷到 `/var/www/krinomatrix`）；后端的 `/landing/` 只用来本地预览。
- 服务器上已经有别的 Caddy 配置时，脚本不会改它，只会提示在 `/etc/caddy/Caddyfile` 末尾加一行 `import /etc/caddy/krino-world.caddy`。
- 语音密钥：国内版填 `DASHSCOPE_API_KEY`，海外版填 `OPENAI_API_KEY`。

自己用 Nginx 时，注意 `/api/sessions/*/stream` 是 SSE 流式输出，要关掉代理缓冲；`/api/devices/ws` 是 WebSocket，要转发 Upgrade 头：

```nginx
location / {
    proxy_pass http://127.0.0.1:8630;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_buffering off;          # SSE 流式回复
    proxy_read_timeout 120s;
    client_max_body_size 16m;     # 上传图片、人设包
}
```

## 翻译

- 界面文字的翻译表在 `app/frontend/i18n/en.json`，用中文原文作键，规则见 `app/frontend/i18n/README.md`。
- 加了新的中文文案后，运行 `node scripts/i18n_check.mjs`，列出还缺英文的条目。
- 角色的人设（官方角色、工坊精选）中英文是分别写的，不是机器翻译。位置在 `app/backend/app/personas.py`（`OFFICIAL` / `OFFICIAL_EN`）和 `catalog.py`。
