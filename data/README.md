# data

构建和检查 Krino Matrix 数据集的脚本，以及 sagax 数据查询示例。脚本进 git；数据集、数据库和评测输出只在本地（git 忽略）。

| 脚本 | 作用 |
|---|---|
| `build_data.py` | 用教师 LLM 构建并标注数据集：`typed-decisions`（英文，来自 HF 数据集）、`generate`（新合成的中文样本）、`legacy`（旧格式转换） |
| `merge_data.py` | 把新生成的样本合并进目标数据集，按 id 去重，可重复运行 |
| `unify_data.py` | `relabel-en` 把英文集统一成中文集的结构和标注标准；`resplit` 按 group 统一重新切分 |
| `check_data.py` | 训练前检查：重复 id、跨 split 泄漏、缺失标签等；硬性检查失败时返回非零 |
| `sagax_demo.py` | sagax 数据查询示例（需要 `.env` 里的 `SAGAX_API_KEY` / `SAGAX_SECRET_KEY`） |

本地目录：

| 路径 | 内容 |
|---|---|
| `krino_matrix/{zh,en}/` | 训练数据，每种语言 `train.jsonl` / `val.jsonl` / `test.jsonl` |
| `krino.db` | Web 应用的本地 SQLite 数据库（没有配置 `DATABASE_URL` 时使用） |
| `test-krino.db` | 测试用数据库 |
| `benchmark/` | `scripts/benchmark.sh` 的评测输出 |
