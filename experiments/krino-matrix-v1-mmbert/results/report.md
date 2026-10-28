# Krino Matrix benchmark

- 设备：NVIDIA GeForce RTX 4060 Laptop GPU；torch 2.6.0+cu124；每个 case 一次前向，同时输出三个任务

## decision（硬约束过滤后的最终选择）

| 模型 | 数据 | n | 选对 ↑ | 选中违反硬约束 ↓ | 全部排除  | 原 gold 选对 ↑ |
|---|---|---|---|---|---|---|
| prior | en | 225 | 0.191 [0.142, 0.244] | 0.542 | 0.000 | 0.244 [0.191, 0.298] |
| prior | zh | 450 | 0.247 [0.209, 0.287] | 0.515 | 0.000 | – |
| mmbert-uncertainty-s2 | en | 225 | 0.609 [0.547, 0.671] | 0.058 | 0.000 | 0.471 [0.409, 0.538] |
| mmbert-uncertainty-s2 | zh | 450 | 0.753 [0.713, 0.793] | 0.123 | 0.002 | – |
| mmbert-fixed-s2 | en | 225 | 0.609 [0.542, 0.671] | 0.062 | 0.000 | 0.516 [0.453, 0.582] |
| mmbert-fixed-s2 | zh | 450 | 0.751 [0.711, 0.791] | 0.125 | 0.000 | – |
| mmbert-selection-only-s2 | en | 225 | 0.618 [0.556, 0.680] | 0.053 | 0.000 | 0.489 [0.427, 0.556] |
| mmbert-selection-only-s2 | zh | 450 | 0.762 [0.722, 0.804] | 0.130 | 0.000 | – |
| mmbert-fixed-s1 | en | 225 | 0.631 [0.569, 0.693] | 0.049 | 0.004 | 0.484 [0.422, 0.551] |
| mmbert-fixed-s1 | zh | 450 | 0.753 [0.713, 0.796] | 0.126 | 0.002 | – |
| mmbert-fixed | en | 225 | 0.631 [0.569, 0.693] | 0.044 | 0.000 | 0.484 [0.418, 0.551] |
| mmbert-fixed | zh | 450 | 0.760 [0.722, 0.800] | 0.114 | 0.002 | – |
| mmbert-selection-only-s1 | en | 225 | 0.640 [0.582, 0.702] | 0.058 | 0.000 | 0.493 [0.427, 0.560] |
| mmbert-selection-only-s1 | zh | 450 | 0.753 [0.713, 0.793] | 0.128 | 0.000 | – |
| mmbert-selection-only | en | 225 | 0.622 [0.560, 0.684] | 0.049 | 0.000 | 0.476 [0.409, 0.542] |
| mmbert-selection-only | zh | 450 | 0.800 [0.762, 0.836] | 0.119 | 0.000 | – |
| mmbert-uncertainty-s1 | en | 225 | 0.631 [0.569, 0.693] | 0.058 | 0.000 | 0.507 [0.444, 0.573] |
| mmbert-uncertainty-s1 | zh | 450 | 0.773 [0.736, 0.811] | 0.123 | 0.002 | – |
| mmbert-uncertainty | en | 225 | 0.627 [0.564, 0.689] | 0.058 | 0.000 | 0.484 [0.418, 0.551] |
| mmbert-uncertainty | zh | 450 | 0.787 [0.749, 0.824] | 0.121 | 0.002 | – |

## goal（目标达成五档）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | MAE ↓ | 排序 ↑ |
|---|---|---|---|---|---|---|---|
| prior | en | 951 | 0.369 | 0.607 | 0.258 | 0.986 | 0.459 |
| prior | zh | 2250 | 0.288 | 0.541 | 0.216 | 0.889 | 0.450 |
| mmbert-uncertainty-s2 | en | 951 | 0.574 | 0.358 | 0.141 | 0.659 | 0.848 |
| mmbert-uncertainty-s2 | zh | 2250 | 0.552 | 0.270 | 0.116 | 0.490 | 0.902 |
| mmbert-fixed-s2 | en | 951 | 0.593 | 0.347 | 0.136 | 0.642 | 0.855 |
| mmbert-fixed-s2 | zh | 2250 | 0.546 | 0.263 | 0.113 | 0.478 | 0.897 |
| mmbert-fixed-s1 | en | 951 | 0.580 | 0.343 | 0.134 | 0.636 | 0.857 |
| mmbert-fixed-s1 | zh | 2250 | 0.540 | 0.267 | 0.115 | 0.484 | 0.897 |
| mmbert-fixed | en | 951 | 0.569 | 0.350 | 0.137 | 0.641 | 0.854 |
| mmbert-fixed | zh | 2250 | 0.555 | 0.265 | 0.114 | 0.481 | 0.896 |
| mmbert-uncertainty-s1 | en | 951 | 0.573 | 0.351 | 0.137 | 0.648 | 0.856 |
| mmbert-uncertainty-s1 | zh | 2250 | 0.543 | 0.269 | 0.115 | 0.490 | 0.894 |
| mmbert-uncertainty | en | 951 | 0.569 | 0.345 | 0.134 | 0.640 | 0.857 |
| mmbert-uncertainty | zh | 2250 | 0.544 | 0.268 | 0.116 | 0.490 | 0.897 |

