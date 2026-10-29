# Krino Matrix

[English](README.md) | **简体中文**

Krino Matrix 致力于解放人的认知资源。

我们希望通过人工智能理解复杂状态、生成可行方案并评估行动价值，降低人们在信息处理、分析和决策上的认知负担，让每个人都能将有限的认知资源投入更有创造性、更有价值的事情中。

## 核心概念

### 基本元素

| 元素 | 说明 |
| --- | --- |
| `State` | 当前状态 |
| `Problem` | 决策问题：`State` + 目标 + 约束 |
| `Action` | 单个候选行动 |
| `ActionSpace` | 候选行动的集合 |

### 核心模块

| 模块 | 输入 → 输出 | 作用 |
| --- | --- | --- |
| Problem Formulator | 自然语言请求 → `Problem` | 把用户的请求转化为决策问题 |
| Clarifier | 请求 + `Problem` → 一个问题或不问 | 只追问可能改变推荐结果的那一条缺失信息 |
| Action Generator | `State` + 目标 + 约束 → `ActionSpace` | 生成候选行动 |
| Action Evaluator | `Problem` + `ActionSpace` → 排序 | KRINO Matrix 模型：给候选行动排序，排除违反硬约束的行动 |

Formulator、Clarifier、Generator 调用托管的大模型；评估器是训练好的 Matrix 模型。

### 决策流程

`krino/engine.py` 的 `DecisionEngine` 把各模块串成一轮完整决策：

```
请求 ─▶ Formulator ─▶ Clarifier ─▶ Generator ─▶ Ranker ─▶ 安全规则 ─▶ 决策
```

Ranker 是基于 `jhu-clsp/mmBERT-base`、用 uncertainty loss 加权训练的 Matrix 评估器（见 `krino/ranker/`）。

### 数据源

`DataSource` 提供一组 `Query`，每个 `Query` 有名称、说明和参数结构，可以作为工具交给大模型调用。数据源暂未接入决策流程。

内置数据源：

