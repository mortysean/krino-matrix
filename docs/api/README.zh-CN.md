# KRINO WORLD 接口

[English](README.md) | **简体中文**

KRINO WORLD 应用背后的 HTTP 接口。网页版用的就是这些接口，它能做的你都能做。所有接口和请求、返回的格式都在 [`openapi.json`](openapi.json)（OpenAPI 3.1）里。这一页讲规范文件里看不出来的部分：连到哪里、怎么登录、流式回复怎么收、报错是什么意思。

最快的用法是 [`sdk/python`](../../sdk/python) 里的 Python 客户端。

## 地址

| 地区 | 应用 | 接口 |
| --- | --- | --- |
| 中国大陆 | `https://krinomatrix.com/cn/products/world/` | `https://krinomatrix.com/cn/products/world/api/` |
| 国际 | `https://krinomatrix.com/global/products/world/` | `https://krinomatrix.com/global/products/world/api/` |

两个地区是**两套独立部署**，服务器、数据库、账号各自分开，用户数据不跨境。所以在一个地区注册的账号，在另一个地区不存在。

自己部署的服务器，接口在 `http://<主机>:8630/api/`。

## 登录

先注册或登录，拿到 token，之后每个请求都带上 Bearer 头。

```bash
API=https://krinomatrix.com/cn/products/world/api
curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"username": "me", "password": "secret"}'
# → {"token": "…", "user": {"id": "…", "username": "me", "display_name": "…", "settings": {…}}}

curl -s $API/characters -H "Authorization: Bearer $TOKEN"
```

| 接口 | |
| --- | --- |
| `POST /auth/register` | `username`、`password`（6–128 位）、可选 `display_name` → `token`、`user` |
| `POST /auth/login` | `username`、`password` → `token`、`user` |
| `POST /auth/logout` | 让 token 失效 |
| `GET /me` · `PATCH /me` | 账号信息和设置 |
| `DELETE /me` | 删除账号和里面的一切，请求体 `{"password": "…"}` |

token 一段时间后会过期。过期后请求返回 `401`，重新登录即可。

## 和角色聊天

1. `GET /characters` 列出你的角色。新账号自带官方默认角色。
2. `POST /sessions`，请求体 `{"character_id": "…"}`，开始一段对话。返回里有角色的开场白 `greeting`。
3. 发消息，可以等整句回复，也可以流式接收：

| 接口 | 请求体 | 返回 |
| --- | --- | --- |
| `POST /sessions/{id}/messages` | `text`、可选 `image`（data URL）、`source`（`app` / `voice` / `glasses`） | 一个 JSON：`reply`、`user`、`actions`、`decision`、`memory_job` |
| `POST /sessions/{id}/stream` | 同上，另可带 `audio`（`data:audio/wav;base64,…`，角色直接听录音） | `text/event-stream` |
| `POST /sessions/{id}/events` | `type`：`gesture`（带 `gesture`）、`idle`、`perception`（带 `image`） | 同 `/messages` |
| `POST /sessions/{id}/end` | — | 会话信息，加一段简短总结 `summary` |

### 流式回复

`/stream` 按下面的顺序发 [SSE 事件](https://html.spec.whatwg.org/multipage/server-sent-events.html)：

```
event: decision
data: {"actions": ["RESPOND"], "policy": "rules", "label": "…"}

event: delta
data: {"text": "你"}

event: delta
data: {"text": "好呀！"}

event: done
data: {"reply": {…}, "user": {…}, "actions": […], "decision": {…}, "memory_job": "…"}
```

- 最先到的是 `decision`：这一轮互动策略的选择，比如回应、安静陪着、做个动作。
- `delta` 是一段段回复文字，把各段的 `text` 拼起来就是整句回复。
- `done` 里是和 `/messages` 一样的完整结果。
- 生成中途失败时，会用 `error`（`{"message": "…"}`）代替 `done`。

如果接口前面有反向代理，这个接口要关掉代理缓冲。

## 记忆

角色会记住和你有关的重要事情。这些记忆你都能看到、修改和删除。

| 接口 | |
| --- | --- |
| `GET /memories?character_id=…` | 可选 `status`（默认 `active`）、`type`、`q`（搜索） |
| `POST /memories` | `character_id`、`content`、`type`（`fact` / `preference` / `event` / `commitment`）、`reality`（`real` 是真实发生的，`story` 是一起编的故事）、`importance` 1–5、`pinned`、`sensitive` |
| `PATCH /memories/{id}` | 修改以上任意字段 |
| `POST /memories/{id}/forget` · `/restore` | 忘掉一条记忆，或者找回来 |
| `DELETE /memories/{id}` | 永久删除 |
| `GET /memories/candidates?character_id=…` | 角色提议记住、等你确认的内容 |
| `POST /memories/candidates/{id}/accept` · `DELETE /memories/candidates/{id}` | 接受或拒绝提议 |
| `GET /memory-jobs/{id}?wait=…` | 一轮对话触发的后台记忆整理（对话结果里的 `memory_job`） |
| `GET /relations/{character_id}/export` · `POST …/import` | 导出或导入你和这个角色的全部关系：记忆和羁绊 |

## 语音与视觉

| 接口 | |
| --- | --- |
| `POST /voice/tts` | `text`、可选 `voice`、`rate`（0.5–2.0）→ 音频。格式看返回的 `Content-Type` |
| `POST /voice/stt` | 语音识别（服务器开启时可用） |
| `GET /voice/config` | 这台服务器提供哪些语音服务 |
| `POST /vision/describe` | `image`（data URL）、可选 `question` |

## 其他接口

`openapi.json` 里还有：角色编辑和版本（`/characters/*`）、`krino-persona/1` 人设包的导入导出、工坊（`/workshop/*`）、圈子（`/social/*`）、KRINO GLASSES 设备接口（`/devices/*`，包括 WebSocket `/devices/ws`）、积分（`/credits`）、服务状态（`/health`、`/status`、`/services`）。

## 报错

报错是 JSON：`{"detail": "…"}`。提示是写给人看的，用所在地区的语言。

| 状态码 | 含义 |
| --- | --- |
| `400` | 请求不完整，比如消息是空的 |
| `401` | 没带 token，或 token 过期了 |
| `404` | 东西不存在，或者不是你的 |
| `409` | 这段会话属于另一个角色，和你传的 `character_id` 对不上 |
| `422` | 请求体格式不对 |
| `429` | 今天的积分用完了 |
| `502` / `503` | 上游的模型或语音服务出错了，一般重试就好 |

## 更新规范文件

`openapi.json` 是从后端导出的。要更新它，先启动服务器，再把 `http://127.0.0.1:8630/openapi.json` 保存下来覆盖这个文件。
