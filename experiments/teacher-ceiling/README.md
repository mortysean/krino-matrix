# Teacher 自一致上限（teacher ceiling）

用生成原标签的**同一套流程**重新标注 Krino Matrix 的 test 集，测出 teacher LLM 自己的自一致度。它决定了学生模型
在这些标签上最多能对齐到什么程度：即使学生输出与“重新标注的标签”完全一致，与原标签的一致率也只能到这条上限，
差额是 teacher 采样随机性带来的标签噪声，学生无从学习。

## 数据与 teacher

- 数据：`data/krino_matrix/zh/test.jsonl`（450 条）、`data/krino_matrix/en/test.jsonl`（225 条），共 675 条。
- 原标签：`examples/krino_matrix_data.py` 的 `label()` 生成——同一 prompt（`LABEL_PROMPT` + `GOAL_TASK` +
  `CONSTRAINTS_TASK` + `BEST_TASK`）、`teacher_output` 结构化输出、temperature 0.7、3 次独立采样、取平均。
- teacher：每条 case 的 `meta.goal_teacher`，全部是 `deepseek/deepseek-v4.1-flash-1017`（OpenRouter）。

## 方法

1. **重新采样**：对每条 case 调用 `LLM("deepseek/deepseek-v4.1-flash-1017")`，prompt 与输出 schema 直接 import 自
   `examples/krino_matrix_data.py`（`LABEL_PROMPT`、`GOAL_TASK`、`CONSTRAINTS_TASK`、`BEST_TASK`、`teacher_output`、
   `levels_text`、`constraints_list`、`normalized`、`mean`、`retry`），校验逻辑与 `label()` 的 `judged()` 相同
   （每个动作的 goal 是 5 个概率、violations 在 [0,1]、best 是分布），失败按 `retry(…, attempts=4)` 重试。
   每次调用独立采样、temperature 0.7，并重新打乱动作展示顺序。区别只在：`label()` 对同一 case 的 3 次运行复用
   同一个打乱顺序（`shown` 在 `asyncio.gather` 之外抽取），本实验每次运行各自打乱——这是任务要求的“每次重新打乱”。
   脚本启动时校验 `LLM.served_model` 确实解析为 `deepseek/deepseek-v4.1-flash-1017`，否则直接退出、不换模型。
2. **原始记录**：每次运行一行写入 `raw/{zh,en}.jsonl`：`set`、`id`、`sample`（0–2）、`index`、`action_order`
   （该次展示顺序）、`constraint_order`、`served_model`、`output`（完整结构化输出）、`latency_ms`（含重试）、
   `attempts`、`error`。断点续跑：某 case 的 3 个运行编号都有有效记录就跳过。
3. **转成 Assessment**（与 `MatrixEvaluator.assess` 规则一致）：
   - `teacher-relabel`：3 次按 `label()` 的方式合并——goal 每次先归一化再取均值、constraints 取均值、best 每次先
     归一化再取均值（`mean()`，保留 4 位小数）。这就是原标签的生成流程。
   - `teacher-single-s1/-s2/-s3`：每次采样单独作为概率。
   - labels 为上一步的概率；`excluded` = 任一硬约束违反概率 ≥ 0.5 的动作及其约束；`choice` = 未排除动作中 best 最大者，
     全部排除时为 `null`。
4. **打分**：直接 import `benchmark/run_krino_matrix.py` 的 `score()`，对 `test.jsonl` 的原始标签打分，一行未改。
5. **纯噪声指标**：只看 3 次新采样彼此——两两之间 best 的 argmax 一致率、goal 期望档位（Σ i·P(level i)）的平均绝对差，
   按 zh / en 分开。

## 运行

```bash
PY=~/anaconda3/envs/krino_matrix/bin/python

# 冒烟：每集前 3 条
$PY experiments/teacher-ceiling/run.py --limit 3 --concurrency 6

# 全量：675 条 × 3 次采样 = 2025 次调用，按已完成的 raw 续跑
$PY experiments/teacher-ceiling/run.py --concurrency 16

# 只用 raw/ 重新打分、重建报告（不再调用 teacher）
$PY experiments/teacher-ceiling/run.py --report-only

# 只跑一个集
$PY experiments/teacher-ceiling/run.py --sets en
```

参数：`--concurrency`（默认 16，`asyncio.Semaphore` 内的 teacher 调用数）、`--limit`（每集只跑前 N 条）、
`--sets`（`zh` / `en`）、`--report-only`。不需要 GPU。

一次完整调用的响应约 1–3 分钟（单次输出 3–12k tokens），`--concurrency 16` 下全量约 3 小时；吞吐上限在 OpenRouter
一侧。

## 产物

| 路径 | 内容 |
|---|---|
| `run.py` | 完整脚本（采样、Assessment、打分、噪声、报告） |
| `raw/{zh,en}.jsonl` | 每次运行的原始记录，续跑与重新打分的依据 |
| `results/teacher-relabel.json` | 3 次平均的评测结果，格式同 `benchmark/run_krino_matrix.py` 的输出 |
| `results/teacher-single-s{1,2,3}.json` | 每次单独采样的评测结果 |
| `results/report.md` | 中文报告：四个模型的指标表、单次均值 ± 标准差、纯噪声、延迟、调用与失败计数、served_model |
| `logs/full.log` | 全量运行的日志 |

每个 JSON 与 benchmark 输出同构：`{"model", "sets": {zh/en: {n_cases, goal, constraints, selection, decision, per_case,
latency_ms, assessments}}, "environment"}`，`assessments` 按 `test.jsonl` 原顺序；另附 `teacher_latency_ms`（单次调用
p50/p95）和 `unscored_cases` 两个附加字段。把四个 JSON 复制到 `experiments/krino-matrix-v1-mmbert/results/` 后，
主实验重新生成报告时会把它们作为额外模型列出。

## 主要结论

（见 `results/report.md`，此处待回填。）
