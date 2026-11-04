# KRINO WORLD

[English](README.md) | **简体中文**

KRINO WORLD 是 KRINO MATRIX 旗下以 ACG 虚拟人物为核心的 AI 角色平台：创建或导入人格，用文字、语音和 3D 形象和角色互动；角色会积累经过你确认的共同经历，表现出稳定而可以演化的人格。默认官方角色是 **WHALE GIRL（鲸鱼娘）**。所有角色都标注为人工智能。

| 品牌 | 说明 |
| --- | --- |
| KRINO MATRIX | 母品牌 |
| KRINO WORLD | 软件平台（本仓库的 `backend/` + `frontend/`） |
| KRINO GLASSES | 未来的硬件：第一人称视觉、听觉与 AR 显示。现在提供统一的设备接口和浏览器模拟器 |
| KRINO CORE | 底层系统：人格、记忆、互动策略（KRINO Evaluator） |

## 快速开始

需要：Python 3.11（推荐 `krino_matrix` conda 环境）、PostgreSQL 14+（`initdb` / `pg_ctl` 在 PATH 里，或设置 `PG_BIN`）、Node 18+（只有端到端测试需要）。

```bash
scripts/world.sh setup            # 装依赖、复制 .env、初始化本地数据库（.pgdata/，端口 5433）并迁移、下载默认 3D 模型
# 编辑 .env：填 OPENROUTER_API_KEY（或 LLM_OPENROUTER_API_KEY）；没有密钥可以设 LLM_PROVIDER=mock 离线演示
scripts/world.sh run              # 前台运行，打开 http://127.0.0.1:8630
scripts/world.sh run --reload     # 开发：改后端代码自动重启
scripts/world.sh start | stop | status | logs    # 后台运行（日志 .run/world.log）
```

数据库：

```bash
scripts/world.sh db init | start | stop | status
scripts/world.sh db migrate                  # 升级到最新表结构（服务启动时也会自动执行，AUTO_MIGRATE=0 关闭）
scripts/world.sh db revision "说明"          # 改了 models.py 之后生成迁移
scripts/world.sh db psql                     # 进数据库
```

测试：

```bash
scripts/world.sh test                         # 后端：单元 + 接口验收 + 设备（独立的测试库，离线 mock 模型）
LLM_PROVIDER=mock scripts/world.sh start      # 端到端测试需要先启动服务
scripts/world.sh e2e                          # 浏览器端到端（tests/e2e，截图在 tests/e2e/shots/）
```

环境变量全部在 [`.env.example`](.env.example) 的 KRINO WORLD 一节：数据库、LLM / VLM / STT / TTS、互动策略、创意工坊管理员与审核、上传上限。

## 功能

| 页面 | 内容 |
| --- | --- |
| 01 互动 | 3D VRM 角色居中（眨眼、视线、呼吸、表情、口型、预设动作）；文字 / 语音切换，回复流式显示；用户可以主动触发挥手、摸摸头、击掌等有限的预设互动；发图片给她看；聊天历史和“她记得的”侧栏；模型加载失败自动换内置形象，断网有提示并保留输入 |
| 02 人格 | 名称、简介、背景、性格、价值倾向、语言风格、兴趣、行为偏好、世界观、角色关系、互动边界、开场白、设定笔记；互动风格（话量、表情丰富度、主动程度、爱讲故事）、可用表情与动作、音色；表单 / Markdown / JSON 三种编辑；版本与恢复；导入导出；描述生成；上传 VRM 形象 |
| 03 记忆 | 记忆列表（现实事件 / 模型推断 / 虚构故事分开标注）、确认待定记忆、修改（保留更正历史）、不再记住、彻底删除；关系阶段、称呼、里程碑、她对你的印象、会过期的“此刻”；导出记忆包 |
| 04 创意工坊 | 浏览、搜索、分类、标签、排序；详情预览；导入、下载人设包；发布自己的角色或直接上传文件；版本更新；评分、评论；举报与自动隐藏；管理员审核 |
| 05 眼镜 | KRINO GLASSES 模拟器：摄像头 / 麦克风 / 头部姿态作为设备输入，角色行为以 AR 事件显示在模拟镜片上 |
| 06 设置 | LLM / VLM / STT / TTS 服务状态；语音、互动、隐私偏好；KRINO Evaluator 开关与测试；眼镜连接状态；运行状态（接口延迟、错误、事件） |

