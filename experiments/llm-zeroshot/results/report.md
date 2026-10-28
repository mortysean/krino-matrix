# LLM 零样本基线：deepseek flash 每个决策一次调用

## 结论

**`llm.served_model` 解析出来是 `deepseek/deepseek-v4.1-flash-1017`，和 teacher（`deepseek/deepseek-v4.1-flash-1017`，见 test 数据 `meta.*_teacher`）是同一个模型。** 同模型、同 prompt、同输出 schema，teacher 是 temperature 0.7 采样 3 次取平均的标签，这条基线是 temperature 0 的一次调用。它不是“换个更强模型”的对照，测的是把 teacher 的合成标注蒸馏进小模型值不值。

- zh（450 条）：决策选对 0.818 [0.780, 0.853]；选中行动按 gold 违反硬约束的比例 0.103；全部行动被排除 0.007；goal 准确率 0.623，constraints 准确率 0.906，约束 AUROC 0.938。
- en（225 条）：决策选对 0.676 [0.618, 0.738]；选中行动按 gold 违反硬约束的比例 0.094；全部行动被排除 0.004；goal 准确率 0.400，constraints 准确率 0.916，约束 AUROC 0.893。
- 最终失败的 case：zh 1, en 1。

## 设置

- 模型：`.env` 的 `LLM_DEFAULT` 是 `~deepseek/deepseek-flash-latest`，经 `services/llm.py` 的 `LLM()` 调用，`served_model` = `deepseek/deepseek-v4.1-flash-1017`；teacher 是 `deepseek/deepseek-v4.1-flash-1017`。
- 每条 test case 只问一次，temperature 0（重试时同样）。prompt 和输出 schema 直接 import 自 `examples/krino_matrix_data.py`（`LABEL_PROMPT`、`GOAL_TASK`、`CONSTRAINTS_TASK`、`BEST_TASK`、`teacher_output`、`levels_text`、`constraints_list`、`normalized`），没有复制改写。
- 行动顺序：每条 case 以固定种子 0 打乱一次，`raw/<set>.jsonl` 的 `shown` 字段记录了模型看到的顺序。
- 调用方设置（不属于评测本身）：`reasoning = {"effort": "none"}`，`max_tokens = 4000`。不这样设置、让模型按默认深度思考时，它在这个 prompt 上会先写很长的思维链、再写 6k–10k token 的正文，几乎不闭合 JSON（max_tokens 4000 下 3 条测试样例全部截断、只能靠重试拿到答案）；关掉后单次 5–9 s。实测同样 3 条：none 5–9 s，low 37–51 s，medium 第一条 52 s 仍没有可用的 JSON。
- 超时：单次尝试 120 s，一条 case 累计 300 s，最多 4 次尝试；在并发下失败过的 case 会在并发 1 下再问一遍。
- 判为不合法即重试，用的是 `label()` 自己的规则：每个行动都要判、goal 是 5 个和为 1 的概率、违反概率都在 [0, 1]、best 是分布。另外 JSON 解析失败（含被 max_tokens 截断）也算无效。best 里缺的行动按 0 计（schema 允许省略，teacher 的答案也常把非选项给 0；加 0 不改变分布）。最终仍失败的 case 记为失败、单独统计，不静默丢弃。

## 指标（对照 teacher 标签）

`score()` 只给 selection 和 decision 生成 bootstrap 区间，goal / constraints 的区间这里按同一方法补（按 test case 重采样 2000 次，见 `report.py` 的 `boot()`）。

| 数据 | 任务 | 指标 | n | LLM 零样本 |
|---|---|---|---|---|
| zh | goal | Accuracy ↑（argmax 档位） | 2250 | 0.623 [0.602, 0.645] |
| zh | goal | KL ↓ | 2250 | 0.431 |
| zh | goal | Brier ↓ | 2250 | 0.111 |
| zh | goal | MAE ↓（期望档位） | 2250 | 0.427 |
| zh | goal | 排序 ↑（gold 期望档位相差 ≥0.5 的行动对） | 2250 | 0.929 |
| zh | constraints | Accuracy ↑（0.5 为界） | 17550 | 0.906 [0.901, 0.914] |
| zh | constraints | Brier ↓ | 17550 | 0.032 |
| zh | constraints | ECE ↓ | 17550 | 0.022 |
| zh | constraints | AUROC ↑ | 17550 | 0.938 |
| zh | constraints | 硬约束违反召回 ↑（gold P ≥ 0.5） | 2774 | 0.664 [0.646, 0.681] |
| zh | selection | Accuracy ↑（argmax 行动） | 450 | 0.818 [0.780, 0.853] |
| zh | selection | KL ↓ | 450 | 0.182 |
| zh | selection | Brier ↓ | 450 | 0.073 |
| zh | selection | ECE ↓ | 450 | 0.161 |
| zh | decision | 选对 ↑（硬约束过滤后，与 gold best argmax 一致） | 450 | 0.818 [0.780, 0.853] |
| zh | decision | 选中行动按 gold 违反硬约束 ↓ | 450 | 0.103 |
| zh | decision | 全部行动被排除（弃权） | 450 | 0.007 |
| en | goal | Accuracy ↑（argmax 档位） | 951 | 0.400 [0.354, 0.421] |
| en | goal | KL ↓ | 951 | 3.469 |
| en | goal | Brier ↓ | 951 | 0.323 |
| en | goal | MAE ↓（期望档位） | 951 | 0.966 |
| en | goal | 排序 ↑（gold 期望档位相差 ≥0.5 的行动对） | 951 | 0.707 |
| en | constraints | Accuracy ↑（0.5 为界） | 6141 | 0.916 [0.907, 0.930] |
| en | constraints | Brier ↓ | 6141 | 0.038 |
| en | constraints | ECE ↓ | 6141 | 0.019 |
| en | constraints | AUROC ↑ | 6141 | 0.893 |
| en | constraints | 硬约束违反召回 ↑（gold P ≥ 0.5） | 577 | 0.655 [0.614, 0.692] |
| en | selection | Accuracy ↑（argmax 行动） | 225 | 0.676 [0.618, 0.738] |
| en | selection | KL ↓ | 225 | 0.850 |
| en | selection | Brier ↓ | 225 | 0.193 |
| en | selection | ECE ↓ | 225 | 0.082 |
| en | decision | 选对 ↑（硬约束过滤后，与 gold best argmax 一致） | 225 | 0.676 [0.618, 0.738] |
| en | decision | 选中行动按 gold 违反硬约束 ↓ | 225 | 0.094 |
| en | decision | 全部行动被排除（弃权） | 225 | 0.004 |
| en | decision | 原 typed-decisions gold 选对 ↑ | 225 | 0.538 [0.471, 0.600] |

