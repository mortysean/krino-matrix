# Krino Matrix benchmark

- 设备：NVIDIA GeForce RTX 4060 Laptop GPU；torch 2.6.0+cu124；每个 case 一次前向，同时输出三个任务

## decision（硬约束过滤后的最终选择）

| 模型 | 数据 | n | 选对 ↑ | 选中违反硬约束 ↓ | 全部排除  | 原 gold 选对 ↑ |
|---|---|---|---|---|---|---|
| prior | en | 225 | 0.191 [0.142, 0.244] | 0.542 | 0.000 | 0.244 [0.191, 0.298] |
| prior | zh | 450 | 0.247 [0.209, 0.287] | 0.515 | 0.000 | – |
| multilingual-selection-only | en | 225 | 0.627 [0.564, 0.689] | 0.049 | 0.000 | 0.471 [0.404, 0.538] |
| multilingual-selection-only | zh | 450 | 0.760 [0.720, 0.800] | 0.123 | 0.000 | – |
| laya-typed-decisions-base | en | 225 | 0.556 [0.493, 0.622] | 0.124 | 0.000 | 0.600 [0.538, 0.667] |
| laya-typed-decisions-base | zh | 450 | 0.278 [0.238, 0.318] | 0.474 | 0.000 | – |
| multilingual-fixed | en | 225 | 0.649 [0.587, 0.711] | 0.049 | 0.000 | 0.480 [0.413, 0.547] |
| multilingual-fixed | zh | 450 | 0.738 [0.698, 0.778] | 0.143 | 0.000 | – |
| multilingual-uncertainty | en | 225 | 0.640 [0.578, 0.702] | 0.067 | 0.004 | 0.476 [0.413, 0.542] |
| multilingual-uncertainty | zh | 450 | 0.756 [0.718, 0.796] | 0.128 | 0.000 | – |

## goal（目标达成五档）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | MAE ↓ | 排序 ↑ |
|---|---|---|---|---|---|---|---|
| prior | en | 951 | 0.369 | 0.607 | 0.258 | 0.986 | 0.459 |
| prior | zh | 2250 | 0.288 | 0.541 | 0.216 | 0.889 | 0.450 |
| multilingual-fixed | en | 951 | 0.482 | 0.396 | 0.154 | 0.621 | 0.865 |
| multilingual-fixed | zh | 2250 | 0.510 | 0.314 | 0.132 | 0.533 | 0.878 |
| multilingual-uncertainty | en | 951 | 0.474 | 0.406 | 0.158 | 0.633 | 0.848 |
| multilingual-uncertainty | zh | 2250 | 0.483 | 0.325 | 0.138 | 0.550 | 0.868 |

## constraints（约束违反）

| 模型 | 数据 | n | Accuracy ↑ | Brier ↓ | ECE ↓ | AUROC ↑ | 硬约束违反召回 ↑ |
|---|---|---|---|---|---|---|---|
| prior | en | 6141 | 0.848 | 0.081 | 0.036 | 0.000 | 0.000 |
| prior | zh | 17550 | 0.781 | 0.106 | 0.021 | 0.000 | 0.000 |
| multilingual-fixed | en | 6141 | 0.872 | 0.054 | 0.040 | 0.859 | 0.204 |
| multilingual-fixed | zh | 17550 | 0.786 | 0.087 | 0.030 | 0.761 | 0.066 |
| multilingual-uncertainty | en | 6141 | 0.879 | 0.050 | 0.041 | 0.870 | 0.278 |
| multilingual-uncertainty | zh | 17550 | 0.791 | 0.084 | 0.029 | 0.777 | 0.105 |

## selection（选择头，未过滤）

| 模型 | 数据 | n | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ |
|---|---|---|---|---|---|---|
| prior | en | 225 | 0.378 [0.316, 0.444] | 0.697 | 0.355 | 0.139 |
| prior | zh | 450 | 0.247 [0.209, 0.287] | 0.855 | 0.400 | 0.047 |
| multilingual-selection-only | en | 225 | 0.627 [0.564, 0.689] | 0.366 | 0.179 | 0.103 |
| multilingual-selection-only | zh | 450 | 0.760 [0.720, 0.800] | 0.247 | 0.120 | 0.166 |
| laya-typed-decisions-base | en | 225 | 0.556 [0.493, 0.622] | 0.488 | 0.251 | 0.162 |
| laya-typed-decisions-base | zh | 450 | 0.278 [0.238, 0.318] | 0.827 | 0.390 | 0.029 |
| multilingual-fixed | en | 225 | 0.649 [0.587, 0.711] | 0.382 | 0.186 | 0.063 |
| multilingual-fixed | zh | 450 | 0.738 [0.698, 0.778] | 0.272 | 0.132 | 0.162 |
| multilingual-uncertainty | en | 225 | 0.640 [0.578, 0.702] | 0.374 | 0.181 | 0.083 |
| multilingual-uncertainty | zh | 450 | 0.756 [0.718, 0.796] | 0.259 | 0.127 | 0.178 |

## 决策准确率的配对差异（减去 multilingual-uncertainty，95% bootstrap 区间）

| 模型 | 数据 | 选对 | 原 gold 选对 |
|---|---|---|---|
| multilingual-selection-only | en | -0.013 [-0.053, +0.027] | -0.004 [-0.036, +0.031] |
| multilingual-selection-only | zh | +0.004 [-0.024, +0.033] | – |
| laya-typed-decisions-base | en | -0.084 [-0.151, -0.018] * | +0.124 [+0.058, +0.191] * |
| laya-typed-decisions-base | zh | -0.478 [-0.533, -0.424] * | – |
| multilingual-fixed | en | +0.009 [-0.018, +0.036] | +0.004 [-0.027, +0.036] |
| multilingual-fixed | zh | -0.018 [-0.042, +0.007] | – |

\* 区间不含 0。

## 延迟（每个 case，p50）

| 模型 | en | zh |
|---|---|---|
| prior | – | – |
| multilingual-selection-only | 41 ms | 44 ms |
| laya-typed-decisions-base | 49 ms | 65 ms |
| multilingual-fixed | 42 ms | 36 ms |
| multilingual-uncertainty | 36 ms | 40 ms |

说明：
- decision：先排除任一硬约束违反概率 ≥0.5 的行动，再在剩下的行动里按选择头取最优；选对 = 与 gold best 的 argmax 一致。
- goal 的排序：同一 case 内 gold 期望档位相差 ≥0.5 的行动对，模型排对的比例。
- constraints 以 0.5 为界；硬约束违反召回 = gold 判为违反的硬约束里，模型也判为违反的比例。
- prior：不看输入，输出训练集的平均标签，选择均匀分布、决策固定选第一个行动，作为下限参照。
- laya-*：原版 Laya 检查点，没有在 Krino Matrix 上训练；整个行动空间作为一道 choice 题，目标和约束放进 state。它没有 goal / constraint 头，也不做硬约束过滤，只评 selection 和 decision。
- *-selection-only：同一基座、同样数据，只训选择头的消融；没有 goal / constraint 头，也不做硬约束过滤。
- 方括号是 95% bootstrap 区间（按 test case 重采样）；*-s1、*-s2 是同一配置的其他种子。
- en 是 typed-decisions test split 转成的 Krino Matrix；goal、constraints、best 三个标签由同一个 teacher 打。原 gold 选对 = 与 typed-decisions 原有 action/disposition gold 的 argmax 一致（仅 en 有）。
