# KRINO MATRIX

**English** | [简体中文](README.zh-CN.md)

The open parts of [KRINO MATRIX](https://krinomatrix.com): a client SDK and API docs for the KRINO WORLD app, and the inference framework of the KRINO Matrix decision model.

| | |
| --- | --- |
| [`sdk/python/`](sdk/python) | Python client for KRINO WORLD: accounts, characters, chat (whole or streamed replies), memory, speech |
| [`docs/api/`](docs/api) | API guide and the full OpenAPI 3.1 schema |
| [`model/`](model) · [`krino/`](krino) | Inference framework of the KRINO Matrix decision model |
| [Hugging Face](https://huggingface.co/yuxiaohuang2004/krino_matrix) | Model weights (`matrix-mmbert/`) |

## KRINO WORLD SDK

KRINO WORLD is a platform of AI characters that remember you. You can talk to them by text or voice in the browser, at [krinomatrix.com/cn/products/world/](https://krinomatrix.com/cn/products/world/) (mainland China) or [krinomatrix.com/global/products/world/](https://krinomatrix.com/global/products/world/) (international). The SDK uses the same API as the app.

```bash
pip install "git+https://github.com/mortysean/krino-matrix#subdirectory=sdk/python"
```

```python
from krino_world import Client

with Client(region="global") as kw:
    kw.login("me", "secret")
    character = kw.characters()[0]
    session = kw.start_session(character["id"])
    for event in kw.stream(session["id"], "Hi!"):
        if event.name == "delta":
            print(event.data["text"], end="", flush=True)
```

See the [SDK guide](sdk/python/README.md) and the [API guide](docs/api/README.md).

## KRINO Matrix decision model

KRINO Matrix takes a decision case: the state, a goal, constraints (hard ones, or soft preferences), and candidate actions. In one forward pass it predicts three things:

- **goal**: for each action, a distribution over five levels of how well it achieves the goal
- **constraints**: for each action and constraint, the probability that the action breaks it
- **selection**: a distribution over the actions, weighing all of the above

The decision filters first and then selects. An action that likely breaks a hard constraint is excluded, whatever its other scores, and the most probable action among the rest is chosen. In KRINO WORLD, this model is the experimental interaction policy (`KRINO_POLICY=matrix`): at each event it picks how the character responds.

The model is a shared [`jhu-clsp/mmBERT-base`](https://huggingface.co/jhu-clsp/mmBERT-base) encoder with three heads. It reads Chinese and English. Benchmark results are on the [model card](https://huggingface.co/yuxiaohuang2004/krino_matrix), and the full report is in [`experiments/krino-matrix-v1-mmbert/`](experiments/krino-matrix-v1-mmbert/results/report.md).

```bash
pip install -r requirements.txt
```

```python
from krino.common.schema import Action, Constraint, Problem, State
from model.inference import MatrixEvaluator, download

evaluator = MatrixEvaluator(download())   # fetches matrix-mmbert/ from Hugging Face the first time

problem = Problem(
    state=State(data={"budget_cny": 300, "time": "Saturday evening"}),
    goal="Have a fun dinner with friends",
    constraints=[Constraint(id="budget_cap", text="Spend no more than 300 CNY in total", hard=True)],
)
actions = [
    Action(id="book_tasting_menu", description="Book a restaurant at 800 CNY per person"),
    Action(id="cook_hotpot_at_home", description="Buy groceries and have hotpot at home, about 200 CNY"),
]
result = evaluator.assess(problem, actions)
print(result.choice)            # the recommended action, or None if every action is excluded
print(result.excluded)          # action id → hard constraints it likely breaks
print(result.labels.best)       # the selection distribution
```

- In mainland China, set `HF_ENDPOINT=https://hf-mirror.com` or call `download(endpoint="https://hf-mirror.com")`.
- The model runs on GPU (bfloat16) when one is available, and on CPU otherwise.
- `krino/evaluator/` wraps the model in the `Evaluator` interface (`MatrixModelEvaluator`). It also has explicit safety rules that never depend on the model: anything that moves money, signs something or can't be undone is always left for a person to confirm.

The scores are relative preferences within one set of candidates. They are not probabilities of success, and they are not guarantees of benefit or safety. The model is experimental.

## Layout

```
sdk/python/        krino-world Python client
docs/api/          API guide (README.md) and schema (openapi.json)
model/network.py   MatrixModel: encoder, refining transformer, three heads
model/dataset.py   the krino-matrix/1 case and label format
model/inference/   MatrixEvaluator (one forward pass, hard-constraint filter, selection), Hugging Face download
krino/             shared schema (Problem, Action, Constraint), Evaluator interface, safety rules
experiments/       the benchmark report of the published checkpoint
```

## License

[Apache License 2.0](LICENSE).