## constraints（约束违反）

| 模型 | 数据 | n | Accuracy ↑ | Brier ↓ | ECE ↓ | AUROC ↑ | 硬约束违反召回 ↑ |
|---|---|---|---|---|---|---|---|
| prior | en | 6141 | 0.848 | 0.081 | 0.036 | 0.000 | 0.000 |
| prior | zh | 17550 | 0.781 | 0.106 | 0.021 | 0.000 | 0.000 |
| mmbert-uncertainty-s2 | en | 6141 | 0.902 | 0.035 | 0.049 | 0.930 | 0.499 |
| mmbert-uncertainty-s2 | zh | 17550 | 0.834 | 0.062 | 0.048 | 0.858 | 0.430 |
| mmbert-fixed-s2 | en | 6141 | 0.896 | 0.037 | 0.040 | 0.925 | 0.444 |
| mmbert-fixed-s2 | zh | 17550 | 0.832 | 0.064 | 0.047 | 0.854 | 0.414 |
| mmbert-fixed-s1 | en | 6141 | 0.901 | 0.036 | 0.047 | 0.929 | 0.511 |
| mmbert-fixed-s1 | zh | 17550 | 0.830 | 0.064 | 0.044 | 0.852 | 0.439 |
| mmbert-fixed | en | 6141 | 0.896 | 0.038 | 0.034 | 0.924 | 0.408 |
| mmbert-fixed | zh | 17550 | 0.825 | 0.066 | 0.038 | 0.848 | 0.373 |
| mmbert-uncertainty-s1 | en | 6141 | 0.900 | 0.037 | 0.044 | 0.924 | 0.475 |
| mmbert-uncertainty-s1 | zh | 17550 | 0.828 | 0.064 | 0.040 | 0.853 | 0.435 |
| mmbert-uncertainty | en | 6141 | 0.903 | 0.035 | 0.042 | 0.933 | 0.494 |
| mmbert-uncertainty | zh | 17550 | 0.832 | 0.062 | 0.040 | 0.857 | 0.454 |

## selection（选择头，未过滤）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ |
|---|---|---|---|---|---|---|
| prior | en | 225 | 0.378 [0.316, 0.444] | 0.697 | 0.355 | 0.139 |
| prior | zh | 450 | 0.247 [0.209, 0.287] | 0.855 | 0.400 | 0.047 |
| mmbert-uncertainty-s2 | en | 225 | 0.609 [0.547, 0.671] | 0.379 | 0.186 | 0.135 |
| mmbert-uncertainty-s2 | zh | 450 | 0.753 [0.713, 0.793] | 0.220 | 0.110 | 0.125 |
| mmbert-fixed-s2 | en | 225 | 0.609 [0.542, 0.671] | 0.367 | 0.181 | 0.152 |
| mmbert-fixed-s2 | zh | 450 | 0.753 [0.713, 0.793] | 0.216 | 0.108 | 0.140 |
| mmbert-selection-only-s2 | en | 225 | 0.618 [0.556, 0.680] | 0.373 | 0.182 | 0.138 |
| mmbert-selection-only-s2 | zh | 450 | 0.762 [0.722, 0.804] | 0.222 | 0.112 | 0.126 |
| mmbert-fixed-s1 | en | 225 | 0.631 [0.569, 0.693] | 0.357 | 0.175 | 0.117 |
| mmbert-fixed-s1 | zh | 450 | 0.756 [0.716, 0.796] | 0.221 | 0.111 | 0.134 |
| mmbert-fixed | en | 225 | 0.631 [0.569, 0.693] | 0.370 | 0.182 | 0.099 |
| mmbert-fixed | zh | 450 | 0.760 [0.722, 0.800] | 0.211 | 0.107 | 0.165 |
| mmbert-selection-only-s1 | en | 225 | 0.640 [0.582, 0.702] | 0.352 | 0.171 | 0.121 |
| mmbert-selection-only-s1 | zh | 450 | 0.753 [0.713, 0.793] | 0.225 | 0.112 | 0.143 |
| mmbert-selection-only | en | 225 | 0.622 [0.560, 0.684] | 0.392 | 0.190 | 0.079 |
| mmbert-selection-only | zh | 450 | 0.800 [0.762, 0.836] | 0.221 | 0.108 | 0.191 |
| mmbert-uncertainty-s1 | en | 225 | 0.631 [0.569, 0.693] | 0.357 | 0.176 | 0.132 |
| mmbert-uncertainty-s1 | zh | 450 | 0.773 [0.736, 0.811] | 0.216 | 0.108 | 0.143 |
| mmbert-uncertainty | en | 225 | 0.627 [0.564, 0.689] | 0.355 | 0.174 | 0.140 |
| mmbert-uncertainty | zh | 450 | 0.787 [0.749, 0.824] | 0.215 | 0.108 | 0.161 |

## 决策准确率的配对差异（减去 mmbert-uncertainty，95% bootstrap 区间）

