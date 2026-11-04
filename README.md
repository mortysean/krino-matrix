# KRINO WORLD

**English** | [简体中文](README.zh-CN.md)

KRINO WORLD is the KRINO MATRIX platform for ACG-style AI characters: create or import a persona and talk to it by text, voice and a 3D avatar. Characters keep the shared experiences you confirm, and their personality stays stable but can evolve. The default official character is **WHALE GIRL**. Every character is labelled as an AI.

KRINO MATRIX is the parent brand, KRINO WORLD the software (`backend/` + `frontend/`), KRINO GLASSES the future hardware (a device interface and a browser simulator exist today), and KRINO CORE the persona, memory and interaction-policy layer.

## Quick start

Requires Python 3.11, PostgreSQL 14+ (`initdb` / `pg_ctl` on PATH or `PG_BIN`), and Node 18+ for the end-to-end tests only.

```bash
scripts/world.sh setup        # deps, .env, local database (.pgdata/, port 5433) + migrations, default VRM model
# edit .env: set OPENROUTER_API_KEY, or LLM_PROVIDER=mock for an offline demo
scripts/world.sh run          # http://127.0.0.1:8630   (--reload for development)
scripts/world.sh start|stop|status|logs
scripts/world.sh db init|migrate|revision "msg"|psql
scripts/world.sh test         # backend tests (separate test database, offline mock model)
scripts/world.sh e2e          # browser end-to-end tests against a running server
```

All settings are in the KRINO WORLD section of [`.env.example`](.env.example).

## What is in it

| Page | Contents |
| --- | --- |
| Interact | 3D VRM avatar (blink, gaze, idle motion, expressions, lip sync, preset animations); text / voice; streamed replies; user-triggered gestures; image sharing; history and memory drawer; fallbacks for model load failure and network loss |
| Persona | All persona fields, interaction style, allowed expressions and animations, voice; form / Markdown / JSON editing; versions; import (SillyTavern / RisuAI cards, Markdown, JSON, legacy Whale Girl packs) and export; generation from a description; custom VRM upload |
| Memory | Memories labelled as real event / model inference / fiction; confirm, edit (with correction history), forget, delete; relationship state; export |
| Workshop | Browse, search, categories; preview; install and download; publish or upload; versions and updates; votes, comments; reports, auto-hide and admin review |
| Glasses | KRINO GLASSES simulator: camera, microphone and head pose as device input; character behaviour rendered from structured AR events |
| Settings | LLM / VLM / STT / TTS status (never the keys); voice, interaction and privacy preferences; KRINO Evaluator mode and self-test; device status; latency and errors |

**KRINO Evaluator** is now only the internal interaction policy. Per event it chooses among `NO_ACTION`, `RESPOND`, `STORY`, `PERCEIVE`, `EMOTE`, `ANIMATE` and `REMEMBER`. `KRINO_POLICY=rules` (default) is a rule policy; `matrix` runs the existing 3-Head Matrix model through its unchanged interface, but its weights were not trained on interaction behaviour, so its output is labelled experimental and falls back to rules when unavailable. Hard constraints are enforced in code for every policy.

Architecture, data model, what was reused from Whale Girl and what was removed: [docs/world/ARCHITECTURE.md](docs/world/ARCHITECTURE.md). The retired decision-navigation app is in [`archive/`](archive/README.md).

## KRINO Matrix model

`model/` holds the 3-Head Matrix network (goal, constraint and selection heads on `jhu-clsp/mmBERT-base`); `bash scripts/train.sh` and `bash scripts/benchmark.sh` train and score it. See the [experiment report](experiments/krino-matrix-v1-mmbert/README.md).

## License

[Apache License 2.0](LICENSE). Third party: three.js (MIT), @pixiv/three-vrm (MIT), default VRM sample model (VRM Public License 1.0).
