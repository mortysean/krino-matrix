# Krino Matrix v1 — from mmBERT-base

当前使用的 Matrix 评估器。从 `jhu-clsp/mmBERT-base` 开始，**encoder 用预训练权重，所有头从零初始化**，
不继承任何别的决策模型。比较三头模型（goal + constraints + selection，先硬约束过滤再选择）和只训选择头的消融，
以及 uncertainty 加权（Kendall et al., 2018）和固定权重。

参数总量 **324.1M**（encoder 306.9M + 精炼 transformer 与三个头 17.1M）。

## 模型

| 名称 | 训练的头 | loss 加权 | 种子 |
|---|---|---|---|
| `mmbert-uncertainty` | goal, constraints, selection | uncertainty | 0, 1, 2 |
| `mmbert-fixed` | goal, constraints, selection | 固定（1 / 1 / 0.5） | 0, 1, 2 |
| `mmbert-selection-only` | selection（消融） | — | 0, 1, 2 |

种子 0 的目录不带后缀，种子 1、2 是 `<名称>-s1`、`<名称>-s2`。超参数：全部层参与训练，`max_length 2048`，
`micro_batch 2 × grad_accum 16`，4 个 epoch，在 val 上选 epoch 并拟合温度。

## 数据

`data/krino_matrix/{zh,en}`，zh 2250 / 300 / 450，en 1125 / 150 / 225（train / val / test），按 group 划分。

## 运行

```bash
# 首次：把 encoder 放到 model/checkpoints/mmbert-base（config.json + model.safetensors + tokenizer*）
bash experiments/krino-matrix-v1-mmbert/run.sh
```

需要 GPU。已训练完的会自动跳过，中断后重跑会接着做。

## 产物

发布的 seed 0 uncertainty 模型：<https://huggingface.co/yuxiaohuang2004/krino_matrix/tree/main/matrix-mmbert>。
Hub checkpoint 位于现有公开仓库 `yuxiaohuang2004/krino_matrix` 的 `matrix-mmbert/` 子目录；子目录内附有本模型卡及 benchmark 报告。

| 路径 | 内容 | 进 git |
|---|---|---|
| `run.sh` | 完整的训练和评测流程 | 是 |
| `results/report.md` | 汇总报告：各任务指标（含 95% bootstrap 区间）、配对差异、多种子均值 ± 标准差 | 是 |
| `results/<模型>.json` | 每个模型的全部指标和逐 case 输出 | 是 |
| `logs/` | 每次训练和 benchmark 的日志 | 否（本地调试产物） |
| `checkpoints/` | 模型权重，每个约 1.3 GB；本地只保留 `mmbert-uncertainty`，已移到 `model/checkpoints/` | 否 |

## 怎么读结果

- **三头 vs. 只训选择头**：`mmbert-uncertainty` vs `mmbert-selection-only`，看三任务拆分和硬约束过滤是否让决策更好、违反硬约束更少。
- **对照**：LLM 直接决策见 [llm-zeroshot](../llm-zeroshot/)，标签噪声上限见 [teacher-ceiling](../teacher-ceiling/)。
- 注意 `report.md` 里 `选对` 列和 `原 gold 选对` 列定义不同（前者对 teacher 重打的 best，后者对 typed-decisions 原 gold），
  对外比较请用后者。
