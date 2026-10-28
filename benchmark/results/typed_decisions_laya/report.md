# Typed Decisions：Laya 系列对比

- Benchmark：`LocalLLaMA/typed-decisions` @ `9ee69423ce0b0568c2d2d86e92c72ed7952fd084`，`all/test`，400 cases / 2000 decisions，sha256 `4f294f218ea1da27…`
- 设备：NVIDIA GeForce RTX 4060 Laptop GPU；torch 2.6.0+cu124；单条请求、batch=1
- 本次测量的模型都只推理，没有用这个 Benchmark 的 train 或 test 训练过，属于 zero-shot

## 总体

| 模型 | 来源 | Accuracy ↑ | KL ↓ | Brier ↓ | ECE ↓ | Soft Acc ↑ | Score MAE ↓ | p50 延迟 |
|---|---|---|---|---|---|---|---|---|
| **typed-decisions-base** | 本次测量 | 0.769 | 0.117 | 0.061 | 0.216 | 0.509 | 0.243 | 102 ms |
| **multilingual-base** | 本次测量 | 0.345 | 1.112 | 0.463 | 0.319 | 0.377 | 0.760 | 46 ms |
| **multilingual-krino** | 本次测量 | 0.339 | 0.719 | 0.340 | 0.238 | 0.405 | 0.761 | 48 ms |
| Laya Base | 公开数据（zero-shot） | 0.362 | – | 0.316 | 0.175 | 0.332 | 0.694 | – |
| Laya fine-tuned | 公开数据（fitted on train (dataset card's second table; not comparable with zero-shot rows)） | 0.766 | – | 0.062 | 0.213 | 0.471 | 0.242 | – |
| JEV 1.13.0 | 公开数据（zero-shot） | 0.727 | 1.442 | 0.148 | 0.144 | 0.580 | 0.391 | 710 ms |
| Prior (ignores the input) | 数据集卡片 | 0.470 | 0.347 | 0.189 | 0.088 | – | – | – |
| Uniform | 数据集卡片 | 0.308 | 0.444 | 0.238 | 0.169 | – | – | – |

本次测量的 KL / Brier / ECE 按官方 `bench/score_with_jobs.py`（全部决策、10 bins）；Soft Acc / Score MAE 按 Laya 定义。Laya 两行的 Brier / ECE 是 Laya 定义（仅 choice+noul、15 bins），与官方定义不能直接比，accuracy 两种定义一致。

## 分组 accuracy

| 分组 | typed-decisions-base | multilingual-base | multilingual-krino | Laya fine-tuned（公开） | JEV 1.13.0（公开） |
|---|---|---|---|---|---|
| `noul` | 0.857 | 0.483 | 0.540 | 0.857 | 0.775 |
| `choice` | 0.733 | 0.288 | 0.267 | 0.733 | 0.720 |
| `score` | 0.730 | 0.284 | 0.242 | 0.723 | 0.696 |
| `agent_trace_observability` | 0.726 | 0.276 | 0.246 | 0.730 | – |
| `customer_service` | 0.760 | 0.416 | 0.332 | 0.764 | – |
| `invoice_processing` | 0.816 | 0.310 | 0.470 | 0.804 | – |
| `security_incidents` | 0.774 | 0.378 | 0.308 | 0.766 | – |

来源：
- Laya Base：https://huggingface.co/convaiinnovations/laya-typed-decisions (README.md @ e929ae5cf69bc34259cd2f95c9e91145b818b1f0)
- Laya fine-tuned：https://huggingface.co/convaiinnovations/laya-typed-decisions (README.md @ e929ae5cf69bc34259cd2f95c9e91145b818b1f0); accuracy also in https://huggingface.co/datasets/LocalLLaMA/typed-decisions (README.md @ 9ee69423ce0b0568c2d2d86e92c72ed7952fd084)
- JEV 1.13.0：https://huggingface.co/datasets/LocalLLaMA/typed-decisions (README.md @ 9ee69423ce0b0568c2d2d86e92c72ed7952fd084) (accuracy, KL, Brier, ECE, p50 latency, per-type accuracy); soft accuracy and score MAE as cited by https://huggingface.co/convaiinnovations/laya-typed-decisions (README.md @ e929ae5cf69bc34259cd2f95c9e91145b818b1f0), third-party
