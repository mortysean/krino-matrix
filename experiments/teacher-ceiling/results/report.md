# Teacher 自一致上限（teacher ceiling）

用生成原标签的同一套流程重新标注 test 集，与原标签对照。teacher `deepseek/deepseek-v4.1-flash-1017`，OpenRouter，温度 0.7，每 case 3 次独立采样，每次重新打乱动作顺序，同一 prompt 与输出 schema、同样的校验与最多 4 次尝试的重试，取平均。

## 结论

| 数据 | n | teacher-relabel 决策选对 | 选中违反硬约束 | 单次采样均值 | goal acc | 约束 AUROC | selection acc |
|---|---|---|---|---|---|---|---|
| zh | 450 | 0.840 [0.807, 0.871] | 0.012 | 0.820 ± 0.002 | 0.790 | 0.992 | 0.902 [0.873, 0.927] |
| en | 225 | 0.796 [0.742, 0.849] | 0.040 | 0.770 ± 0.024 | 0.718 | 0.976 | 0.791 [0.738, 0.844] |

- **zh**：teacher-relabel 决策选对 **0.840**（95% CI 0.807–0.871），单次采样 0.820 ± 0.002。
- **en**：teacher-relabel 决策选对 **0.796**（95% CI 0.742–0.849），单次采样 0.770 ± 0.024；与原 typed-decisions gold 的一致度 0.551。
- 这就是学生模型在这种标签上能对齐到的上限：即使学生输出与 teacher-relabel 完全相同，与原标签的决策一致率也只有上面的数字，其余部分是 teacher 自身的采样随机性造成的标签噪声，学生无从学习。

## 采样

| 数据 | case 数 | 有效运行 | 重试 | 首次尝试即成功 | 重跑补齐的运行 | 不完整 case | 无有效运行 case | 单次调用 p50 / p95 |
|---|---|---|---|---|---|---|---|---|
| zh | 450 | 1350 | 323 | 1027 | 1 | 0 | 0 | 82037 / 215229 ms |
| en | 225 | 675 | 120 | 555 | 2 | 0 | 0 | 69488 / 166716 ms |

`raw/` 里的采样记录合计 **2468 次调用**：zh 1673 次，en 795 次；其中 443 次是同一次运行内的重试（第 2–4 次尝试），2022 个运行首次尝试即成功，3 个运行是**重跑补齐**的（之前那次运行 4 次尝试全部失败，同一命令重跑同一运行编号后成功，只留下 `raw/` 里的成功记录，失败记录见 `logs/full.log` 的 `gave up after 4 attempts`）；每个失败的运行额外用掉 4 次调用，真实调用总数约为 2468 + 4×3 = 2480。`raw/` 覆盖 675/675 个 case，每个 case 3 次有效采样。

| 数据 | served_model（全部有效运行） |
|---|---|
| zh | `deepseek/deepseek-v4.1-flash-1017` × 1350 |
| en | `deepseek/deepseek-v4.1-flash-1017` × 675 |

重试沿用 `examples/krino_matrix_data.py` 的 `retry()`：最多 4 次尝试（含首次），退避 1s、2s、4s。原始每次运行一条记录，写在 `raw/{zh,en}.jsonl`，包括 `action_order`（该次展示的动作顺序）、`served_model`、完整输出、`latency_ms`（含重试的总耗时）、`attempts` 和 `error`。

## 决策（硬约束过滤后的最终选择）

| 模型 | 数据 | n | 选对 ↑ | 选中违反硬约束 ↓ | 全部排除 | 原 gold 选对 ↑ |
|---|---|---|---|---|---|---|
| teacher-relabel | zh | 450 | 0.840 [0.807, 0.871] | 0.012 | 0.067 | – |
| teacher-relabel | en | 225 | 0.796 [0.742, 0.849] | 0.040 | 0.004 | 0.551 [0.489, 0.618] |
| teacher-single-s1 | zh | 450 | 0.822 [0.787, 0.858] | 0.029 | 0.064 | – |
| teacher-single-s1 | en | 225 | 0.787 [0.733, 0.840] | 0.045 | 0.004 | 0.564 [0.498, 0.631] |
| teacher-single-s2 | zh | 450 | 0.820 [0.784, 0.853] | 0.017 | 0.071 | – |
| teacher-single-s2 | en | 225 | 0.742 [0.684, 0.796] | 0.041 | 0.018 | 0.547 [0.480, 0.609] |
| teacher-single-s3 | zh | 450 | 0.818 [0.780, 0.851] | 0.024 | 0.067 | – |
| teacher-single-s3 | en | 225 | 0.782 [0.729, 0.836] | 0.032 | 0.013 | 0.524 [0.462, 0.591] |