### 互动怎么决定：KRINO Evaluator

KRINO Evaluator 现在只作为内部的互动策略（Interaction Policy），不向用户展示排名。每次事件（你说话、做了一个互动动作、安静了一阵、分享了画面）它在七种行为里选择：

`NO_ACTION` 保持安静 · `RESPOND` 回应 · `STORY` 幻想剧情 · `PERCEIVE` 多模态理解 · `EMOTE` 表情 · `ANIMATE` 预设动作 · `REMEMBER` 建议记住

| `KRINO_POLICY` | 说明 |
| --- | --- |
| `rules`（默认） | 规则策略，参数来自角色的互动风格和你的设置。输出标注“规则策略（非模型输出）” |
| `matrix` | KRINO Matrix 3-Head 模型（`model/checkpoints/mmbert-uncertainty`），沿用原接口。**权重没有针对互动行为训练**，输出只作实验对照；不可用时自动回退规则策略 |
| `off` | 只回应，不做额外动作 |

无论哪种策略，硬约束都在代码里强制（你要求安静就不说话、没授权摄像头就不请求画面……）。详见 [docs/world/ARCHITECTURE.md](docs/world/ARCHITECTURE.md)。

### 语音与视觉

- **STT / TTS**：默认用浏览器自带的识别和朗读（Chrome / Edge 支持识别；Chrome 会把音频发给浏览器厂商的服务）。配置 `STT_PROVIDER=openai` / `TTS_PROVIDER=openai` 和 OpenAI 兼容的地址后由服务端转发，密钥不进浏览器。
- **VLM**：默认 `mock`，只读颜色和亮度，回复里明确标“模拟视觉”；配置 `VLM_PROVIDER=openai` 使用真实的视觉模型。

### 3D 形象

默认形象是 pixiv 的 VRM 示例模型（VRM Public License 1.0，允许再分发），由 `scripts/fetch_vrm.py` 下载到 `frontend/assets/vrm/`（不进 git，许可信息见同目录 `LICENSE.md`）。下载不到、浏览器不支持 WebGL 或模型加载失败时，自动换成内置的程序化形象或平面立绘。用户可以在“人格”页上传自己的 `.vrm`（VRM 0.x / 1.0，≤ 40MB）。Three.js 0.186.1 与 @pixiv/three-vrm 3.5.5 已放在 `frontend/vendor/`（MIT）。

## 目录

```
backend/            KRINO WORLD 后端（FastAPI + PostgreSQL + alembic），结构见 docs/world/ARCHITECTURE.md
frontend/           KRINO WORLD 前端（沿用鲸鱼娘的视觉；原生 ES 模块，无构建）
tests/e2e/          浏览器端到端测试
scripts/world.sh    运行、数据库、测试
scripts/fetch_vrm.py  下载默认 3D 模型
model/              KRINO Matrix 3-Head 模型（训练、推理）
krino/              模型的评估接口与基础数据结构
data/ experiments/  模型的数据脚本与实验记录
archive/            已下线的决策导航（见 archive/README.md）
```

## KRINO Matrix 模型

`model/dataset.py` 定义 `krino-matrix/1` 样本格式；网络有目标、约束、行动选择三个头，从 `jhu-clsp/mmBERT-base` 训练。训练与评测：

```bash
bash scripts/train.sh [out_dir] [seed]
bash scripts/benchmark.sh [checkpoint ...]
```

训练细节与结果见[实验报告](experiments/krino-matrix-v1-mmbert/README.md)。

## 当前状态与已知限制

- 离线 mock 模式下的回复和记忆提取是模板和正则，只用于演示和测试，界面上标“演示模式”。
- Matrix 策略是实验性的（见上）；规则策略是默认。
- 眼镜只有浏览器模拟器；真机适配器是占位，等 SDK。
- 记忆检索是 PostgreSQL 全文检索（jieba 分词 + 中文二元组），没有用向量；pgvector 留作后续，表结构里的 `search_text` 可以平滑扩展。
- 单进程运行（眼镜模拟器的 WebSocket 连接在进程内）。

## 许可

[Apache License 2.0](LICENSE)。第三方：three.js（MIT）、@pixiv/three-vrm（MIT）、默认 VRM 模型（VRM Public License 1.0）。
