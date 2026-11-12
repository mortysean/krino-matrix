# krino-world（Python）

[English](README.md) | **简体中文**

[KRINO WORLD 接口](../../docs/api/README.zh-CN.md)的 Python 客户端。需要 Python 3.10+，唯一的依赖是 `httpx`。

```bash
pip install "git+https://github.com/mortysean/krino-matrix#subdirectory=sdk/python"
```

## 用法

```python
from krino_world import Client, KrinoError

with Client(region="cn") as kw:               # 国际站用 "global"
    kw.login("me", "secret")                  # 或 kw.register(...)；token 会存在客户端里
    character = kw.characters()[0]
    session = kw.start_session(character["id"])
    print(session["greeting"])

    # 等整句回复
    turn = kw.send(session["id"], "今天过得怎么样？")
    print(turn["reply"]["content"])

    # 流式回复
    for event in kw.stream(session["id"], "讲个故事吧"):
        if event.name == "delta":
            print(event.data["text"], end="", flush=True)
        elif event.name == "error":
            print("\n", event.data["message"])

    # 记忆
    kw.remember(character["id"], "我喜欢吃白饭", type="preference")
    for m in kw.memories(character["id"]):
        print(m["content"], m["reality"])

    # 语音
    audio, mime = kw.speak("晚安")
```

| | |
| --- | --- |
| 账号 | `register`、`login`、`logout`、`me`、`health` |
| 角色 | `characters`、`character`、`export_character` |
| 对话 | `sessions`、`start_session`、`session`、`send`、`stream`、`gesture`、`end_session`、`delete_session` |
| 记忆 | `memories`、`remember`、`edit_memory`、`forget`、`restore`、`delete_memory` |
| 语音 | `speak` |
| 其他接口 | `request(method, path, **httpx 参数)` 可以调用 `/api/` 下的任何接口 |

- 连自己的服务器：`Client(base_url="http://127.0.0.1:8630")`。
- 复用已有的 token：`Client(region="cn", token="…")`。
- 请求被拒绝时抛出 `KrinoError`：`.status` 是 HTTP 状态码，`.message` 是服务器给的说明。
- 两个地区的账号互不相通，见[地址](../../docs/api/README.zh-CN.md#地址)。
