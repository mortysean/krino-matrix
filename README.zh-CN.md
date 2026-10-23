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
| `Decision` | 最终选择的行动及其得分 |

### 核心模块

| 模块 | 输入 → 输出 | 作用 |
| --- | --- | --- |
| Problem Formulator | 自然语言请求 → `Problem` | 把用户的请求转化为决策问题 |
| Observer | `Problem` + 数据源 → `State` | 从数据源收集决策所需的数据，补充进状态 |
| Action Generator | `State` + 目标 + 约束 → `ActionSpace` | 生成候选行动 |
| Action Evaluator | `State` + 目标 + `Action` → 得分 | 评估行动的价值 |

每个模块都是抽象接口，`api_*` 实现基于托管的大模型。

### 流水线

`Pipeline` 把各模块串成一次完整决策：

```
请求 ─▶ Formulator ─▶ Observer ─▶ Generator ─▶ Evaluator ─▶ 决策（按得分排序）
                         ▲
                       数据源
```

Observer 可选；不接入时，状态只包含 Formulator 从请求中读出的信息。候选行动并发评估。

### 数据源

`DataSource` 提供一组 `Query`，每个 `Query` 有名称、说明和参数结构。API Observer 把它们作为工具交给大模型调用，查询结果原样存入状态的 `observations`，数字不经过大模型转述。

内置数据源：

| 数据源 | 覆盖范围 |
| --- | --- |
| `SagaxSource`（[sagax 数据平台](https://www.sagax.cn/data/v1/)） | A 股股票（选股、估值、财务、资金流向）、指数、ETF、期货、期权、专题报表、宏观指标、新闻、公告和研报 |

sagax 是作者自建的数据平台：每日从 tushare、tqsdk 等来源采集中国市场数据，财务数据按时点（PIT）口径保存，通过 HTTP API 和 Python SDK `sagax-data` 对外提供。数据表、指标和示例见 [sagax 官网](https://www.sagax.cn/data/v1/)；查询需要 API key 和 secret。

## 项目结构

```
core/
  schema.py         基本元素
  pipeline.py       端到端流水线
  formulator/       Problem Formulator（api_formulator）
  observer/         Observer（api_observer）
  generator/        Action Generator（api_generator）
  evaluator/        Action Evaluator（value_evaluator）
  data/             DataSource / Query 接口，sagax 数据源
services/
  llm.py            统一的大模型接口，支持 OpenRouter、litellm 和 Anthropic SDK
examples/           可运行的示例
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env    # 填入大模型服务商和 sagax API key
```

| 示例 | 运行内容 |
| --- | --- |
| `python examples/api_formulator_demo.py ["请求"]` | 仅 Formulator |
| `python examples/api_generator_demo.py` | 仅 Generator，使用手写的状态 |
| `python examples/data_demo.py` | sagax 数据查询 |
| `python examples/pipeline_demo.py ["请求"]` | 完整流水线 |
| `python examples/value_evaluator_demo.py [data.jsonl]` | 价值评估器：微调、保存、加载、打分 |

## 进度

- 已实现：Formulator、Observer、Generator、sagax 数据源、流水线
- 进行中：Action Evaluator —— `value_evaluator` 是非自回归的价值模型（文本编码器 + 线性头，每个行动一次前向），附最简训练循环；还缺标注数据，所以 `pipeline_demo.py` 仍用占位实现，所有行动得分相同

## 许可证

[Apache License 2.0](LICENSE)