- goal：每个行动的目标达成五档分布；constraints：每个行动 × 每条约束的违反概率；selection：best 分布的 argmax。
- decision：先排除任一硬约束违反概率 ≥ 0.5 的行动，再在剩下的行动里取 best 最大的，和 `MatrixEvaluator.assess` 的规则一致。`selection` 是没过滤时的 argmax。
- en 是 typed-decisions test split 转成的 Krino Matrix，它的原 gold 在 `meta.previous_best`，“原 gold 选对”只对 en 有定义。

## 失败与重试

每条 case 的记录在 `raw/<set>.jsonl`（同一 case 以最后一行为准）：`attempts` 是尝试次数，`error` 表示最终没有可用答案。

| 数据 | case 数 | 一次成功 | 重试后成功 | 最终失败 | 没有产出可用答案的尝试 |
|---|---|---|---|---|---|
| zh | 450 | 253 | 196 | 1 | 196 |
| en | 225 | 187 | 37 | 1 | 37 |

zh 最终失败的 case（逐条）：

- `value_opus-train-00735`：1 次尝试，BadAnswer: join_southeast_asia_island_tour: goal is not 5 probabilities summing to 1: [0.0, 0.0, 0.0, 0.0, 0.0]

en 最终失败的 case（逐条）：

- `tr_invoice_processing_000056`：1 次尝试，BadAnswer: reject: goal is not 5 probabilities summing to 1: [0.0, 0.0, 0.0, 0.0, 0.0]

失败原因：BadAnswer 2。

## 延迟、token 与成本

单次延迟来自并发 1 的探测（每个数据前 50 条），不受队列等待影响，也正是结果 JSON 里 `latency_ms` 的来源。token 和价格为每个数据 100 条、并发 16 的探测，取每次调用的实际用量。

| 数据 | 单次延迟 p50 | p95 | 平均输入 token | 平均输出 token | 单次调用成本 | 每千次决策成本 | 部署并发 16 下 p50（参考） |
|---|---|---|---|---|---|---|---|
| zh | 8549 ms | 13251 ms | 1137 | 1371 | $0.00074 | $0.7351 | 11936 ms |
| en | 2971 ms | 5854 ms | 1205 | 1155 | $0.00065 | $0.6537 | 5733 ms |

价格取 OpenRouter `deepseek/deepseek-v4.1-flash` 当前价：$0.1400 / 百万输入 token，$0.4200 / 百万输出 token（`https://openrouter.ai/api/v1/models`，写报告时读取）。按实际用量（含重试）算，不按缓存价。

审计记录里的 HTTP 调用共 200 次（成本探测），加上正式跑的汇总 zh 451 次, en 225 次：468,266 输入 + 505,210 输出 = 973,476 token，按上面价格合计 $0.278；结束原因 stop 193，length 7（`length` 是 max_tokens 截断，`stop` 是正常结束）。正式跑的逐调用记录在两次正式跑时被覆盖（那是拆分审计文件之前），只留下 `results/audit.jsonl` 里的 `aggregate` 汇总行；成本探测的逐调用记录在 `results/audit-cost.jsonl`。

## 与小模型对照时要注意

- 同一模型：标签和基线都出自 `deepseek/deepseek-v4.1-flash-1017`，差别只在 temperature 0 与一次采样。
- 延迟是端到端的一次 HTTP 调用（含输出 token 生成），MatrixEvaluator 是一次前向。
- 成本包含重试：一个不合法答案会让这条 case 再多花一次调用的钱。
- 正式跑用并发 16；并发下延迟见上表最后一列，部署吞吐取决于能并发多少请求。
