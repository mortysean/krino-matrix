# Experiments

最终实验，每个实验一个目录，包含说明（`README.md`）、可复现的运行脚本（`run.sh`）、结果（`results/`）、日志（`logs/`）和模型权重（`checkpoints/`，不进 git）。

| 实验 | 内容 |
|---|---|
| [llm-zeroshot](llm-zeroshot/) | 零样本基线：deepseek flash 每个决策直接调用一次（`LLM_DEFAULT`，即 teacher 本身）的准确率、延迟与成本，作为小模型的对照 |
| [krino-matrix-v1-mmbert](krino-matrix-v1-mmbert/) | 当前使用的 Matrix 评估器：从 `jhu-clsp/mmBERT-base` 训练，所有头从零开始；三头模型 vs. 只训选择头的消融，uncertainty / 固定加权，3 个种子 |