| 模型 | 数据 | 选对 | 原 gold 选对 |
|---|---|---|---|
| mmbert-uncertainty-s2 | en | -0.018 [-0.049, +0.013] | -0.013 [-0.049, +0.018] |
| mmbert-uncertainty-s2 | zh | -0.033 [-0.064, -0.004] * | – |
| mmbert-fixed-s2 | en | -0.018 [-0.058, +0.022] | +0.031 [-0.004, +0.071] |
| mmbert-fixed-s2 | zh | -0.036 [-0.064, -0.004] * | – |
| mmbert-selection-only-s2 | en | -0.009 [-0.031, +0.013] | +0.004 [-0.022, +0.031] |
| mmbert-selection-only-s2 | zh | -0.024 [-0.051, +0.004] | – |
| mmbert-fixed-s1 | en | +0.004 [-0.013, +0.022] | +0.000 [-0.027, +0.027] |
| mmbert-fixed-s1 | zh | -0.033 [-0.062, -0.004] * | – |
| mmbert-fixed | en | +0.004 [-0.013, +0.022] | +0.000 [-0.022, +0.022] |
| mmbert-fixed | zh | -0.027 [-0.056, +0.004] | – |
| mmbert-selection-only-s1 | en | +0.013 [-0.009, +0.036] | +0.009 [-0.018, +0.036] |
| mmbert-selection-only-s1 | zh | -0.033 [-0.062, -0.004] * | – |
| mmbert-selection-only | en | -0.004 [-0.027, +0.013] | -0.009 [-0.031, +0.013] |
| mmbert-selection-only | zh | +0.013 [-0.016, +0.042] | – |
| mmbert-uncertainty-s1 | en | +0.004 [-0.027, +0.036] | +0.022 [-0.009, +0.053] |
| mmbert-uncertainty-s1 | zh | -0.013 [-0.042, +0.013] | – |

\* 区间不含 0。

## 多种子汇总（均值 ± 标准差）

| 模型 | 种子数 | 数据 | 决策选对 | 原 gold 选对 | 选择头 | goal | 约束 AUROC |
|---|---|---|---|---|---|---|---|
| mmbert-uncertainty | 3 | en | 0.622 ± 0.012 | 0.487 ± 0.018 | 0.622 ± 0.012 | 0.572 ± 0.003 | 0.929 ± 0.005 |
| mmbert-uncertainty | 3 | zh | 0.771 ± 0.017 | – | 0.771 ± 0.017 | 0.546 ± 0.005 | 0.856 ± 0.003 |
| mmbert-fixed | 3 | en | 0.624 ± 0.013 | 0.495 ± 0.018 | 0.624 ± 0.013 | 0.581 ± 0.012 | 0.926 ± 0.002 |
| mmbert-fixed | 3 | zh | 0.755 ± 0.005 | – | 0.756 ± 0.003 | 0.547 ± 0.007 | 0.851 ± 0.003 |
| mmbert-selection-only | 3 | en | 0.627 ± 0.012 | 0.486 ± 0.009 | 0.627 ± 0.012 | – | – |
| mmbert-selection-only | 3 | zh | 0.772 ± 0.025 | – | 0.772 ± 0.025 | – | – |

## 延迟（每个 case，p50）

| 模型 | en | zh |
|---|---|---|
| prior | – | – |
| mmbert-uncertainty-s2 | 41 ms | 39 ms |
| mmbert-fixed-s2 | 41 ms | 41 ms |
| mmbert-selection-only-s2 | 40 ms | 38 ms |
| mmbert-fixed-s1 | 41 ms | 39 ms |
| mmbert-fixed | 39 ms | 38 ms |
| mmbert-selection-only-s1 | 40 ms | 38 ms |
| mmbert-selection-only | 36 ms | 41 ms |
| mmbert-uncertainty-s1 | 38 ms | 38 ms |
| mmbert-uncertainty | 34 ms | 34 ms |

说明：
- decision：先排除任一硬约束违反概率 ≥0.5 的行动，再在剩下的行动里按选择头取最优；选对 = 与 gold best 的 argmax 一致。
- goal 的排序：同一 case 内 gold 期望档位相差 ≥0.5 的行动对，模型排对的比例。
- constraints 以 0.5 为界；硬约束违反召回 = gold 判为违反的硬约束里，模型也判为违反的比例。
- prior：不看输入，输出训练集的平均标签，选择均匀分布、决策固定选第一个行动，作为下限参照。
- laya-*：原版 Laya 检查点，没有在 Krino Matrix 上训练；整个行动空间作为一道 choice 题，目标和约束放进 state。它没有 goal / constraint 头，也不做硬约束过滤，只评 selection 和 decision。
- *-selection-only：同一基座、同样数据，只训选择头的消融；没有 goal / constraint 头，也不做硬约束过滤。
- 方括号是 95% bootstrap 区间（按 test case 重采样）；*-s1、*-s2 是同一配置的其他种子。
- en 是 typed-decisions test split 转成的 Krino Matrix；goal、constraints、best 三个标签由同一个 teacher 打。原 gold 选对 = 与 typed-decisions 原有 action/disposition gold 的 argmax 一致（仅 en 有）。
