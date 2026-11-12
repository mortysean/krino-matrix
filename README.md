# KRINO WORLD

**English** | [简体中文](README.zh-CN.md)

KRINO WORLD is the KRINO MATRIX platform for ACG-style AI characters. You chat by text and voice with characters that remember you, and you can create, import, or adopt characters from the workshop. The default character is **大肥鱼** ("Big Fat Fish"), the rice-loving, overthinking "big blue fat fish" from the Chinese internet's DeepSeek fan persona. Every character is labelled as an AI.

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

- **Voice:** for local development, speech is synthesized with [Kokoro-82M Chinese](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh) (Apache-2.0). It's free, offline, and has 100 voices; each character picks one. The production servers use the self-hosted voice service (`TTS_PROVIDER=qwen`). When it fails, the page shows the error instead of falling back to the browser's voice.
- **2D characters:** pixi-live2d-display (MIT) with Live2D's Cubism Core runtime. That runtime is free for individuals and small businesses; larger companies need a Live2D release license. Art credits are in [`app/frontend/assets/CREDITS.md`](app/frontend/assets/CREDITS.md).
- **KRINO Evaluator:** the evaluator now runs only as the internal interaction policy. It is rule-based by default. `KRINO_POLICY=matrix` runs the 3-Head Matrix model, which is labelled experimental because it wasn't trained on interaction behaviour. Hard constraints are enforced in code. The weights are open source on [Hugging Face](https://huggingface.co/yuxiaohuang2004/krino_matrix) (`matrix-mmbert/`, the same as the local `model/checkpoints/mmbert-uncertainty`).

Architecture and data model: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Website and deployment

The company site [krinomatrix.com](https://krinomatrix.com) is generated from `app/landing_src/` (`python app/landing_src/build.py`). It has a mainland China site `/cn/` and an international site `/global/`, and the app runs under each at `/<region>/products/world/`. The two regions are separate deployments: `/cn/` is served from the Hangzhou server and `/global/` from the Tokyo server. `scripts/deploy.sh cn|global user@host [caddy]` deploys one of them; see [docs/DEPLOY.md](docs/DEPLOY.md). Site-only changes have to be deployed to both servers.

## Repositories

| Repository | Contents |
| --- | --- |
| [krino-matrix-private](https://github.com/mortysean/krino-matrix-private) (remote `private`) | All of the code: this repository |
| [krino-matrix](https://github.com/mortysean/krino-matrix) (remote `origin`) | The public part: client SDK, API docs, inference framework of the Matrix model |

The public repository is assembled by `scripts/publish_public.sh`; don't edit it directly. Its README and requirements are in `public/`. To update it, commit here first, then run `scripts/publish_public.sh` to preview the change and `scripts/publish_public.sh --push` to publish. The script scans for keys before it pushes. Secrets (`.env*`, keys, server passwords) never go into either repository.

## Layout

`app/` holds backend, frontend, e2e and the website (`landing_src/` is the source, `landing/` the generated pages). `sdk/python/` is the KRINO WORLD Python client and `docs/api/` the API guide and OpenAPI schema. `data/` is local only: the database, downloaded models and datasets. `model/` and `krino/` contain the Matrix model. `scripts/`, `docs/`, and `archive/` hold scripts, documentation, and the retired decision-navigation app.

## License

[Apache License 2.0](LICENSE). Third-party components:
- PixiJS and pixi-live2d-display: MIT.
- Live2D Cubism Core: proprietary, redistributable.
- Kokoro: Apache-2.0.
- 大肥鱼 portrait: CC0, as marked by the uploader.
