# krino-world (Python)

**English** | [简体中文](https://github.com/mortysean/krino-matrix/blob/main/sdk/python/README.zh-CN.md)

A Python client for the [KRINO WORLD API](https://github.com/mortysean/krino-matrix/blob/main/docs/api/README.md). It needs Python 3.10+ and its only dependency is `httpx`.

```bash
pip install krino-world
```

Full reference and quick start: [krinomatrix.com/global/developers](https://krinomatrix.com/global/developers/) ([mainland China site](https://krinomatrix.com/cn/developers/)).

## API key

Sign in to KRINO WORLD and create a key under **Settings → API keys**. It starts with `km_`, is shown only once, and stays valid until you delete it. Keep it like a password; the easiest place is an environment variable:

```bash
export KRINO_API_KEY=km_...
```

## Usage

```python
from krino_world import Client, KrinoError

with Client(region="global") as kw:          # reads KRINO_API_KEY; "cn" for the mainland China site
    character = kw.characters()[0]
    session = kw.start_session(character["id"])
    print(session["greeting"])

    # Whole reply
    turn = kw.send(session["id"], "How was your day?")
    print(turn["reply"]["content"])

    # Streamed reply
    for event in kw.stream(session["id"], "Tell me a story"):
        if event.name == "delta":
            print(event.data["text"], end="", flush=True)
        elif event.name == "error":
            print("\n", event.data["message"])

    # Memories
    kw.remember(character["id"], "I like plain rice", type="preference")
    for m in kw.memories(character["id"]):
        print(m["content"], m["reality"])

    # Speech
    audio, mime = kw.speak("Good night")
```

| | |
| --- | --- |
| Account | `register`, `login`, `logout`, `me`, `health` |
| Characters | `characters`, `character`, `export_character` |
| Chat | `sessions`, `start_session`, `session`, `send`, `stream`, `gesture`, `end_session`, `delete_session` |
| Memory | `memories`, `remember`, `edit_memory`, `forget`, `restore`, `delete_memory` |
| Voice | `speak` |
| Anything else | `request(method, path, **httpx_kwargs)` calls any endpoint under `/api/` |

- Your own server: `Client(base_url="http://127.0.0.1:8630")`.
- Pass the key directly: `Client(region="cn", api_key="km_…")`.
- No key? `kw.login("me", "secret")` signs in with a password instead; that token expires after a week.
- A refused request raises `KrinoError`, with `.status` (the HTTP status) and `.message` (the server's explanation).
- The two regions have separate accounts. See [Base URLs](https://github.com/mortysean/krino-matrix/blob/main/docs/api/README.md#base-urls).
