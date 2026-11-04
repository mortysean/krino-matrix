# 部署：国内版和海外版

KRINO WORLD 有两个版本，代码是同一套，用 `SITE_EDITION` 区分：

| | 国内版（`cn`） | 海外版（`global`） |
| --- | --- | --- |
| 商标 | 图形 + “决策矩阵” + KRINO MATRIX | 图形 + KRINO MATRIX |
| 界面、报错 | 中文 | 英文（`app/frontend/i18n/en.json`） |
| 默认角色 | 大肥鱼（中文） | Whale-chan（英文，同一个角色） |
| 工坊精选 | 中文的 9 个角色 | 英文的 9 个角色 |
| 语音 | Kokoro 中文音色 | Kokoro 英文音色（af_maple / af_sol / bf_vale） |
| 页脚 | 公司名 + ICP 备案号 + 公安备案号 | 公司英文名 |
| 配置 | `.env`（模板 `.env.example`） | `.env.global`（模板 `.env.global.example`） |

**两个版本是两套独立部署**：各自的服务器、数据库和账号。用户数据不跨境、也不互通，这样国内版的数据可以留在境内。

## 一个域名，按地区解析到不同服务器

`krinomatrix.com` 在 DNS 里配**智能解析（按地区分线路）**：

```
krinomatrix.com   A   境内线路   → 国内服务器 IP（国内版）
krinomatrix.com   A   境外线路   → 海外服务器 IP（海外版）
```

阿里云云解析、腾讯云 DNSPod 都支持按“境内 / 境外”或更细的地区分线路，免费版就有。境外线路也可以改用 Cloudflare 等海外 DNS，但同一个域名只能有一家权威 DNS，所以通常直接在国内 DNS 服务商那里分线路。

需要注意：

- **国内服务器必须先办 ICP 备案**，否则 80/443 端口会被云厂商拦截。办好后把备案号填进国内版的 `ICP_NUMBER`，页脚会显示并链接到工信部查询页。网站上线 30 天内还要办公安联网备案，号码填 `POLICE_RECORD_NUMBER`。
- **AI 对话服务在国内上线需要算法备案和生成式 AI 服务备案**（网信办），并且要用已备案的大模型。国内版请先确认 `LLM_PROVIDER` 指向的模型服务符合要求。这一点我没法替你判断，上线前请找法务确认。
- **HTTPS 证书**：两台服务器各自申请同一个域名的证书（比如 Let's Encrypt），互不影响。
- **按 IP 判断地区不是 100% 准确**：用了代理、VPN 或境外漫游的人会被分到另一个版本。所以两个版本的页脚各放一个指向对方的链接，比如国内版放 “Global”、海外版放 “中国大陆”，用不同的子域名（`cn.krinomatrix.com` / `global.krinomatrix.com`）指向各自的服务器，保证任何人都能手动进入另一个版本。
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

1. 装 Python 3.11 和 PostgreSQL 14+。
2. 运行 `scripts/world.sh setup`，它会装依赖、建库，并下载语音模型和 Live2D 示例。海外服务器访问 Hugging Face 不用镜像。
3. 填写配置文件：`SITE_EDITION`、`DATABASE_URL`、`OPENROUTER_API_KEY`，国内版还要填 `ICP_NUMBER`。
4. 前面放一个反向代理（Nginx / Caddy）负责 HTTPS，转发到 `127.0.0.1:8630`。注意 `/api/sessions/*/stream` 是 SSE 流式输出，要关掉代理缓冲；`/api/devices/ws` 是 WebSocket，要转发 Upgrade 头。Nginx 示例：

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