## goal（目标达成五档）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | MAE ↓ | 排序 ↑ |
|---|---|---|---|---|---|---|---|
| teacher-relabel | zh | 2250 | 0.790 | 0.113 | 0.032 | 0.194 | 0.990 |
| teacher-relabel | en | 951 | 0.718 | 0.945 | 0.088 | 0.388 | 0.948 |
| teacher-single-s1 | zh | 2250 | 0.721 | 0.354 | 0.059 | 0.265 | 0.977 |
| teacher-single-s1 | en | 951 | 0.668 | 1.676 | 0.129 | 0.455 | 0.934 |
| teacher-single-s2 | zh | 2250 | 0.732 | 0.356 | 0.059 | 0.262 | 0.980 |
| teacher-single-s2 | en | 951 | 0.654 | 1.633 | 0.140 | 0.468 | 0.930 |
| teacher-single-s3 | zh | 2250 | 0.739 | 0.355 | 0.057 | 0.260 | 0.978 |
| teacher-single-s3 | en | 951 | 0.647 | 1.675 | 0.133 | 0.466 | 0.937 |

## constraints（约束违反）

| 模型 | 数据 | n | Accuracy ↑ | Brier ↓ | ECE ↓ | AUROC ↑ | 硬约束违反召回 ↑ |
|---|---|---|---|---|---|---|---|
| teacher-relabel | zh | 17550 | 0.966 | 0.006 | 0.080 | 0.992 | 0.920 |
| teacher-relabel | en | 6141 | 0.958 | 0.015 | 0.029 | 0.976 | 0.881 |
| teacher-single-s1 | zh | 17550 | 0.952 | 0.011 | 0.059 | 0.980 | 0.910 |
| teacher-single-s1 | en | 6141 | 0.945 | 0.022 | 0.019 | 0.962 | 0.884 |
| teacher-single-s2 | zh | 17550 | 0.952 | 0.011 | 0.058 | 0.978 | 0.906 |
| teacher-single-s2 | en | 6141 | 0.947 | 0.021 | 0.013 | 0.965 | 0.860 |
| teacher-single-s3 | zh | 17550 | 0.952 | 0.011 | 0.060 | 0.981 | 0.915 |
| teacher-single-s3 | en | 6141 | 0.944 | 0.022 | 0.010 | 0.966 | 0.867 |

## selection（选择头，未过滤）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ |
|---|---|---|---|---|---|---|
| teacher-relabel | zh | 450 | 0.902 [0.873, 0.927] | 0.060 | 0.027 | 0.184 |
| teacher-relabel | en | 225 | 0.791 [0.738, 0.844] | 0.448 | 0.128 | 0.072 |
| teacher-single-s1 | zh | 450 | 0.882 [0.851, 0.909] | 0.144 | 0.048 | 0.146 |
| teacher-single-s1 | en | 225 | 0.791 [0.742, 0.840] | 0.790 | 0.159 | 0.050 |
| teacher-single-s2 | zh | 450 | 0.889 [0.860, 0.918] | 0.160 | 0.043 | 0.148 |
| teacher-single-s2 | en | 225 | 0.751 [0.693, 0.809] | 0.861 | 0.205 | 0.090 |
| teacher-single-s3 | zh | 450 | 0.880 [0.847, 0.911] | 0.154 | 0.047 | 0.136 |
| teacher-single-s3 | en | 225 | 0.787 [0.733, 0.840] | 0.861 | 0.173 | 0.068 |

## 单次采样（s1/s2/s3）：均值 ± 标准差

| 数据 | 决策选对 | 选中违反硬约束 | goal accuracy | 约束 AUROC | selection accuracy | 原 gold 选对 |
|---|---|---|---|---|---|---|
| zh | 0.820 ± 0.002 | 0.023 ± 0.006 | 0.731 ± 0.009 | 0.980 ± 0.001 | 0.884 ± 0.005 | – |
| en | 0.770 ± 0.024 | 0.039 ± 0.007 | 0.656 ± 0.011 | 0.964 ± 0.002 | 0.776 ± 0.022 | 0.545 ± 0.020 |

