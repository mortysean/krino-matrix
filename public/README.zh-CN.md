# KRINO MATRIX

[English](README.md) | **简体中文**

[决策矩阵 KRINO MATRIX](https://krinomatrix.com) 的开源部分：KRINO WORLD 应用的客户端 SDK 和接口文档，以及 KRINO Matrix 决策模型的推理框架。

| | |
| --- | --- |
| [`sdk/python/`](sdk/python) | KRINO WORLD 的 Python 客户端：账号、角色、对话（整句或流式）、记忆、语音 |
| [`docs/api/`](docs/api) | 接口说明和完整的 OpenAPI 3.1 规范 |
| [`model/`](model) · [`krino/`](krino) | KRINO Matrix 决策模型的推理框架 |
| [Hugging Face](https://huggingface.co/yuxiaohuang2004/krino_matrix) | 模型权重（`matrix-mmbert/`） |

## KRINO WORLD SDK

KRINO WORLD 是一个 AI 角色平台，角色会记得你。在浏览器里就能和她们用文字、语音聊天：[krinomatrix.com/cn/products/world/](https://krinomatrix.com/cn/products/world/)（中国大陆）、[krinomatrix.com/global/products/world/](https://krinomatrix.com/global/products/world/)（国际）。SDK 用的接口和网页版完全一样。

```bash
pip install "git+https://github.com/mortysean/krino-matrix#subdirectory=sdk/python"
```

```python
from krino_world import Client

with Client(region="cn") as kw:
    kw.login("me", "secret")
    character = kw.characters()[0]
    session = kw.start_session(character["id"])
    for event in kw.stream(session["id"], "你好呀"):
        if event.name == "delta":
            print(event.data["text"], end="", flush=True)
```

详见 [SDK 说明](sdk/python/README.zh-CN.md)和[接口说明](docs/api/README.zh-CN.md)。

## KRINO Matrix 决策模型

KRINO Matrix 的输入是一个决策问题：当前状态、目标、约束（硬约束或软性偏好）和几个候选行动。模型一次前向就给出三样结果：

- **目标（goal）**：每个行动达成目标的程度，是五个档位上的概率分布
- **约束（constraints）**：每个行动违反每条约束的概率
- **选择（selection）**：综合以上，在各行动之间的选择分布

决策时先过滤、再选择：可能违反硬约束的行动直接排除，不管其他分数多高；在剩下的行动里，选概率最高的那个。在 KRINO WORLD 里，这个模型是实验性的互动策略（`KRINO_POLICY=matrix`），每次事件发生时，由它选择角色怎么回应。

模型由共享的 [`jhu-clsp/mmBERT-base`](https://huggingface.co/jhu-clsp/mmBERT-base) 编码器加三个输出头组成，支持中文和英文。评测结果见[模型卡](https://huggingface.co/yuxiaohuang2004/krino_matrix)，完整报告在 [`experiments/krino-matrix-v1-mmbert/`](experiments/krino-matrix-v1-mmbert/results/report.md)。

```bash
pip install -r requirements.txt
```

```python
from krino.common.schema import Action, Constraint, Problem, State
from model.inference import MatrixEvaluator, download

evaluator = MatrixEvaluator(download())   # 第一次运行时从 Hugging Face 下载 matrix-mmbert/

problem = Problem(
    state=State(data={"budget_cny": 300, "time": "周六晚上"}),
    goal="和朋友吃一顿开心的晚饭",
    constraints=[Constraint(id="budget_cap", text="总花费不超过 300 元", hard=True)],
)
actions = [
    Action(id="book_tasting_menu", description="预订人均 800 元的高级餐厅"),
    Action(id="cook_hotpot_at_home", description="买菜在家一起涮火锅，约 200 元"),
]
result = evaluator.assess(problem, actions)
print(result.choice)            # 推荐的行动；所有行动都被排除时是 None
print(result.excluded)          # 行动 id → 它可能违反的硬约束
print(result.labels.best)       # 选择分布
```

- 在中国大陆，设置 `HF_ENDPOINT=https://hf-mirror.com`，或者调用 `download(endpoint="https://hf-mirror.com")`。
- 有 GPU 时用 GPU（bfloat16）运行，没有就用 CPU。
- `krino/evaluator/` 把模型封装成 `Evaluator` 接口（`MatrixModelEvaluator`）。里面还有一套不依赖模型的显式安全规则：涉及资金、签约或不可逆的操作，一律留给人自己确认。

分数是同一组候选之间的相对倾向，不是成功概率，也不是收益或安全保证。模型仍处于实验阶段。

## 目录

```
sdk/python/        krino-world Python 客户端
docs/api/          接口说明（README.md）和规范（openapi.json）
model/network.py   MatrixModel：编码器、精炼 Transformer、三个输出头
model/dataset.py   krino-matrix/1 样本和标注格式
model/inference/   MatrixEvaluator（一次前向、硬约束过滤、选择）、从 Hugging Face 下载
krino/             共用数据结构（Problem、Action、Constraint）、Evaluator 接口、安全规则
experiments/       已发布权重的评测报告
```

## 许可证

[Apache License 2.0](LICENSE)。
