# KRINO WORLD 架构

日常开发先看这一篇。

## 设计原则

前端的核心是**节省用户的认知资源：能点一下解决的，绝不用两下**。

- 导航只有 4 项：聊天 · 角色 · 工坊 · 设置。
- 会话自动管理，不用开始或结束；空会话给三个一点就发的开场白。
- 每条回复旁边一个喇叭，点一下就读。舞台右上角一个开关决定是否自动朗读。
- 麦克风点一下开始说，再点一下发送。
- 工坊卡片上直接“领养”，一次点击就导入并开始聊天。
- 设置是开关，改了立刻保存。技术细节（模型服务、策略、眼镜模拟器、运行状态）都收在“高级”里。
- 确认弹窗只用于删除、告别、注销这类不可逆的操作。

## 目录

```
app/
  backend/          FastAPI + PostgreSQL + alembic
    app/            一个领域一个文件（见下表）
    migrations/     表结构迁移
    tests/          pytest：单元、接口验收、设备
  frontend/         原生 ES 模块，无构建
    index.html  style.css  mascot.js
    js/             main（路由）core（接口、弹窗）chat persona workshop settings memory glasses
                    stage（2D 形象）voice（语音）icons
    assets/         立绘与头像（来源见 assets/CREDITS.md）
    vendor/         PixiJS、pixi-live2d-display、Cubism Core（版本与许可见 vendor/README.md）
  e2e/              浏览器端到端测试
data/               只在本地，不进 git
  pgdata/           PostgreSQL 数据目录（scripts/world.sh db init 创建）
  models/           scripts/fetch_assets.py 下载的素材：kokoro-zh/（语音）、live2d/（示例模型）
  krino_matrix/ …   Matrix 模型的训练数据
model/ krino/       KRINO Matrix 3-Head 模型与评估接口（互动策略 KRINO_POLICY=matrix 时用）
scripts/            world.sh（运行、数据库、测试）、fetch_assets.py、模型训练和评测脚本
docs/               本文、品牌素材（brand/）、产品哲学
archive/            已下线的决策导航
```

### 后端文件

| 文件 | 职责 |
| --- | --- |
| `main.py` | 入口：路由、延迟统计、错误日志、静态文件（`/static` 前端，`/models` 下载的素材） |
| `config.py` | 全部配置（环境变量）。`service_status()` 只报告“配没配”，不返回密钥 |
| `db.py` / `models.py` | 连接与迁移 / 全部表 |
| `auth.py` | 注册、登录、注销账号、个人设置（按白名单校验） |
| `personas.py` | 角色：增删改查、版本、导入导出、描述生成、行为参数与立绘校验、官方角色（鲸鱼娘、KRINO） |
| `persona_io.py` | 人设格式转换（krino-persona/1、Markdown、SillyTavern / RisuAI 角色卡、旧版鲸鱼娘）与内容安全 |
| `catalog.py` | 官方精选：启动时把一批原创角色上架到工坊（按标题去重） |
| `chat.py` | 一轮互动的唯一主流程，SSE 流式 |
| `policy.py` | KRINO Evaluator 互动策略（规则 / Matrix / 关闭）与硬约束 |
| `prompt.py` | 分层拼系统提示词；解析回复里的 `<state>`；流式时屏蔽标签 |
| `memory.py` | 记忆与关系：提取、校验、更正、检索、淡化、删除记录 |
| `llm.py` / `mock.py` | OpenRouter 适配 / 离线 mock |
| `voice.py` / `tts_local.py` | STT、TTS、VLM 适配 / 本地 Kokoro 语音合成 |
| `devices.py` | KRINO GLASSES：Device Adapter、模拟器 WebSocket、AR 事件校验 |
| `workshop.py` | 创意工坊：发布（拒绝原样的官方角色和重复内容）、领养、更新、评分评论、举报审核 |
| `events.py` | 运行事件、接口延迟、错误；`/api/health`、`/api/services`、`/api/status` |

### 数据（全部在 PostgreSQL）

| 表 | 内容 | 可见范围 |
| --- | --- | --- |
| `users` `auth_tokens` | 账号、令牌哈希、个人设置 | 本人 |
| `characters` `character_versions` | 人格配置（persona / behavior / lore）与历史版本。立绘在 `behavior.portrait` | 本人 |
| `chat_sessions` `messages` | 会话与消息，含每轮策略决策、用到的记忆 | 本人 |
| `memories` `memory_candidates` `memory_tombstones` `memory_jobs` | 记忆、待确认、删除记录（只存哈希）、整理任务 | 本人 × 该角色 |
| `bonds` | 关系状态与会过期的“此刻” | 本人 × 该角色 |
| `workshop_*` | 作品、版本（人设包 JSON）、领养、投票、评论、举报 | 公开（作品）/ 本人 |
| `world_events` | 策略决策、模型 / 语音 / 视觉耗时、设备与 AR 事件 | 本人 |

公开内容只有 `workshop_versions.package`（只含人格配置）。所有私人数据的查询都带 `user_id`，记忆还带 `character_id`。

**改表结构**：改 `models.py` → `scripts/world.sh db revision "说明"` → 检查生成的迁移（外键和删表的顺序、计算列）→ `scripts/world.sh db migrate`。测试会从空库跑一遍全部迁移。

