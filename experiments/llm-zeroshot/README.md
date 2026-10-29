# LLM 零样本基线（deepseek flash）

## 目的

`MatrixEvaluator`（`krino/evaluator/`）一次前向就同时给出每个行动的目标达成五档分布、每个行动违反每条约束的概率和该选哪个行动，它要替代的是“每个决策直接调用一次 LLM”。这个实验把那条被替代的路真实地跑一遍：每条 test case 只调用一次 deepseek flash，用**和 teacher 完全相同的 prompt 和输出 schema**，再按与小模型相同的方式打分。得到三个数：

- **效果**：直接问 LLM，在 goal / constraints / selection / decision 四个口径上做到什么水平；
- **延迟**：一次调用端到端要多久（并发 1 实测，不受队列影响）；
- **成本**：一次调用多少 token、折合每千次决策多少钱。

和 `experiments/krino-matrix-v1-mmbert/` 的小模型结果对照时，请先读报告第一节：`LLM_DEFAULT` 的 `served_model` 解析出来是 `deepseek/deepseek-v4.1-flash-1017`，**就是给这批数据打标签的 teacher**。所以这不是“换一个更强的模型”的对照，而是“用一次 temperature 0 的调用去复原 teacher 三次 temperature 0.7 采样的平均”能到什么程度，是蒸馏上限的直接读数。

## 怎么做的

- 模型：`.env` 的 `LLM_DEFAULT`（`~deepseek/deepseek-flash-latest`），通过 `krino/llm.py` 的 `LLM()` 与 `astructured()` 调用，temperature 0。
- prompt 和 schema 直接 import 自 `scripts/build_data.py`：`LABEL_PROMPT`、`GOAL_TASK`、`CONSTRAINTS_TASK`、`BEST_TASK`、`teacher_output`、`levels_text`、`constraints_list`、`normalized`，与 `label()` 的构造方式相同（三个任务都问，best 总是问）。
- 行动顺序：每条 case 用固定种子 0 打乱一次（不依赖进程哈希种子），记录在 `raw/<set>.jsonl` 的 `shown`。
- 不合法就重试，最多 4 次尝试：goal 不是 5 个和为 1 的概率、违反概率不在 [0, 1]、violations / best 没覆盖全部行动或约束、best 不是分布、JSON 解析失败或截断。最终仍失败记 `error`，报告单独统计。
- 调用方设置：`reasoning={"effort": "none"}`、`max_tokens=4000`、单次尝试 120 s、每条 case 累计 300 s。默认深度思考时模型在这个 prompt 上几乎不闭合 JSON（见报告“设置”一节），这是部署方自己会做的取舍，不属于评测本身。
- 输出 → `Assessment`：`labels.goal` / `labels.constraints` / `labels.best` 来自模型答案；`excluded` = 任一硬约束违反概率 ≥ 0.5 的行动；`choice` = 未被排除的行动里 best 最大的（与 `MatrixEvaluator.assess` 无异）；全部被排除则 `choice=None`（弃权）。
- 打分：直接 import `scripts/benchmark.py` 的 `score()`，模型名 `llm-zeroshot-flash`。
- 延迟：并发 1 对每个数据前 50 条再问一遍，取 `latency_ms` 的 p50 / p95，结果 JSON 的 `latency_ms` 用的就是它；正式跑并发 16。token 和成本：每个数据 100 条、并发 16 的探测，`LLM.astructured` 拿不到用量，所以从 HTTP 响应里审计（只包 litellm 的传输层，不改 `krino/llm.py`）。

## 运行

```bash
PY=~/anaconda3/envs/krino_matrix/bin/python
$PY experiments/llm-zeroshot/run.py --limit 3              # 冒烟：每个数据前 3 条，检查输出格式
$PY experiments/llm-zeroshot/run.py --probe --latency-probe 50   # 并发 1 的延迟探测（约 10 分钟）
$PY experiments/llm-zeroshot/run.py --cost --cost-cases 100      # token / 成本探测（并发 16）
$PY experiments/llm-zeroshot/run.py                        # 正式：zh 450 + en 225，并发 16
$PY experiments/llm-zeroshot/report.py                     # 由上面的产物生成 results/report.md
```

不需要 GPU（只用了 torch 的 import 和 numpy），不碰 `km-train` / `km-next` / `km-final`。断点续跑：答案逐条追加进 `raw/<set>.jsonl`，重跑只问还没有可用记录的 case；想重问某条就删掉它的行，或删掉整个文件。探测结果每次按数据整体覆盖写。

## 产物

| 路径 | 内容 | 进 git |
|---|---|---|
| `run.py` | 调用、重试、探测、打分、写结果 JSON | 是 |
| `report.py` | 由下面的文件生成 `report.md`（含 bootstrap 区间、成本表） | 是 |
| `raw/zh.jsonl`, `raw/en.jsonl` | 每条 case 的 `shown`、`attempts`、`latency_ms`、`assessment` 或 `error` | 是 |
| `results/llm-zeroshot-flash.json` | `{"model", "sets": {set: {n_cases, **score(), latency_ms, assessments}}}` | 是 |
| `results/report.md` | 指标表、失败与重试、延迟 / token / 成本、served_model 与 teacher 的比较 | 是 |
| `results/probe.jsonl` | 延迟探测：每条 case 的墙钟与它背后的单次调用（token、ms） | 是 |
| `results/cost.jsonl` | 成本探测：同上，并发 16 | 是 |
| `results/audit.jsonl` | 每次 HTTP 回答一行：输入 / 输出 token、结束原因、耗时 | 是 |
| `logs/` | 每次运行的终端输出 | 是 |

## 不在本实验里

- 不调 prompt、不做 few-shot、不做 self-consistency：要测的就是“每个决策一次调用”这条部署路径。
- 不改 `krino/`、`scripts/`、`data/`，也不改 `experiments/krino-matrix-v1-mmbert/` 里除 `results/` 之外的内容。
- 只用 OpenRouter 上的 deepseek flash，不换模型、不接别的 provider。