| 数据源 | 覆盖范围 |
| --- | --- |
| `SagaxSource`（[sagax 数据平台](https://www.sagax.cn/data/v1/)） | A 股股票（选股、估值、财务、资金流向）、指数、ETF、期货、期权、专题报表、宏观指标、新闻、公告和研报 |

sagax 是作者自建的数据平台：每日从 tushare、tqsdk 等来源采集中国市场数据，财务数据按时点（PIT）口径保存，通过 HTTP API 和 Python SDK `sagax-data` 对外提供。数据表、指标和示例见 [sagax 官网](https://www.sagax.cn/data/v1/)；查询需要 API key 和 secret。

## 项目结构

```
krino/                核心 Python 包
  engine.py           一轮决策的完整流程，以及 Web 使用的 build_engine()
  steps/              调用大模型的三个步骤
    formulator.py       请求 → 决策问题
    clarifier.py        必要时追问一个关键问题
    generator.py        生成候选行动
  ranker/             排序与安全
    base.py             Ranker 接口
    matrix.py           Matrix 模型排序
    rules.py            显式安全规则
  common/             各部分共享
    schema.py           基本元素
    contract.py         返回给客户端的 clarification / decision / error 响应
    matrix.py           训练与评测用的样本格式
    llm.py, tracing.py  大模型接口（OpenRouter、litellm、Anthropic SDK）与调用记录
  data/               DataSource / Query 接口，sagax 数据源
model/                Matrix 模型
  network.py          网络结构（训练和推理共用）
  training/           训练框架：trainer.py（训练与校准）、train.py（训练命令）、benchmark.py（评测）
  inference/          推理框架：MatrixEvaluator，一次前向、硬约束过滤、再选择
  checkpoints/        训练好的权重（git 忽略），Web 使用 mmbert-uncertainty
data/                 构建与检查数据集的脚本、sagax 示例；数据集和数据库本身 git 忽略
scripts/              常用 bash 脚本：训练、评测、启动 Web、测试
backend/              FastAPI、认证、对话与持久化
frontend/             React + Vite Web 应用
experiments/          可复现的模型实验和报告
tests/                后端与决策流程测试
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env    # 填入大模型服务商和 sagax API key
```

| 命令 | 运行内容 |
| --- | --- |
| `bash scripts/serve.sh` | 构建前端并启动 Web 应用（`--dev` 只启动 API，配合 `npm run dev`） |
| `bash scripts/test.sh` | 后端与决策流程测试，不调用模型 |
| `bash scripts/train.sh [输出目录] [种子]` | 按当前配置训练 Matrix 模型（mmBERT-base、uncertainty 加权） |
| `bash scripts/benchmark.sh [检查点 ...]` | 在测试集上评测，默认评测 `model/checkpoints/mmbert-uncertainty` |
| `python data/build_data.py ...` | 用教师 LLM 构建并标注数据集，其余数据脚本见 [data/README.md](data/README.md) |
| `python data/sagax_demo.py` | sagax 数据查询 |

## Web 决策助手（V2.5 P0）

按[《KRINO MATRIX V2.5 精简需求》](KRINO_MATRIX_V2.5_%E7%B2%BE%E7%AE%80%E9%9C%80%E6%B1%82_%E8%A7%86%E8%A7%89%E5%8A%A8%E6%95%88%E5%A2%9E%E5%BC%BA%E7%89%88.docx)实现的第一版：输入目标 → 提取状态/约束 → 必要时澄清（最多 3 问，可跳过）→ 生成 2–4 个候选 → 评估排序 → 行动卡 → 选择与反馈。

| 目录 | 内容 |
|---|---|
| `krino/` | 与设备无关的决策流程：统一的 clarification / decision / error 响应、澄清、候选生成、Matrix 排序（显示真实输出的选择倾向；检查点由 `KRINO_MATRIX_CHECKPOINT` 指定）、显式安全规则 |
| `backend/` | FastAPI：邮箱登录、对话与决策快照、反馈、个人记忆、使用量、调用耗时与失败记录；PostgreSQL（本地开发可用 SQLite） |
| `frontend/` | React + Vite：Today / 对话 / 决策详情 / 设置，演示动画、进度轨迹、移动端适配、减少动效 |

```bash
pip install -r requirements.txt
bash scripts/serve.sh          # 打开 http://localhost:8000
# 开发时前端热更新：bash scripts/serve.sh --dev 与 (cd frontend && npm run dev) 同时运行
bash scripts/test.sh           # 后端与决策流程测试，不调用模型
```

配置见 `.env.example` 的 Web 部分（`DATABASE_URL`、`KRINO_SECRET_KEY`、`KRINO_MATRIX_CHECKPOINT` 等）。邮件服务尚未接入，找回密码的链接写在服务器日志中；余额、充值和 BYOK 在设置中标为未上线。

## 模型实验

`krino/common/matrix.py` 定义了 `krino-matrix/1` 样本格式。Matrix 评估器分别预测目标达成度、约束违反和行动选择；硬约束规则会在选择前过滤不安全的候选。训练数据放在 `data/krino_matrix/{zh,en}`，模型检查点保存在本地（Git 忽略）。当前模型从小模型 `jhu-clsp/mmBERT-base`（多语言 encoder）自行训练，三个任务头全部从零初始化，loss 用 uncertainty 加权；本地只保留这一个检查点 `model/checkpoints/mmbert-uncertainty`。训练方式与结果见[实验报告](experiments/krino-matrix-v1-mmbert/README.md)。

## 进度

- 已实现：Formulator、Clarifier、Generator、决策引擎、sagax 数据源
- 已实现，实验阶段：`MatrixEvaluator` 一次前向预测目标达成度、约束违反和行动选择；Web 应用需要训练好的检查点才能给候选排序。

## 许可证

[Apache License 2.0](LICENSE)