## 角色形象（2D）

`behavior.portrait` 有两种，没有时显示名字铭牌：

- `{"kind": "image", "src": ...}`：一张立绘。可以是 `/static/assets/` 下的内置图，也可以是用户上传的图片（data URL，≤ 2MB）。呼吸、说话时的轻微弹动、预设动作都用 CSS 变换表现；表情用小气泡提示。
- `{"kind": "live2d", "src": "/models/.../*.model3.json"}`：Live2D 模型。眨眼、视线、物理、口型由模型自己完成；表情和预设动作通过参数驱动（`stage.js`）。

立绘地址只接受本站路径或上传的图片，不能指向外部网址。

**为什么不用 3D**：VRM 示例模型和角色风格不搭，程序化的视线和口型容易造成恐怖谷。2D 立绘和整站的插画风一致；Live2D 是行业主流（AIRI 等开源陪伴项目、VTuber 都用它）。

**Live2D 许可**：渲染器 pixi-live2d-display 是 MIT 开源；Cubism Core 是 Live2D 的可再分发代码，但不开源。个人和小企业免费；中型以上企业正式发布前需要签发布许可。示例模型 Hiyori 适用 Live2D 免费素材许可，不进 git，用 `scripts/fetch_assets.py` 下载。

## 语音

- **TTS**：默认 `local`，用 Kokoro-82M 中文版（Apache-2.0）。CPU 上约 2 秒生成 5 秒语音，有 100 个中文音色（`zf_*` 女声，`zm_*` 男声），每个角色可以选自己的音色和语速。没有模型时前端自动退回浏览器朗读。
- **STT**：默认用浏览器识别；配置 OpenAI 兼容接口后由服务端转发。
- **以后**：要更好的音质或声音克隆，可以接 CosyVoice 3（Apache-2.0，需要约 8GB 显存），加一个 `TTS_PROVIDER` 分支即可。

## 官方角色

- **鲸鱼娘**：人设来自中文互联网对 DeepSeek 的拟人化共创（“DeepSeek 娘 / 蓝色大肥鱼”）：能吃白饭（token 便宜）、想得太多（思考链长）、被说便宜会炸毛、傲娇嘴硬。关系里写了 Claude 娘、GPT 娘、千问娘的网友设定，并在边界里注明“这些是梗、不拉踩真实公司”。立绘为 CC0 同人作品，来源见 `assets/CREDITS.md`。
- **KRINO**：KRINO MATRIX 的看板娘，在工坊精选里，一键领养。
- 用户没改过的官方角色（还是第 1 版）会在启动时跟着官方设定更新；改过的不动，可以手动“还原为官方设定”。

## KRINO Evaluator：互动策略

```
事件（说话 / 预设互动 / 安静 / 画面）
  → build_candidates：列出候选行为，标出被硬约束挡住的
  → 打分：rules（默认）| matrix（实验）| off
  → 主行为（NO_ACTION / RESPOND / STORY / PERCEIVE）取最高分；附加行为（EMOTE / ANIMATE / REMEMBER）过阈值就执行
  → chat.py 执行：需要说话才调模型；表情和动作来自策略，模型只能“建议”表情（白名单校验）
```

- **硬约束**（所有策略都在代码里强制）：
  - 要求安静时什么都不做；
  - 没有画面、也没授权摄像头时，不请求画面；
  - 用户关掉动作或剧情，就不做；
  - 主动开口至少隔 5 分钟；
  - 动作和表情必须在角色的白名单里。
- **Matrix 模型**：沿用 `Problem + Action[]` 接口，只用选择头的相对概率排序。现有权重是在决策任务上训练的，没有针对互动行为训练，所以输出标为实验。模型不可用时自动回退到规则策略。

## KRINO GLASSES

- `devices.py` 的 `DeviceAdapter` 有六项能力：摄像头、麦克风、扬声器、AR 显示、IMU、连接状态。目前有 `glasses-sim`（浏览器模拟器，在“设置 → 高级”里）和 `krino-glasses`（真机占位）。
- **输入**：`camera.frame`、`mic.text`、`imu.pose`、`heartbeat`，走和 App 相同的互动流程。
- **输出**：`ar.avatar` / `ar.subtitle` / `ar.panel` / `ar.clear`，由已经执行的行为生成，经过白名单和数值范围校验，模型碰不到渲染。

## 安全与隐私

- 密钥只在服务端环境变量里。语音和视觉都由服务端转发。
- 人设导入只解析数据，有大小、文件数、路径穿越和类型检查；像指令的文字会提示；角色卡的 system_prompt 不进提示词。
- 上传的图片和音频限制类型和大小，只在内存里处理。
- 摄像头需要在设置里允许，并且每次都要浏览器授权。
- 每个角色都标注为 AI。
- 不支持露骨内容和真实人物原型。

## 移除的内容（产品方向调整）

- **成人硬件与设备控制**：鲸鱼娘项目的 `actuation/`、TCode、设备 / 灯光 / 调试台、亲密模式都没有复制进来，原仓库保持原样。
- **决策导航**：移到 `archive/decision-nav/`。
- **3D VRM 形象**：换成了 2D（见上）。
- 测试 `test_no_adult_hardware_or_decision_navigation_routes` 会检查接口和前端里没有这些功能。
