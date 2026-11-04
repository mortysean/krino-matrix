# 归档

这里的代码已经**不在运行路径里**，只为保留历史、方便查阅。新代码不要引用这里。

## decision-nav/ — 旧的 KRINO MATRIX 决策导航

产品方向调整为 KRINO WORLD 后，决策导航（目标 → 澄清问题 → 候选行动 → 决策矩阵排名）整体下线：

| 原位置 | 内容 |
| --- | --- |
| `backend/` | 决策导航的 FastAPI 后端（会话、决策轮次、账号） |
| `frontend/` | 决策导航的 React + Vite 前端 |
| `krino/engine.py`、`krino/steps/` | 决策流程：formulator / clarifier / generator |
| `tests/` | 上述代码的测试 |
| `scripts/serve.sh` | 旧的启动脚本 |

仍在使用、没有归档的部分：
- `model/`：KRINO Matrix 3-Head 模型（训练、推理）。
- `krino/evaluator/`、`krino/common/`：模型的评估接口和基础数据结构。KRINO WORLD 的互动策略（`backend/app/policy.py`）在 `KRINO_POLICY=matrix` 时通过 `krino.evaluator.matrix` 调用模型。

## 鲸鱼娘（Whale Girl）的成人设备控制

KRINO WORLD 的前后端以鲸鱼娘项目为基础，但**没有复制**它的设备控制部分（`actuation/`、TCode 适配器与仿真固件、设备 / 灯光 / 调试台接口、亲密模式）。
这些代码原样留在鲸鱼娘自己的仓库里，没有被修改或删除；KRINO WORLD 的运行路径里没有任何对应的接口或界面（有测试检查）。
