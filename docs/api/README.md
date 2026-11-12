# KRINO WORLD API

**English** | [简体中文](README.zh-CN.md)

The HTTP API behind the KRINO WORLD app. The web app uses the same endpoints, so anything it does you can do too. Every endpoint, with its request and response schema, is in [`openapi.json`](openapi.json) (OpenAPI 3.1). This page covers what the schema can't: where to connect, how to sign in, how streaming works, and what errors mean.

The quickest way in is the Python client in [`sdk/python`](../../sdk/python).

## Base URLs

| Region | App | API |
| --- | --- | --- |
| Mainland China | `https://krinomatrix.com/cn/products/world/` | `https://krinomatrix.com/cn/products/world/api/` |
| International | `https://krinomatrix.com/global/products/world/` | `https://krinomatrix.com/global/products/world/api/` |

The two regions are **separate deployments** with their own servers, databases and accounts. User data never crosses between them, so an account made in one region does not exist in the other.

A server you run yourself serves the API at `http://<host>:8630/api/`.

## Authentication

Register or log in, then send the token as a Bearer header on every other request.

```bash
API=https://krinomatrix.com/global/products/world/api
curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"username": "me", "password": "secret"}'
# → {"token": "…", "user": {"id": "…", "username": "me", "display_name": "…", "settings": {…}}}

curl -s $API/characters -H "Authorization: Bearer $TOKEN"
```

| Endpoint | |
| --- | --- |
| `POST /auth/register` | `username`, `password` (6–128 characters), optional `display_name` → `token`, `user` |
| `POST /auth/login` | `username`, `password` → `token`, `user` |
| `POST /auth/logout` | Revokes the token |
| `GET /me` · `PATCH /me` | Your account and settings |
| `DELETE /me` | Deletes the account and everything in it. Body: `{"password": "…"}` |

Tokens expire after a while. When one does, requests return `401` and you need to log in again.

## Talking to a character

1. `GET /characters` lists your characters. A new account already has the official default character.
2. `POST /sessions` with `{"character_id": "…"}` starts a conversation. The response includes the character's `greeting`.
3. Send turns, either all at once or streamed:

| Endpoint | Body | Response |
| --- | --- | --- |
| `POST /sessions/{id}/messages` | `text`, optional `image` (data URL), `source` (`app` / `voice` / `glasses`) | One JSON object: `reply`, `user`, `actions`, `decision`, `memory_job` |
| `POST /sessions/{id}/stream` | Same, plus optional `audio` (`data:audio/wav;base64,…`, which the character hears directly) | `text/event-stream` |
| `POST /sessions/{id}/events` | `type`: `gesture` (with `gesture`), `idle`, or `perception` (with `image`) | Same as `/messages` |
| `POST /sessions/{id}/end` | — | The session plus a short `summary` |

### Streaming

`/stream` sends [server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html) in this order:

```
event: decision
data: {"actions": ["RESPOND"], "policy": "rules", "label": "…"}

event: delta
data: {"text": "Hi"}

event: delta
data: {"text": " there!"}

event: done
data: {"reply": {…}, "user": {…}, "actions": […], "decision": {…}, "memory_job": "…"}
```

- `decision` comes first. It says what the interaction policy chose for this turn, such as replying, staying quiet, or making a gesture.
- `delta` events carry the reply in pieces. Join their `text` fields to get the whole reply.
- `done` carries the same object `/messages` returns.
- `error` (`{"message": "…"}`) can replace `done` if generation fails partway through.

A reverse proxy in front of the API must turn off response buffering for this endpoint.

## Memory

A character remembers what matters about you. You can see, correct and remove all of it.

| Endpoint | |
| --- | --- |
| `GET /memories?character_id=…` | Optional `status` (`active` by default), `type`, `q` (search) |
| `POST /memories` | `character_id`, `content`, `type` (`fact` / `preference` / `event` / `commitment`), `reality` (`real` for things that happened, `story` for shared fiction), `importance` 1–5, `pinned`, `sensitive` |
| `PATCH /memories/{id}` | Change any of those fields |
| `POST /memories/{id}/forget` · `/restore` | Forget a memory and bring it back |
| `DELETE /memories/{id}` | Delete permanently |
| `GET /memories/candidates?character_id=…` | Things the character proposes to remember, waiting for you to confirm |
| `POST /memories/candidates/{id}/accept` · `DELETE /memories/candidates/{id}` | Accept or reject a proposal |
| `GET /memory-jobs/{id}?wait=…` | The background memory update a turn started (`memory_job` in the turn result) |
| `GET /relations/{character_id}/export` · `POST …/import` | Move a character's whole relationship with you: memories and bond |

## Voice and vision

| Endpoint | |
| --- | --- |
| `POST /voice/tts` | `text`, optional `voice`, `rate` (0.5–2.0) → audio bytes. Check the `Content-Type` to see the format |
| `POST /voice/stt` | Speech recognition, for servers that have it enabled |
| `GET /voice/config` | Which speech services this server offers |
| `POST /vision/describe` | `image` (data URL), optional `question` |

## Everything else

`openapi.json` also covers the character editor and versions (`/characters/*`), character import and export as `krino-persona/1` packages, the workshop (`/workshop/*`), the social circle (`/social/*`), the KRINO GLASSES device bridge (`/devices/*`, including the WebSocket `/devices/ws`), credits (`/credits`) and service status (`/health`, `/status`, `/services`).

## Errors

Errors are JSON in the form `{"detail": "…"}`. The message is written for people and is in the region's language.

| Status | Meaning |
| --- | --- |
| `400` | The request is incomplete, for example an empty message |
| `401` | Missing or expired token |
| `404` | The thing doesn't exist, or it isn't yours |
| `409` | The session belongs to a different character than the one you named |
| `422` | The body doesn't match the schema |
| `429` | Today's credits are used up |
| `502` / `503` | A model or voice service upstream failed. Retrying usually works |

## Regenerating the schema

`openapi.json` is exported from the backend. To regenerate it, run a server and save `http://127.0.0.1:8630/openapi.json` over this file.
