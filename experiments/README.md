# Experiments

最终实验，每个实验一个目录，包含说明（`README.md`）、可复现的运行脚本（`run.sh`）、结果（`results/`）、日志（`logs/`）和模型权重（`checkpoints/`，不进 git）。

| 实验 | 内容 |
|---|---|
| [krino-matrix-v1](krino-matrix-v1/) | Krino Matrix 格式：三头模型 vs. 只训选择头的消融 vs. 原版 Laya，uncertainty / 固定加权，3 个种子 |
| [llm-zeroshot](llm-zeroshot/) | 零样本基线：deepseek flash 每个决策直接调用一次（`LLM_DEFAULT`，即 teacher 本身）的准确率、延迟与成本，作为小模型的对照 |
| [krino-matrix-v1-mmbert](krino-matrix-v1-mmbert/) | 同样的数据和变体，但从 `jhu-clsp/mmBERT-base` 直接训练，所有头从零开始，不继承任何 Laya 决策头 |
