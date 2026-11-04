# KRINO WORLD

**English** | [简体中文](README.zh-CN.md)

KRINO WORLD is the KRINO MATRIX platform for ACG-style AI characters. You chat by text and voice with characters that remember you, and you can create, import, or adopt characters from the workshop. The default character is **Whale Girl** (鲸鱼娘), the rice-loving, overthinking "big blue fat fish" from the Chinese internet's DeepSeek fan persona. Every character is labelled as an AI.

## Quick start

You need Python 3.11 and PostgreSQL 14+ (`initdb` / `pg_ctl` on your PATH, or set `PG_BIN`). The end-to-end tests also need Node 18+.

```bash
scripts/world.sh setup        # deps, .env, database (data/pgdata/), voice model + Live2D sample (data/models/)
# edit .env: set OPENROUTER_API_KEY, or LLM_PROVIDER=mock for an offline demo
scripts/world.sh run          # http://127.0.0.1:8630
scripts/world.sh start|stop|status|logs
scripts/world.sh db init|migrate|revision "msg"|psql
scripts/world.sh test         # backend tests
scripts/world.sh e2e          # browser end-to-end tests against a running server
```

## What's in it

The UI follows one rule: save the user's attention. If one click can do it, don't make it two.

| Page | Contents |
| --- | --- |
| Chat | The character as a 2D portrait or Live2D model next to the conversation, with streamed replies. Every reply has a speaker button. The microphone starts on one click and sends on the next. There are preset gestures, and a memory drawer where memories are labelled as real, inferred, or fiction |
| Characters | Your cast, plus an editor for the common fields, the look (built-in portrait, your own upload, or Live2D), and the voice. Everything else is under "More" |
| Workshop | Official picks and shared characters, adopted with one click. Also search, categories, votes, comments, reports, and admin review |
| Settings | Toggles that save instantly. "Advanced" holds model service status, the interaction policy, the KRINO GLASSES simulator, and run status |

- **Voice:** speech is synthesized locally by default with [Kokoro-82M Chinese](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) (Apache-2.0). It's free, offline, and has 100 voices; each character picks one. If the model is missing, the browser's own speech is used instead.
- **2D characters:** pixi-live2d-display (MIT) with Live2D's Cubism Core runtime. That runtime is free for individuals and small businesses; larger companies need a Live2D release license. Art credits are in [`app/frontend/assets/CREDITS.md`](app/frontend/assets/CREDITS.md).
- **KRINO Evaluator:** the evaluator now runs only as the internal interaction policy. It is rule-based by default. `KRINO_POLICY=matrix` runs the 3-Head Matrix model, which is labelled experimental because it wasn't trained on interaction behaviour. Hard constraints are enforced in code.

Architecture and data model: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Layout

`app/` holds backend, frontend and e2e. `data/` is local only: the database, downloaded models and datasets. `model/` and `krino/` contain the Matrix model. `scripts/`, `docs/`, and `archive/` hold scripts, documentation, and the retired decision-navigation app.

## License

[Apache License 2.0](LICENSE). Third-party components:
- PixiJS and pixi-live2d-display: MIT.
- Live2D Cubism Core: proprietary, redistributable.
- Kokoro: Apache-2.0.
- Whale Girl portrait: CC0, as marked by the uploader.
