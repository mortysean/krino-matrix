# Krino Matrix v1

在新的 Krino Matrix 格式（`core/matrix.py`，`krino-matrix/1`）上，比较三头模型、只训选择头的消融和原版 Laya 的决策能力。

## 问题

1. **三任务拆分有没有用**：同一基座、同样数据，三头模型（goal + constraints + selection，先硬约束过滤再选择）和只训选择头的模型相比，决策是否更好、违反硬约束是否更少。
2. **loss 加权方式**：uncertainty 加权（Kendall et al., 2018）和固定权重相比如何。
3. **相对原版 Laya**：在 typed-decisions 上微调过、没见过 Krino Matrix 格式的原版检查点，作为零样本参照。

## 模型

| 名称 | 基座 | 训练的头 | loss 加权 | 种子 |
|---|---|---|---|---|
| `multilingual-uncertainty` | laya-multilingual（mmBERT-base） | goal, constraints, selection | uncertainty | 0, 1, 2 |
| `multilingual-fixed` | 同上 | goal, constraints, selection | 固定（1 / 1 / 0.5） | 0, 1, 2 |
| `multilingual-selection-only` | 同上 | selection（消融） | — | 0, 1, 2 |
| `laya-typed-decisions-base` | laya-typed-decisions（ModernBERT-large） | 不训练，零样本 | — | — |

种子 0 的目录不带后缀，种子 1、2 是 `<名称>-s1`、`<名称>-s2`。所有训练的模型超参数相同：全部层参与训练，`max_length 2048`，`micro_batch 2 × grad_accum 16`，4 个 epoch，在 val 上选 epoch 并拟合温度。

## 数据

`data/krino_matrix/{zh,en}`：zh 2250 / 300 / 450，en 1125 / 150 / 225（train / val / test），按 group 划分。test 只在 benchmark 里使用。

## 运行

```bash
bash experiments/krino-matrix-v1/run.sh
```

需要 GPU。已经训练完的跳过，所以中断后重跑会接着做。全部跑完约 5 小时（RTX 4060 Laptop，每次训练约 35 分钟）。

## 产物

| 路径 | 内容 | 进 git |
|---|---|---|
| `run.sh` | 完整的训练和评测流程 | 是 |
| `results/report.md` | 汇总报告：各任务指标（含 95% bootstrap 区间）、相对 `multilingual-uncertainty` 的配对差异、多种子均值 ± 标准差 | 是 |
| `results/<模型>.json` | 每个模型的全部指标和逐 case 输出 | 是 |
| `logs/` | 每次训练和 benchmark 的日志 | 否（本地调试产物） |
| `checkpoints/` | 模型权重，每个约 1.3 GB | 否 |

## 不在本实验里

- teacher 自一致上限、deepseek flash 零样本基线：另行用 dsh 实现。
- 人工标注 test：不做。
