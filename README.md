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

### Core Modules

| Module | Input → Output | Role |
| --- | --- | --- |
| Problem Formulator | natural-language request → `Problem` | Turns the user's request into a decision problem |
| Clarifier | request + `Problem` → one question or none | Asks for the one missing fact that could change the recommendation |
| Action Generator | `State` + objective + constraints → `ActionSpace` | Generates candidate actions |
| Action Evaluator | `Problem` + `ActionSpace` → ranking | The KRINO Matrix model: ranks the candidates and excludes those that break a hard constraint |

The formulator, clarifier and generator call a hosted LLM; the evaluator is the trained Matrix model.

### Decision Flow

`DecisionEngine` in `krino/engine.py` chains the modules into one decision turn:

```
request ─▶ Formulator ─▶ Clarifier ─▶ Generator ─▶ Evaluator ─▶ safety rules ─▶ decision
```

The evaluator runs the Matrix model trained from `jhu-clsp/mmBERT-base` with uncertainty loss weighting (`krino/evaluator/` in the flow, `model/inference/` for the model itself).

### Data Sources

A `DataSource` offers a set of `Query`s, each with a name, a description and a parameter schema, so an LLM can call them as tools. The data source is not wired into the decision flow yet.

Built-in source:

| Source | Coverage |
| --- | --- |
| `SagaxSource` ([sagax data platform](https://www.sagax.cn/data/v1/)) | A-share stocks (screening, valuation, financials, capital flows), indices, ETFs, futures, options, special reports, macro indicators, news, announcements and research |

sagax is a data platform built by the author. It collects China market data from sources such as tushare and tqsdk on a daily schedule, keeps financials point-in-time (PIT), and serves everything through an HTTP API and the Python SDK `sagax-data`. Tables, indicators and examples are documented on the [sagax site](https://www.sagax.cn/data/v1/); an API key and secret are needed to query it.

## Project Structure

```
krino/                the Python package
  engine.py           one decision turn through every step, and build_engine() for the web app
  contract.py         the engine's input and the clarification / decision / error responses clients get
  steps/              the three hosted-LLM steps
    formulator.py       request → decision problem
    clarifier.py        one key question when needed
    generator.py        candidate actions
  evaluator/          evaluation and safety
    base.py             the Evaluator interface
    matrix.py           evaluation by the Matrix model (model/inference)
    rules.py            explicit safety rules
  common/             shared by every part
    schema.py           basic elements
    llm.py, tracing.py  LLM interface (OpenRouter, litellm, Anthropic SDK) and call records
  data/               DataSource / Query interface, sagax source
model/                the Matrix model
  network.py          the network, shared by training and inference
  dataset.py          the case format (krino-matrix/1) for training, benchmarks and the data scripts
  training/           training framework: trainer.py (training, calibration), train.py (command), benchmark.py
  inference/          inference framework: MatrixEvaluator, one forward pass, hard-constraint filter, selection
  checkpoints/        trained weights (git-ignored); the web app runs mmbert-uncertainty
data/                 scripts that build and check the datasets, sagax demo; the data itself is git-ignored
scripts/              bash scripts: train, benchmark, serve the web app, test
backend/              FastAPI, authentication, conversations and persistence
frontend/             React + Vite web application
experiments/          reproducible model experiments and reports
tests/                backend and decision-flow tests
```

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env    # fill in LLM providers and the sagax API key
```

| Command | What it runs |
| --- | --- |
| `bash scripts/serve.sh` | Build the frontend and serve the web app (`--dev`: API only, next to `npm run dev`) |
| `bash scripts/test.sh` | Backend and decision-flow tests, no model calls |
| `bash scripts/train.sh [out_dir] [seed]` | Train a Matrix model with the current recipe (mmBERT-base, uncertainty weighting) |
| `bash scripts/benchmark.sh [checkpoint ...]` | Score on the test sets; default `model/checkpoints/mmbert-uncertainty` |
| `python data/build_data.py ...` | Build datasets labeled by a teacher LLM; the other data scripts are in [data/README.md](data/README.md) |
| `python data/sagax_demo.py` | sagax data queries |

## Web Decision Assistant (V2.5 P0)

First version of the KRINO MATRIX V2.5 spec: goal → state/constraints → clarifying questions when needed (at most 3, skippable) → 2–4 candidates → evaluation → action cards → choice and feedback.

| Directory | Contents |
|---|---|
| `krino/` | Device-independent decision flow: one clarification / decision / error contract, clarifier, card generator, Matrix evaluation (shows its real selection probabilities; checkpoint set by `KRINO_MATRIX_CHECKPOINT`), explicit safety rules |
| `backend/` | FastAPI: email login, conversations and decision snapshots, feedback, personal memory, usage, call latency and failures; PostgreSQL (SQLite for local dev) |
| `frontend/` | React + Vite: Today / Chats / Decision / Settings, product demo, stage progress, mobile layout, reduced motion |

```bash
pip install -r requirements.txt
bash scripts/serve.sh          # open http://localhost:8000
# frontend hot reload: run bash scripts/serve.sh --dev and (cd frontend && npm run dev) together
bash scripts/test.sh           # backend and decision-flow tests, no model calls
```

Configuration is in the Web section of `.env.example` (`DATABASE_URL`, `KRINO_SECRET_KEY`, `KRINO_MATRIX_CHECKPOINT`, ...). Email delivery is not wired up yet, so password reset links go to the server log; balance, top-up and BYOK are marked as not live in Settings.

## Model Experiments

`model/dataset.py` defines the `krino-matrix/1` case format. The Matrix evaluator has separate goal, constraint and action-selection heads; hard-constraint rules filter unsafe candidates before selection. Training data is expected under `data/krino_matrix/{zh,en}` and checkpoints are kept locally (they are excluded from Git). The current model is trained in-house from the small multilingual encoder `jhu-clsp/mmBERT-base`, with all three task heads initialised from scratch and uncertainty loss weighting; it is the only checkpoint kept locally, `model/checkpoints/mmbert-uncertainty`. See the [experiment report](experiments/krino-matrix-v1-mmbert/README.md) for training details and results.

## Status

- Implemented: Formulator, Clarifier, Generator, decision engine, sagax data source
- Implemented, experimental: `MatrixEvaluator` predicts goal attainment, constraint violations and action selection in one pass; the web app needs a trained checkpoint to rank candidates.

## License

[Apache License 2.0](LICENSE)
