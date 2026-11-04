# KRINO WORLD

[English](README.md) | **简体中文**

KRINO WORLD 是 KRINO MATRIX 旗下的 AI 角色平台：和会记得你的 ACG 角色用文字和语音聊天，创建、导入或在工坊领养角色。默认角色是**大肥鱼**——爱吃白饭、想得太多、嘴硬心软的蓝色大肥鱼。所有角色都标注为人工智能。

| 品牌 | 说明 |
| --- | --- |
| KRINO MATRIX | 母品牌 |
| KRINO WORLD | 软件平台（`app/`） |
| KRINO GLASSES | 未来的眼镜硬件；现在有统一的设备接口和浏览器模拟器 |
| KRINO CORE | 人格、记忆、互动策略（KRINO Evaluator） |

## 快速开始

需要 Python 3.11（推荐 `krino_matrix` conda 环境）和 PostgreSQL 14+（`initdb` / `pg_ctl` 在 PATH 里，或设置 `PG_BIN`）。端到端测试另外需要 Node 18+。

```bash
scripts/world.sh setup            # 装依赖、复制 .env、初始化数据库（data/pgdata/）、下载语音模型和 Live2D 示例（data/models/）
# 编辑 .env：填 OPENROUTER_API_KEY；没有密钥可以设 LLM_PROVIDER=mock 离线演示
scripts/world.sh run              # 前台运行，打开 http://127.0.0.1:8630
scripts/world.sh start | stop | status | logs
```

| 命令 | 作用 |
| --- | --- |
| `scripts/world.sh db init \| start \| stop \| migrate \| psql` | 数据库 |
| `scripts/world.sh db revision "说明"` | 改了 `models.py` 之后生成迁移 |
| `scripts/world.sh test` | 后端测试（独立的测试库，离线 mock 模型） |
| `scripts/world.sh e2e` | 浏览器端到端测试（先 `LLM_PROVIDER=mock scripts/world.sh start`） |
| `python scripts/fetch_assets.py [tts\|live2d]` | 重新下载素材 |

配置都在 [`.env.example`](.env.example) 的 KRINO WORLD 一节。在局域网里的其他电脑上访问时，设 `HOST=0.0.0.0`。

## 用起来是什么样

| 页面 | 内容 |
| --- | --- |
| 聊天 | 左边是她（2D 立绘或 Live2D），右边是对话。回复流式显示；每条回复旁有喇叭，点一下就读；麦克风点一下说话。预设互动（挥手、摸摸头……）。“她记得的”里可以确认、修改、删除记忆，现实 / 推断 / 虚构分开标注 |
| 角色 | 我的角色一排卡片；下面是编辑器：常用字段、形象（内置立绘 / 上传 / Live2D）、音色。其余设定、Markdown / JSON、版本、导入导出、发布都在“更多”里 |
| 工坊 | 官方精选和大家分享的角色，卡片上一键领养。搜索、分类、评分评论、举报；管理员审核 |
| 设置 | 几个开关（自动朗读、主动互动、动作、故事、摄像头、私密记忆），改了立刻生效。“高级”里是模型服务状态、互动策略、眼镜模拟器和运行状态 |

### 语音

默认用本地的 [Kokoro-82M 中文版](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)（Apache-2.0）合成语音：免费、不用密钥、不联网，有 100 个中文音色，每个角色可以选自己的音色。没有模型时自动改用浏览器朗读。语音识别默认用浏览器自带的，Chrome / Edge 支持。

### 2D 形象

- 大肥鱼的立绘来自“蓝色大肥鱼”公开存档里 @MX1951 的投稿，投稿者标注为 CC0。来源和说明见 [`app/frontend/assets/CREDITS.md`](app/frontend/assets/CREDITS.md)。
- Live2D 用开源渲染器 pixi-live2d-display（MIT）加 Live2D 官方的 Cubism Core。
- 示例模型 Hiyori 适用 Live2D 免费素材许可（© Live2D Inc.），由脚本下载，不进 git。
- 中型以上企业正式发布前，需要和 Live2D 签发布许可。

### 互动策略（KRINO Evaluator）

每次事件，策略在七种行为里选择：安静陪着 / 回应 / 幻想剧情 / 看画面 / 表情 / 动作 / 提议记住。

- 默认是规则策略。
- `KRINO_POLICY=matrix` 时用 KRINO Matrix 3-Head 模型。它的权重没有针对互动行为训练，所以输出标为实验。
- 硬约束（比如你要求安静就什么都不做）在代码里强制，不依赖任何策略。

## 目录

```
app/backend    后端（FastAPI + PostgreSQL + alembic）
app/frontend   前端（原生 ES 模块，无构建）
app/e2e        浏览器端到端测试
data/          数据：sources/（数据源代码，进 git）；pgdata/（数据库）、models/（语音、Live2D）、训练数据只在本地
model/ krino/  KRINO Matrix 模型与评估接口
scripts/       world.sh、fetch_assets.py、训练与评测
docs/          架构（ARCHITECTURE.md）、品牌素材、产品哲学
archive/       已下线的决策导航
```

更多见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## KRINO Matrix 模型

`model/dataset.py` 定义 `krino-matrix/1` 样本格式，网络从 `jhu-clsp/mmBERT-base` 训练。训练用 `bash scripts/train.sh`，评测用 `bash scripts/benchmark.sh`。详见[实验报告](experiments/krino-matrix-v1-mmbert/README.md)。

## 已知限制

- 离线 mock 模式的回复和记忆提取是模板，只用于演示和测试，界面上会标“演示”。
- 眼镜目前只有浏览器模拟器。
- 记忆检索用的是 PostgreSQL 全文检索，没有用向量。
- 服务是单进程运行。

## 许可

[Apache License 2.0](LICENSE)。第三方组件：
- PixiJS、pixi-live2d-display：MIT；
- Live2D Cubism Core：Live2D 专有许可（可再分发）；
- Kokoro：Apache-2.0；
- 大肥鱼立绘：CC0（投稿者标注）。
