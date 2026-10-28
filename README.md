# Krino Matrix

**English** | [简体中文](README.zh-CN.md)

Krino Matrix aims to free up human cognitive resources.

By using AI to understand complex states, generate feasible options, and evaluate the value of actions, we reduce the cognitive burden of processing information, analyzing, and making decisions — so everyone can devote their limited attention to more creative and meaningful work.

## Core Concepts

### Basic Elements

| Element | Description |
| --- | --- |
| `State` | The current situation |
| `Problem` | A decision problem: `State` + objective + constraints |
| `Action` | A single candidate action |
| `ActionSpace` | The set of candidate actions |
| `Decision` | The chosen action and its score |

### Core Modules

| Module | Input → Output | Role |
| --- | --- | --- |
| Problem Formulator | natural-language request → `Problem` | Turns the user's request into a decision problem |
| Observer | `Problem` + data sources → `State` | Gathers the data the decision needs into the state |
| Action Generator | `State` + objective + constraints → `ActionSpace` | Generates candidate actions |
| Action Evaluator | `State` + objective + `Action` → score | Evaluates the value of an action |

Each module is an abstract interface; the `api_*` implementations are backed by a hosted LLM.

### Pipeline

`Pipeline` chains the modules into one decision:

```
request ─▶ Formulator ─▶ Observer ─▶ Generator ─▶ Evaluator ─▶ Decisions (best first)
                            ▲
                      data sources
```

The observer is optional; without one, the state is only what the formulator read from the request. Actions are evaluated concurrently.

### Data Sources

A `DataSource` offers a set of `Query`s, each with a name, a description and a parameter schema. The API observer exposes them to the LLM as tools, and stores the query results in the state as-is under `observations`, so no figure passes through the LLM.

Built-in source:

| Source | Coverage |
| --- | --- |
| `SagaxSource` ([sagax data platform](https://www.sagax.cn/data/v1/)) | A-share stocks (screening, valuation, financials, capital flows), indices, ETFs, futures, options, special reports, macro indicators, news, announcements and research |

sagax is a data platform built by the author. It collects China market data from sources such as tushare and tqsdk on a daily schedule, keeps financials point-in-time (PIT), and serves everything through an HTTP API and the Python SDK `sagax-data`. Tables, indicators and examples are documented on the [sagax site](https://www.sagax.cn/data/v1/); an API key and secret are needed to query it.

## Project Structure

```
core/
  schema.py         basic elements
  matrix.py         typed decision-case format and dataset validation
  pipeline.py       end-to-end pipeline
  formulator/       Problem Formulator  (api_formulator)
  observer/         Observer            (api_observer)
  generator/        Action Generator    (api_generator)
  evaluator/        Value and Matrix decision evaluators
  data/             DataSource / Query interface, sagax source
decision_core/      device-independent web decision flow and safety rules
model_adapter/      LLM and Matrix evaluator adapters
backend/            FastAPI, authentication, conversations and persistence
frontend/           React + Vite web application
benchmark/          typed-decisions benchmark runners and metrics
experiments/        reproducible model experiments and reports
services/
  llm.py            unified LLM interface over OpenRouter, litellm and the Anthropic SDK
examples/           runnable demos
```

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in LLM providers and the sagax API key
```

| Demo | What it runs |
| --- | --- |
| `python examples/api_formulator_demo.py ["request"]` | Formulator only |
| `python examples/api_generator_demo.py` | Generator only, on a hand-written state |
| `python examples/data_demo.py` | sagax data queries |
| `python examples/pipeline_demo.py ["request"]` | The whole pipeline |
| `python examples/value_evaluator_data.py [--cases N]` | Synthesize labeled cases for the value evaluator with a teacher LLM |
| `python examples/value_evaluator_demo.py [data/value]` | Value evaluator: train, calibrate, evaluate, save, reload, score |

## Web Decision Assistant (V2.5 P0)

First version of the KRINO MATRIX V2.5 spec: goal → state/constraints → clarifying questions when needed (at most 3, skippable) → 2–4 candidates → evaluation → action cards → choice and feedback.

| Directory | Contents |
|---|---|
| `decision_core/` | Device-independent decision core: one clarification / decision / error contract, clarifier, card generator, explicit safety rules |
| `model_adapter/` | Concrete models: traced LLM calls; evaluator `baseline` (default, a general LLM compares, labeled as test mode, no scores shown) or `matrix` (experimental KRINO Matrix model, shows its real selection probabilities) |
| `backend/` | FastAPI: email login, conversations and decision snapshots, feedback, personal memory, usage, call latency and failures; PostgreSQL (SQLite for local dev) |
| `frontend/` | React + Vite: Today / Chats / Decision / Settings, product demo, stage progress, mobile layout, reduced motion |

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn backend.main:app --port 8000          # open http://localhost:8000
# frontend hot reload: run uvicorn backend.main:app --reload and (cd frontend && npm run dev) together
pytest tests                                   # backend and core tests, no model calls
```

Configuration is in the Web section of `.env.example` (`DATABASE_URL`, `KRINO_SECRET_KEY`, `KRINO_EVALUATOR`, ...). Email delivery is not wired up yet, so password reset links go to the server log; balance, top-up and BYOK are marked as not live in Settings.

## Model Experiments

`core/matrix.py` defines the `krino-matrix/1` case format. The Matrix evaluator has separate goal, constraint and action-selection heads; hard-constraint rules filter unsafe candidates before selection. Training data is expected under `data/krino_matrix/{zh,en}` and checkpoints are kept locally (they are excluded from Git). See [experiment reports](experiments/README.md) for training details and results. The typed-decisions comparison is documented in [benchmark/results/typed_decisions_laya/report.md](benchmark/results/typed_decisions_laya/report.md).

## Status

- Implemented: Formulator, Observer, Generator, sagax data source, pipeline
- Implemented, experimental: `MatrixEvaluator` predicts goal attainment, constraint violations and action selection in one pass; a trained checkpoint is required to use it. The pipeline demo falls back to equal placeholder scores when no checkpoint is present.
- Also available: `value_evaluator` is a Laya-style goal-value model trained with RLCD on teacher-labeled cases; it returns a calibrated distribution over ordered rubric levels.
- Web app: the LLM baseline is the default evaluator; the trained Matrix evaluator can be selected in experimental mode.

## License

[Apache License 2.0](LICENSE)
