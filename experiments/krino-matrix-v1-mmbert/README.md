# Krino Matrix v1 — from mmBERT-base

与 [krino-matrix-v1](../krino-matrix-v1/) **同样的数据、同样的三种变体、同样的超参数和评测**，唯一的差别是起点：
不再加载 `laya-multilingual`，而是直接从 `jhu-clsp/mmBERT-base` 开始，**encoder 用预训练权重，所有头从零初始化**。
这个实验回答一个问题：Krino Matrix 的决策能力有多少来自 Laya 已有的决策头预训练，多少是我们自己的数据和训练给的。

## 与 krino-matrix-v1 的唯一差别

| | krino-matrix-v1 | 本实验 |
|---|---|---|
| 起点 | `convaiinnovations/laya-multilingual`（322M） | `jhu-clsp/mmBERT-base`（307M encoder） |
| encoder 权重 | Laya 微调过（RLCD 15,987 updates） | 纯 mmBERT 预训练权重，没经过任何决策训练 |
| 精炼 transformer（2 层） | 继承 Laya 的 head | 随机初始化 |
| 选择头 | 继承 Laya 的 option scorer | 随机初始化 |
| kind embedding | 零初始化（本来就等价于没有） | 零初始化（相同） |
| 数据 / 超参数 / 评测 | — | 完全相同 |

参数总量两边都是 **324.1M**（encoder 306.9M + 17.1M 头），因此这是一个干净的对照：**只有"是否有决策头预训练"这一个变量不同**。

## 模型

| 名称 | 训练的头 | loss 加权 | 种子 |
|---|---|---|---|
| `mmbert-uncertainty` | goal, constraints, selection | uncertainty | 0, 1, 2 |
| `mmbert-fixed` | goal, constraints, selection | 固定（1 / 1 / 0.5） | 0, 1, 2 |
| `mmbert-selection-only` | selection（消融） | — | 0, 1, 2 |

种子 0 的目录不带后缀，种子 1、2 是 `<名称>-s1`、`<名称>-s2`。超参数与 v1 一致：全部层参与训练，`max_length 2048`，
`micro_batch 2 × grad_accum 16`，4 个 epoch，在 val 上选 epoch 并拟合温度。

## 数据

与 v1 完全相同：`data/krino_matrix/{zh,en}`，zh 2250 / 300 / 450，en 1125 / 150 / 225（train / val / test），按 group 划分。

## 运行

```bash
# 首次：把 encoder 放到 checkpoints/base/mmbert-base（config.json + model.safetensors + tokenizer*）
bash experiments/krino-matrix-v1-mmbert/run.sh
```

需要 GPU。已训练完的会自动跳过，中断后重跑会接着做。

## 产物

发布的 seed 0 uncertainty 模型：<https://huggingface.co/yuxiaohuang2004/krino_matrix/tree/main/matrix-mmbert>。
Hub checkpoint 位于现有公开仓库 `yuxiaohuang2004/krino_matrix` 的 `matrix-mmbert/` 子目录；仓库根目录的 model card 汇总了 MatrixEvaluator 和原 ValueEvaluator，子目录内附有本模型卡及 benchmark 报告。

| 路径 | 内容 | 进 git |
|---|---|---|
| `run.sh` | 完整的训练和评测流程 | 是 |
| `results/report.md` | 汇总报告：各任务指标（含 95% bootstrap 区间）、配对差异、多种子均值 ± 标准差 | 是 |
| `results/<模型>.json` | 每个模型的全部指标和逐 case 输出 | 是 |
| `logs/` | 每次训练和 benchmark 的日志 | 否（本地调试产物） |
| `checkpoints/` | 模型权重，每个约 1.3 GB | 否 |

## 怎么读结果

- **和 v1 的同名变体比**：`mmbert-uncertainty` vs `multilingual-uncertainty`。差值就是 Laya 决策头预训练的贡献。
  如果两者接近，说明决策能力基本来自 Krino Matrix 数据本身；如果 v1 明显更好，说明 Laya 的预训练有迁移价值。
- **和原版 Laya 零样本比**：Laya 权重就在本实验的起点里，所以它的零样本成绩在这批数据上的意义更直接——
  它衡量的是"同样的 encoder，加上别人的决策头预训练、不加我们的数据"能做到什么。
- 注意 `report.md` 里 `选对` 列和 `原 gold 选对` 列定义不同（前者对 teacher 重打的 best，后者对 typed-decisions 原 gold），
  对外比较请用后者。