每次采样单独打分：没有平均，单次的 goal/best 不经归一化直接使用（Assessment 用概率），所以单次与平均的差距既包含采样随机性，也包含平均带来的平滑收益。

## teacher-single 与 teacher-relabel 并排

| 数据 | 指标 | single 均值 | relabel |
|---|---|---|---|
| zh | 决策选对 | 0.820 | 0.840 |
| zh | 选中违反硬约束 | 0.023 | 0.012 |
| zh | goal accuracy | 0.731 | 0.790 |
| zh | 约束 AUROC | 0.980 | 0.992 |
| zh | selection accuracy | 0.884 | 0.902 |
| en | 决策选对 | 0.770 | 0.796 |
| en | 选中违反硬约束 | 0.039 | 0.040 |
| en | goal accuracy | 0.656 | 0.718 |
| en | 约束 AUROC | 0.964 | 0.976 |
| en | selection accuracy | 0.776 | 0.791 |

## 纯噪声指标（3 次新采样两两之间，与旧标签无关）

| 数据 | case 数 | 对数/case | best argmax 一致率 | goal 期望档位平均绝对差 | 档位一致率 | 比较的行动次数 |
|---|---|---|---|---|---|---|
| zh | 450 | 3 | 0.887 | 0.298 | 0.726 | 6750 |
| en | 225 | 3 | 0.804 | 0.380 | 0.723 | 2853 |

goal 期望档位 = Σ i·P(level i)，0–4；平均绝对差是同一行动两次采样的期望档位之差的绝对值平均。档位一致率 = 同一行动两次采样的期望档位取整（floor，即落在哪一档）相同的比例。best argmax 一致率低说明 teacher 在同一 case 上会把不同行动选为最优；这是任何学生模型都无法从单份标签学到的部分。

## 延迟

| 模型 | 数据 | 每个 case 的 Assessment 构造+打分（ms，benchmark 口径） | 单次 teacher 调用 p50 / p95（ms） |
|---|---|---|---|
| teacher-relabel | zh | 0.10 | 82037 / 215229 |
| teacher-relabel | en | 0.08 | 69488 / 166716 |
| teacher-single-s1 | zh | 0.03 | 82037 / 215229 |
| teacher-single-s1 | en | 0.02 | 69488 / 166716 |
| teacher-single-s2 | zh | 0.03 | 82037 / 215229 |
| teacher-single-s2 | en | 0.02 | 69488 / 166716 |
| teacher-single-s3 | zh | 0.03 | 82037 / 215229 |
| teacher-single-s3 | en | 0.03 | 69488 / 166716 |

teacher 调用延迟是该集全部采样的 p50/p95（含重试与退避的总耗时）；老师单次输出 3–12k tokens，并由网关流式返回，所以单次调用在 1–4 分钟量级。

## 未完成的 case

无：每个 case 都有 3 次有效采样。

## 口径

- teacher-relabel：3 次新采样完全按 `label()` 的方式合并——goal 每次先归一化再取均值，constraints 取均值，best 每次先归一化再取均值，四舍五入到 4 位；然后与原 test 标签比较。
- teacher-single-sN：第 N 次采样单独作为概率，不平均。
- Assessment：labels.goal / constraints / best 为上述概率；excluded = 任一硬约束违反概率 ≥ 0.5 的行动（阈值 0.5，同 `MatrixEvaluator.assess`）；choice = 未被排除的行动中 best 最大者，全部被排除时为 null。
- 所有指标由 `benchmark/run_krino_matrix.py` 的 `score()` 计算（未改动），准确率的方括号为 95% bootstrap 区间。
- en 的 `original_gold_accuracy`：与 typed-decisions 原有 action/disposition gold（`meta.previous_best`）的 argmax 一致率。它与 teacher 标签的一致度是原 gold 与 teacher 的水平，不是本实验新采样引入的差异。
- `results/<模型>.json` 的结构与 `benchmark/run_krino_matrix.py` 写出的完全相同（`model` / `sets` / `environment`），额外附带 `teacher_latency_ms`、`unscored_cases` 两个字段；把它们复制到 `experiments/krino-matrix-v1/results/` 后，主实验的 benchmark 报告会把它们列为额外的模型。
