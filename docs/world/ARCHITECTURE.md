# KRINO WORLD 架构与改造记录

本文记录这次产品方向调整的仓库检查结论、复用范围、移除内容，以及各层怎么扩展。日常开发先看这一篇。

## 1. 仓库检查结论（改造前）

| 项目 | 位置 | 技术栈 | 状态 |
| --- | --- | --- | --- |
| Whale Girl（鲸鱼娘） | `~/whale-gril-companion`（独立仓库，未改动） | FastAPI + PostgreSQL；原生 JS 单页（无构建）；人设与记忆存 Obsidian vault（Markdown 文件） | 工作区有大量未提交的修改（创意工坊、AI娘、用户画像），按“最新设计”参考，**只读取不修改** |
| KRINO MATRIX | 本仓库 `main` 分支 | `model/` 3-Head Matrix 模型（mmBERT）；`krino/` 决策流程；`backend/` + `frontend/`（React）决策导航 | 决策导航整体下线，模型保留 |

## 2. 复用范围

| 来源 | 复用了什么 | 怎么改的 |
| --- | --- | --- |
| Whale Girl 前端 | 钴蓝铜版画视觉：色板、字体、颗粒、按钮、卡片、弹窗、提示、开场动画、登录页、侧栏 CAST / INDEX 编号导航、记忆侧栏、创意工坊卡片、关系面板；鲸鱼娘线稿立绘与头像（`frontend/assets/kujira-*.png`、`mascot.js`） | `style.css` 删掉设备 / 灯光 / 成人模式 / 手账的样式，追加 3D 舞台、编辑器、眼镜模拟器的样式（同一套变量）；单个 1200 行的 `app.js` 拆成按页面划分的 ES 模块 |
| Whale Girl 后端 | 账号与令牌、人设导入导出（SillyTavern / RisuAI 角色卡、Markdown、JSON、旧版人设包）及安全检查、记忆提取与校验规则（原话出处、假设 / 转述 / 角色扮演过滤、敏感信息确认、更正链、删除记录）、关系阶段、创意工坊（发布、版本、导入更新、评分、评论、举报、自动隐藏、审核）、离线 mock 模型 | 存储从“vault 文件 + 数据库索引”改为**全部 PostgreSQL**；`roleplay` 扩展为 `story`（虚构故事，含幻想剧情）；成人相关字段全部去掉 |
| KRINO MATRIX | `model/`（3-Head 网络与推理）、`krino/evaluator/`、`krino/common/schema.py` | 作为内部互动策略的一个实现（`KRINO_POLICY=matrix`），见第 5 节 |

## 3. 移除的内容

- **成人硬件与设备控制**：Whale Girl 的 `actuation/`（设备接口、TCode 适配器与仿真固件、动作映射、心跳闸门、灯光模拟器）、`routers/device.py`、`routers/ambient.py`、`routers/lab.py` + 调试台、亲密 / 成人模式（会话 mode、`adult_confirmed`、敏感模式门控、提示词里的成人规则、mock 的推进类意图）、`behavior.json` 里的动作模板——**一行都没有复制进来**，原仓库保持原样。导入旧版人设包时，旧的动作模板被忽略，默认的成人边界句会被去掉。
- **决策导航**：`backend/`、`frontend/`、`krino/engine.py`、`krino/steps/` 与对应测试移到 `archive/decision-nav/`（`git mv`，保留历史），见 `archive/README.md`。
- 也没有带过来：手账 / 知识库图谱、AI娘社交圈（串门、好友、鲸号）、荣格八维用户画像、AI 生成头像。它们和这次的目标无关，需要时可从 Whale Girl 仓库再移植。

`backend/tests/test_acceptance.py::test_no_adult_hardware_or_decision_navigation_routes` 会检查接口和前端代码里没有这些功能。

## 4. 结构

```
backend/
  app/
    main.py          入口：路由、延迟统计中间件、错误日志、静态前端
    config.py        全部配置（环境变量）；service_status() 只报告“配没配”，不含密钥
    db.py            连接；migrate() = alembic upgrade head
    models.py        全部表（见下）
    auth.py          注册登录、令牌、个人设置（按分组白名单校验）
    personas.py      人格配置：CRUD、版本、导入导出接口、描述生成、行为参数校验、官方角色 WHALE GIRL
    persona_io.py    人设格式转换（krino-persona/1、Markdown、角色卡、旧版鲸鱼娘）与内容安全
    chat.py          一轮互动的唯一主流程（计划 → 执行 → 收尾），SSE 流式
    policy.py        KRINO Evaluator 互动策略（规则 / Matrix / 关闭）+ 硬约束
    prompt.py        系统提示词分层拼装；解析回复里的 <state>；流式输出时屏蔽标签
    memory.py        记忆与关系：提取、校验、去重 / 更正、检索、淡化、删除记录、接口
    llm.py / mock.py 模型适配（OpenRouter）与离线 mock
    voice.py         STT / TTS / VLM 适配层（浏览器 / OpenAI 兼容 / mock）
    devices.py       KRINO GLASSES：Device Adapter、眼镜模拟器 WebSocket、AR 事件校验
    avatars.py       VRM 上传（格式 / 大小 / 许可信息）与角色形象选择
    workshop.py      创意工坊
    events.py        运行事件、延迟、错误；/api/health、/api/services、/api/status
  migrations/        alembic 迁移
  tests/             pytest（单元 + 接口验收 + 设备）
frontend/
  index.html  style.css  mascot.js  assets/  vendor/（three、three-vrm，固定版本）
  js/  main.js（入口、路由）core.js（接口、弹窗、事件总线）avatar.js（3D）voice.js
       chat.js memory.js persona.js workshop.js glasses.js settings.js（每个页面一个模块）
tests/e2e/           浏览器端到端测试（Playwright + 真实服务）
scripts/world.sh     启动、数据库、测试的统一入口
```

