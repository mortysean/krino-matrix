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
  pipeline.py       end-to-end pipeline
  formulator/       Problem Formulator  (api_formulator)
  observer/         Observer            (api_observer)
  generator/        Action Generator    (api_generator)
  evaluator/        Action Evaluator    (value_evaluator)
  data/             DataSource / Query interface, sagax source
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
| `python examples/value_evaluator_demo.py [data.jsonl]` | Value evaluator: fine-tune, save, reload, score |

## Status

- Implemented: Formulator, Observer, Generator, sagax data source, pipeline
- In progress: Action Evaluator — `value_evaluator` is a non-autoregressive value model (text encoder + linear head, one forward pass per action) with a minimal training loop; it still needs labeled data, so `pipeline_demo.py` keeps a placeholder that scores every action the same

## License

[Apache License 2.0](LICENSE)