### 数据（全部在 PostgreSQL）

| 表 | 内容 | 可见范围 |
| --- | --- | --- |
| `users` `auth_tokens` | 账号、令牌哈希、个人设置 | 本人 |
| `characters` `character_versions` | 人格配置（persona / behavior / lore）与历史版本 | 本人 |
| `avatar_models` | 上传的 VRM（文件本身也在库里）与许可信息 | 本人 |
| `chat_sessions` `messages` | 会话与消息（含每轮策略决策、用到的记忆） | 本人 |
| `memories` `memory_candidates` `memory_tombstones` `memory_jobs` | 记忆、待确认、删除记录（只有哈希）、整理任务 | 本人 × 该角色 |
| `bonds` | 关系状态与会过期的“此刻” | 本人 × 该角色 |
| `workshop_*` | 工坊作品、版本（人设包 JSON）、导入、投票、评论、举报 | 公开（作品）/ 本人（导入） |
| `world_events` | 策略决策、LLM / 语音 / 视觉耗时、设备与 AR 事件 | 本人 |

私人数据与公开内容的隔离：公开内容只有 `workshop_versions.package`（由 `persona_io.to_package` 生成，只含人格配置）。所有私人数据的查询都带 `user_id`，记忆还带 `character_id`。

### 改表结构

1. 改 `backend/app/models.py`；
2. `scripts/world.sh db revision "说明"` 自动生成迁移，检查生成的文件（尤其是计算列、索引）；
3. `scripts/world.sh db migrate`；测试会从空库跑一遍全部迁移。

## 5. KRINO Evaluator：互动策略

```
事件（说话 / 预设互动 / 安静 / 画面）
  → build_candidates：列出候选行为，标出被硬约束挡住的
  → 策略打分：rules（默认）| matrix（实验）| off
  → 主行为（NO_ACTION / RESPOND / STORY / PERCEIVE）取最高分；附加行为（EMOTE / ANIMATE / REMEMBER）过阈值就执行
  → chat.py 执行：要说话才调模型；表情和动作来自策略，模型只能“建议”表情（白名单校验）
```

- **硬约束在代码里**，不依赖任何策略：要求安静就不说话；没有画面也没授权摄像头就不请求画面；用户关掉动作 / 剧情就不做；安静时主动开口至少隔 5 分钟；动作和表情必须在角色的白名单里。
- **3-Head 模型适配**：沿用 `Problem(goal, constraints, state) + Action[]` 接口，每个候选行为是一个 action，只用选择头的相对概率排序。现有权重 `mmbert-uncertainty` 是在“决策问题 + 候选行动”数据上训练的，**没有针对互动行为训练**：输出标注为实验、只作对照，界面上明确写出。模型不可用（没权重、加载失败、推理报错）时自动回退规则策略并记录原因。CPU 上首次加载约 10 秒，之后每次约 250 ms。
- 让模型真正适配互动行为需要：互动场景数据（事件 + 人格 + 候选行为 + 标注的最佳行为）；把人格参数编码进 state；重新训练选择头（目标头 / 约束头可以不用）。接口不用改。

## 6. KRINO GLASSES 兼容

- `devices.py` 的 `DeviceAdapter`：摄像头 / 麦克风 / 扬声器 / AR 显示 / IMU / 连接状态六项能力。现在注册了 `glasses-sim`（浏览器模拟器）和 `krino-glasses`（真机占位，不可用）。
- 设备输入：`camera.frame`、`mic.text`、`imu.pose`、`heartbeat`，走和 App 完全相同的互动流程。
- 设备输出：`ar.avatar`（表情、动作、相对头部的锚点）、`ar.subtitle`、`ar.panel`、`ar.clear`。由已经执行的行为生成，pydantic 白名单 + 数值范围校验，模型碰不到渲染。
- 接真机：实现一个 `DeviceAdapter` 子类（连接、能力），在 SDK 回调里把输入转成上面的消息，把 AR 事件转成设备的显示指令。

## 7. 安全与隐私要点

- 密钥只在服务端环境变量里；`/api/services` 只返回 provider / model / 是否就绪。语音和视觉都由服务端转发。
- 人设导入：只解析数据（JSON / YAML safe_load / PNG 文本块 / zip 里的 .md .json），有大小、文件数、路径穿越、类型检查；像指令的文字在预览里提示，提示词里把人设标为“资料而不是指令”；角色卡的 system_prompt 不进提示词。
- 上传：VRM 校验 glTF 头和 VRM 扩展、大小；图片只接受 PNG / JPEG / WebP data URL 且限制大小、只在内存里处理；音频限制类型和大小。
- 摄像头 / 麦克风：需要在设置里允许，并且每次都由浏览器授权；离开眼镜页立即关闭。
- 每个角色都标注为 AI：界面徽标、登录页说明、系统提示词要求被问到时如实说明（有测试）。
- 内容：不支持露骨内容和真实人物原型（导入、生成、编辑、工坊发布、评论都检查）。
