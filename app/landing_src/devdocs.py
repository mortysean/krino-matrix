"""开发者中心：/<地区>/developers/（概览 + 快速开始）、developers/api/（API 参考）、developers/sdk/（Python SDK）。build.py 调用。

照交易所 API 文档的样子做：左边一栏目录，右边一个接口一节（方法、路径、参数表、请求示例、返回示例）。
- 接口列表、标题、说明、示例在这个文件里写（ENDPOINTS、EXAMPLES）；参数的名字、类型、必填、默认值、取值范围从
  docs/api/openapi.json 读，所以后端改了参数，重新导出 openapi.json 再重跑 build.py 就跟上了。
- SDK 的方法签名从 sdk/python/krino_world/client.py 读，说明写在 SDK_DOC 里。
- validate() 检查：列出来的接口在 openapi.json 里都还在、每个参数都有说明、SDK 每个公开方法都有说明。对不上就报错，不让文档悄悄过时。
页面上的文字都是（中文, 英文）一对，按地区的语言取。
"""
import ast
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OPENAPI = ROOT / "docs/api/openapi.json"
CLIENT = ROOT / "sdk/python/krino_world/client.py"
PYPROJECT = ROOT / "sdk/python/pyproject.toml"
GITHUB = "https://github.com/mortysean/krino-matrix"
PYPI = "https://pypi.org/project/krino-world/"
OPENAPI_PUBLISHED = "assets/krino-world-openapi.json"  # build.py 拷到站点根目录下的这个位置
esc = html.escape


def tr(x, zh):
    return (x[0] if zh else x[1]) if isinstance(x, tuple) else x


# ---------------------------------------------------------------- 代码块（生成时上色，不用第三方库）
_PY = re.compile(r"(?P<c>#[^\n]*)|(?P<s>f?\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*')|(?P<n>\b\d+(?:\.\d+)?\b)"
                 r"|(?P<k>\b(?:from|import|with|as|for|in|if|elif|else|try|except|def|return|print|True|False|None|curl|pip|jq)\b)")
_JSON = re.compile(r"(?P<k>\"(?:\\.|[^\"\\])*\"(?=\s*:))|(?P<s>\"(?:\\.|[^\"\\])*\")|(?P<n>-?\b\d+(?:\.\d+)?\b)|(?P<b>\b(?:true|false|null)\b)")
_SSE = re.compile(r"(?P<k>^event:[^\n]*)", re.M)
LANG_LABEL = {"python": "Python", "bash": "Shell", "json": "JSON", "sse": "text/event-stream"}


def hl(code, lang):
    rx = {"python": _PY, "bash": _PY, "json": _JSON, "sse": _SSE}[lang]
    out, i = [], 0
    for m in rx.finditer(code):
        out.append(esc(code[i:m.start()]))
        out.append(f'<span class="t-{m.lastgroup}">{esc(m.group())}</span>')
        i = m.end()
    out.append(esc(code[i:]))
    return "".join(out)


def code(src, lang, zh, label=None):
    src = src.strip("\n")
    copy, done = ("复制", "已复制") if zh else ("Copy", "Copied")
    return (f'<div class="code"><div class="code-h"><span>{esc(label or LANG_LABEL[lang])}</span>'
            f'<button type="button" class="copy" data-done="{done}">{copy}</button></div>'
            f'<pre><code>{hl(src, lang)}</code></pre></div>')


def tabs(items, zh):
    """几种写法切换（Python / cURL）。选了哪种整页一起切，下次打开还记得（portal.js）。"""
    heads = "".join(f'<button type="button" role="tab" data-tab="{k}" aria-selected="{str(i == 0).lower()}">{esc(label)}</button>'
                    for i, (k, label, _, _) in enumerate(items))
    bodies = "".join(f'<div role="tabpanel" data-tab="{k}"{"" if i == 0 else " hidden"}>{code(src, lang, zh, label)}</div>'
                     for i, (k, label, src, lang) in enumerate(items))
    return f'<div class="tabs"><div class="tab-h" role="tablist">{heads}</div>{bodies}</div>'


def table(head, rows, cls=""):
    th = "".join(f"<th>{h}</th>" for h in head)
    tb = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="table-wrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


# ---------------------------------------------------------------- 接口
# (方法, 路径, 标题, 说明, 返回示例的键)；路径不带 /api 前缀
ENDPOINTS = [
    ("account", ("账号", "Account"), [
        ("POST", "/auth/register", ("注册", "Register"),
         ("新建账号并直接登录。新账号自带官方角色，可以马上开始对话。", "Create an account and sign in. A new account already has the official characters, so you can start talking right away."), "auth"),
        ("POST", "/auth/login", ("登录", "Log in"), ("用户名和密码换一个登录 token（一周后过期），用法和 API 密钥一样。写程序推荐直接用 <a href=\"#auth\">API 密钥</a>。",
                                                    "Trade a username and password for a login token (expires after a week), used like an API key. For programs, an <a href=\"#auth\">API key</a> is simpler."), "auth"),
        ("POST", "/auth/logout", ("退出登录", "Log out"), ("让当前 token 失效。", "Revoke the current token."), "ok"),
        ("GET", "/me", ("账号信息", "Your account"), ("账号和设置。", "Your account and settings."), "me"),
        ("PATCH", "/me", ("修改设置", "Update settings"), ("只传要改的字段。设置分组的结构和 <code>GET /me</code> 返回的 <code>settings</code> 一样，组内也只需传要改的项。",
                                                        "Send only the fields you change. Each settings group has the shape you see in <code>settings</code> from <code>GET /me</code>, and within a group you also send only what changes."), "me"),
        ("DELETE", "/me", ("注销账号", "Delete account"), ("删除账号和里面的一切：角色、记忆、聊天、关系。不能恢复。", "Delete the account and everything in it: characters, memories, chats and relationships. This can't be undone."), "ok"),
    ]),
    ("characters", ("角色", "Characters"), [
        ("GET", "/characters", ("角色列表", "List characters"), ("你的角色，新的在前。", "Your characters, newest first."), "characters"),
        ("GET", "/characters/{cid}", ("角色详情", "Get a character"), ("一个角色的完整资料，包括开场白和声音设置。", "One character in full, including its greeting and voice settings."), "character"),
        ("GET", "/characters/{cid}/export", ("导出角色", "Export a character"),
         ("把角色导出成 <code>krino-persona/1</code> 角色包（可以在别处导入）。只含人设，不含你们之间的记忆，那部分用“导出关系”。",
          "The character as a <code>krino-persona/1</code> package you can import elsewhere. It holds the persona only; your memories with it are under “Export relationship”."), "export"),
    ]),
    ("chat", ("对话", "Chat"), [
        ("POST", "/sessions", ("开始对话", "Start a session"), ("开一段新对话，返回里带着角色的开场白 <code>greeting</code>。", "Start a new conversation. The response carries the character's <code>greeting</code>."), "session"),
        ("GET", "/sessions", ("对话列表", "List sessions"), ("和这个角色的所有对话，新的在前。", "Your conversations with this character, newest first."), "sessions"),
        ("GET", "/sessions/{sid}", ("对话详情", "Get a session"), ("一段对话和它的全部消息。", "A conversation with all its messages."), "session_full"),
        ("POST", "/sessions/{sid}/messages", ("发消息", "Send a message"),
         ("说一句话，等角色的完整回复。要边生成边显示用下面的流式接口。", "Say something and wait for the whole reply. To show the reply as it's written, use the streaming endpoint below."), "turn"),
        ("POST", "/sessions/{sid}/stream", ("发消息（流式）", "Send a message (streamed)"),
         ("同上，但回复以 <a href=\"#streaming\">server-sent events</a> 一段段返回。可以带一段录音 <code>audio</code>，角色直接听。",
          "The same, but the reply arrives piece by piece as <a href=\"#streaming\">server-sent events</a>. You can attach a recording as <code>audio</code> and the character hears it directly."), "stream"),
        ("POST", "/sessions/{sid}/events", ("互动事件", "Send an event"),
         ("不说话的互动：做手势（挥手、摸头……）、你走开了一会儿、或者给角色看一眼画面。角色自己决定要不要回应。返回和发消息一样。",
          "Interactions without words: a gesture (wave, pat…), you being idle for a while, or showing the character an image. The character decides whether to respond. Returns the same as sending a message."), "turn"),
        ("POST", "/sessions/{sid}/end", ("结束对话", "End a session"), ("结束对话，角色会给这段对话写一份小结。", "Close the conversation. The character writes a short summary of it."), "end"),
        ("DELETE", "/sessions/{sid}", ("删除对话", "Delete a session"), ("删除对话和里面的消息。", "Delete the conversation and its messages."), "ok"),
    ]),
    ("memory", ("记忆", "Memory"), [
        ("GET", "/memories", ("记忆列表", "List memories"), ("角色记得的关于你的事。<code>reality</code> 是 <code>real</code>（真实发生的）或 <code>story</code>（一起编的故事）。",
                                                          "What the character remembers about you. <code>reality</code> is <code>real</code> (it happened) or <code>story</code> (shared fiction)."), "memories"),
        ("POST", "/memories", ("添加记忆", "Add a memory"), ("自己告诉角色一件事，让它记住。", "Tell the character something to remember."), "memory"),
        ("PATCH", "/memories/{mid}", ("修改记忆", "Edit a memory"), ("改正记错的地方。只传要改的字段。", "Correct what it got wrong. Send only the fields you change."), "memory"),
        ("POST", "/memories/{mid}/forget", ("忘掉", "Forget"), ("让角色不再想起这条记忆。可以用 <code>/restore</code> 找回。", "The character stops recalling this memory. <code>/restore</code> brings it back."), "memory_forgotten"),
        ("POST", "/memories/{mid}/restore", ("找回", "Restore"), ("找回忘掉的记忆。", "Bring a forgotten memory back."), "memory"),
        ("DELETE", "/memories/{mid}", ("彻底删除", "Delete permanently"), ("彻底删除这条记忆，不能恢复。", "Delete the memory for good."), "removed"),
        ("GET", "/memories/candidates", ("待确认的记忆", "Proposed memories"), ("角色从对话里提出想记住、但要你确认的事。", "Things the character proposes to remember from your conversations, waiting for you to confirm."), "candidates"),
        ("POST", "/memories/candidates/{cand_id}/accept", ("确认", "Accept"), ("确认记住。可以顺手改写内容。", "Accept the proposal, optionally rewording it."), "memory"),
        ("DELETE", "/memories/candidates/{cand_id}", ("拒绝", "Reject"), ("不记这件事。", "Don't remember it."), "ok"),
        ("GET", "/memory-jobs/{job_id}", ("记忆整理进度", "Memory job"),
         ("每轮对话后角色会在后台整理记忆，发消息的返回里有任务 id <code>memory_job</code>。<code>wait</code> 秒内完成就直接返回结果。",
          "After each turn the character updates its memories in the background; the turn result carries the job id as <code>memory_job</code>. With <code>wait</code>, the call returns as soon as the job finishes, waiting at most that many seconds."), "job"),
        ("GET", "/relations/{cid}/export", ("导出关系", "Export relationship"), ("你和这个角色之间的私人数据：记忆和关系进度，可选带上聊天记录。", "Your private data with this character: memories and relationship progress, optionally with chats."), "relation"),
        ("POST", "/relations/{cid}/import", ("导入关系", "Import relationship"), ("把导出的关系导进来（比如换了角色或换了账号）。重复的记忆会跳过。", "Import an exported relationship, for example into another account. Duplicate memories are skipped."), "relation_import"),
    ]),
    ("voice", ("语音与视觉", "Voice & vision"), [
        ("POST", "/voice/tts", ("语音合成", "Text to speech"),
         ("把文字读出来，返回音频本身（不是 JSON）。看 <code>Content-Type</code> 判断格式。",
          "Speak text aloud. The response is the audio itself, not JSON; check <code>Content-Type</code> for the format."), "tts"),
        ("POST", "/voice/stt", ("语音识别", "Speech to text"), ("上传一段录音（<code>multipart/form-data</code>），返回识别出的文字。", "Upload a recording as <code>multipart/form-data</code> and get the text back."), "stt"),
        ("GET", "/voice/config", ("语音服务", "Voice services"), ("这台服务器提供哪些语音和视觉服务、有哪些声音可选。", "Which voice and vision services this server offers, and the voices to choose from."), "voice_config"),
        ("POST", "/vision/describe", ("看图", "Describe an image"), ("让模型描述一张图，或回答关于它的问题。", "Have the model describe an image or answer a question about it."), "vision"),
    ]),
    ("status", ("服务状态", "Status"), [
        ("GET", "/health", ("健康检查", "Health"), ("服务是否在线。不用登录。", "Whether the service is up. No sign-in needed."), "health"),
        ("GET", "/credits", ("今日额度", "Today's credits"), ("今天的额度和已用量。用完后接口返回 429，第二天恢复。", "Today's credit limit and usage. When it runs out the API returns 429 until the next day."), "credits"),
    ]),
]

# 参数说明：先找 “方法 路径:参数名”，再找参数名
P = {
    "username": ("用户名", "Username"),
    "password": ("密码", "Password"),
    "display_name": ("显示的名字，不填就用用户名", "The name shown to characters; defaults to the username"),
    "DELETE /me:password": ("当前密码，确认是你本人", "Your current password, to confirm it's you"),
    "save_sensitive": ("允许角色记住敏感信息（健康、财务等）", "Let characters remember sensitive things (health, money…)"),
    "privacy": ("隐私：<code>camera</code>、<code>microphone</code>", "Privacy: <code>camera</code>, <code>microphone</code>"),
    "voice": ("语音：<code>stt</code>、<code>tts</code>、<code>autoplay</code>、<code>voice</code>", "Voice: <code>stt</code>, <code>tts</code>, <code>autoplay</code>, <code>voice</code>"),
    "interaction": ("互动：<code>proactive</code>（角色主动搭话）、<code>idle_seconds</code>、<code>stories</code>、<code>web</code> 等", "Interaction: <code>proactive</code> (characters start talking), <code>idle_seconds</code>, <code>stories</code>, <code>web</code> and more"),
    "evaluator": ("互动策略：<code>mode</code>", "Interaction policy: <code>mode</code>"),
    "social": ("社交圈：<code>autonomy</code>、<code>share_life</code>", "Social circle: <code>autonomy</code>, <code>share_life</code>"),
    "cid": ("角色 id", "Character id"),
    "sid": ("对话 id", "Session id"),
    "mid": ("记忆 id", "Memory id"),
    "cand_id": ("待确认记忆的 id", "Proposal id"),
    "job_id": ("任务 id（发消息返回的 <code>memory_job</code>）", "Job id (<code>memory_job</code> from a turn)"),
    "character_id": ("角色 id", "Character id"),
    "GET /characters/{cid}/export:format": ("<code>json</code>：角色包；<code>md</code>：可读的 Markdown", "<code>json</code> for the package, <code>md</code> for readable Markdown"),
    "text": ("你说的话", "What you say"),
    "image": ("一张图片，data URL（<code>data:image/jpeg;base64,…</code>）", "An image as a data URL (<code>data:image/jpeg;base64,…</code>)"),
    "audio": ("一段录音，data URL（<code>data:audio/wav;base64,…</code>），角色直接听；只有流式接口用", "A recording as a data URL (<code>data:audio/wav;base64,…</code>) that the character hears directly; streaming only"),
    "source": ("从哪发来的：<code>app</code>、<code>voice</code>（语音对话）、<code>glasses</code>（眼镜）", "Where it came from: <code>app</code>, <code>voice</code> (voice chat), <code>glasses</code>"),
    "POST /sessions/{sid}/messages:character_id": ("可选：校验对话属于这个角色，不是就返回 409", "Optional: check the session belongs to this character, 409 if not"),
    "POST /sessions/{sid}/stream:character_id": ("可选：校验对话属于这个角色，不是就返回 409", "Optional: check the session belongs to this character, 409 if not"),
    "POST /sessions/{sid}/events:character_id": ("可选：校验对话属于这个角色，不是就返回 409", "Optional: check the session belongs to this character, 409 if not"),
    "type": ("<code>gesture</code>（手势）、<code>idle</code>（你走开了）、<code>perception</code>（给角色看画面）", "<code>gesture</code>, <code>idle</code> (you've been away) or <code>perception</code> (show the character an image)"),
    "gesture": ("手势名，比如 <code>wave</code>、<code>pat</code>", "The gesture, such as <code>wave</code> or <code>pat</code>"),
    "idle_count": ("连续第几次空闲", "How many idle events in a row"),
    "POST /sessions/{sid}/events:text": ("附带的一句话（可选）", "An optional line to go with it"),
    "GET /memories:status": ("<code>active</code>（在用的）、<code>forgotten</code>（忘掉的）", "<code>active</code> or <code>forgotten</code>"),
    "GET /memories:type": ("按类型筛选", "Filter by type"),
    "q": ("搜索内容", "Search text"),
    "content": ("记忆内容", "What to remember"),
    "POST /memories/candidates/{cand_id}/accept:content": ("改写后的内容（可选）", "Reworded content (optional)"),
    "POST /memories:type": ("<code>fact</code> 事实、<code>preference</code> 偏好、<code>event</code> 事件、<code>commitment</code> 约定", "<code>fact</code>, <code>preference</code>, <code>event</code> or <code>commitment</code>"),
    "PATCH /memories/{mid}:type": ("<code>fact</code>、<code>preference</code>、<code>event</code>、<code>commitment</code>", "<code>fact</code>, <code>preference</code>, <code>event</code> or <code>commitment</code>"),
    "reality": ("<code>real</code> 真实发生的、<code>story</code> 一起编的故事", "<code>real</code> (it happened) or <code>story</code> (shared fiction)"),
    "title": ("短标题，不填就从内容截取", "A short title; taken from the content if omitted"),
    "importance": ("重要程度 1–5", "Importance, 1–5"),
    "pinned": ("置顶：每次对话都想得起来", "Pinned: always recalled"),
    "sensitive": ("敏感信息", "Sensitive"),
    "source_message_id": ("出自哪条消息（消息的 <code>id</code>）", "The message it came from (its <code>id</code>)"),
    "wait": ("最多等几秒（最多 15）", "Seconds to wait for it to finish, up to 15"),
    "chats": ("同时导出聊天记录", "Include chats"),
    "data": ("“导出关系”返回的整个对象", "The whole object from “Export relationship”"),
    "POST /voice/tts:text": ("要读的文字", "The text to speak"),
    "POST /voice/tts:voice": ("声音 id，可选值见 <code>GET /voice/config</code>；不填用默认", "A voice id from <code>GET /voice/config</code>; the default if omitted"),
    "rate": ("语速 0.5–2.0", "Speed, 0.5–2.0"),
    "style": ("声音描述（一句话生成的角色才有）", "A voice description (characters designed from a sentence)"),
    "stream": ("边合成边返回 16-bit PCM（24 kHz 单声道），第一段声音零点几秒就到", "Stream 16-bit PCM (24 kHz mono) as it's synthesized; the first audio arrives in a fraction of a second"),
    "opus_stream": ("流式时也压成 Ogg Opus（浏览器用 WebCodecs 边收边解）", "With stream, send Ogg Opus instead of PCM (decode with WebCodecs)"),
    "opus_file": ("整句返回 Ogg Opus 而不是 WAV，小很多", "Return Ogg Opus instead of WAV for the whole clip; much smaller"),
    "file": ("录音文件：webm、ogg、mp4、wav 等", "The recording: webm, ogg, mp4, wav…"),
    "POST /vision/describe:image": ("图片，data URL", "The image as a data URL"),
    "question": ("想问的问题（可选）", "A question about it (optional)"),
}
SKIP = {"POST /auth/login:display_name"}  # 模型里有、但这个接口用不上的字段
VARS = {"cid": "CHARACTER_ID", "character_id": "CHARACTER_ID", "sid": "SESSION_ID", "mid": "MEMORY_ID", "cand_id": "CANDIDATE_ID", "job_id": "JOB_ID"}

# 请求体示例（curl 用）
REQ = {
    "POST /auth/register": {"username": "me", "password": "your-password"},
    "POST /auth/login": {"username": "me", "password": "your-password"},
    "PATCH /me": {"display_name": "Mika", "voice": {"autoplay": False}},
    "DELETE /me": {"password": "your-password"},
    "POST /sessions": {"character_id": "$CHARACTER_ID"},
    "POST /sessions/{sid}/messages": {"text": ("今天过得怎么样？", "How was your day?")},
    "POST /sessions/{sid}/stream": {"text": ("讲个故事吧", "Tell me a story")},
    "POST /sessions/{sid}/events": {"type": "gesture", "gesture": "wave"},
    "POST /memories": {"character_id": "$CHARACTER_ID", "content": ("我喜欢吃白米饭", "I like plain rice"), "type": "preference"},
    "PATCH /memories/{mid}": {"importance": 5, "pinned": True},
    "POST /memories/candidates/{cand_id}/accept": {},
    "POST /relations/{cid}/import": {"data": "…"},
    "POST /voice/tts": {"text": ("晚安", "Good night"), "opus_file": True},
    "POST /vision/describe": {"image": "data:image/jpeg;base64,…", "question": ("这是什么？", "What is this?")},
}
QUERY = {"GET /memory-jobs/{job_id}": "wait=5", "GET /relations/{cid}/export": "chats=true"}

ID_C, ID_S, ID_M = "c54631270dbe4ae9b7fb44ff27d5ae2c", "2f549fa0f5f240a8b7e979c12c275312", "806576307f4a428d871dceee6921f2cd"
SETTINGS = """{
      "save_sensitive": false,
      "privacy": {"camera": false, "microphone": false},
      "voice": {"stt": "auto", "tts": "auto", "autoplay": true, "voice": ""},
      "interaction": {"proactive": true, "idle_seconds": 45, "animations": true, "stories": true, "web": true},
      "evaluator": {"mode": null},
      "social": {"autonomy": true, "share_life": true}
    }"""
MEMORY = """{
  "id": "%s",
  "character_id": "%s",
  "type": "preference",
  "title": "%s",
  "content": "%s",
  "origin": "manual",
  "reality": "real",
  "status": "%s",
  "status_reason": %s,
  "importance": 3,
  "pinned": false,
  "sensitive": false,
  "created_at": "2026-11-13T14:34:05+00:00",
  "updated_at": "2026-11-13T14:34:05+00:00",
  …
}"""


def _mem(zh, status="active", reason="null"):
    t = "我喜欢吃白米饭" if zh else "I like plain rice"
    return MEMORY % (ID_M, ID_C, t, t, status, reason)


def _reply(zh):
    return "嗯，我在。今天顺利吗？" if zh else "I'm here. How did today go?"


def _greeting(zh):
    return "你来了。今天要解决什么问题？" if zh else "You're here. What are we solving today?"


# 返回示例：键 → 函数(zh) → (语言, 文本)。“…”表示省略了的字段
EXAMPLES = {
    "auth": lambda zh: ("json", """{
  "token": "2wIk7-Ecvo7oSW2Qo1IsO_Nh2S-aDo_Nxe0-bFh0HvQ",
  "user": {
    "id": "58acfe8dca7b4a02ab9cbea54767adb8",
    "username": "me",
    "display_name": "me",
    "settings": {…}
  }
}"""),
    "ok": lambda zh: ("json", '{"ok": true}'),
    "me": lambda zh: ("json", """{
  "id": "58acfe8dca7b4a02ab9cbea54767adb8",
  "username": "me",
  "display_name": "me",
  "settings": %s,
  "companion_limit": 8
}""" % SETTINGS.replace("\n  ", "\n")),
    "characters": lambda zh: ("json", """[
  {
    "id": "%s",
    "public_id": "KR-27B48Y",
    "slug": "krino",
    "name": "KRINO",
    "tagline": "%s",
    "tags": ["official", "glasses"],
    "official": true,
    "version": 1,
    "portrait": {"kind": "chibi", "src": "/static/chibi/krino/chibi.json"}
  },
  …
]""" % (ID_C, "决策矩阵的吉祥物，戴眼镜的冷静研究员" if zh else "Krino Matrix's mascot, a calm researcher with glasses")),
    "character": lambda zh: ("json", """{
  "id": "%s",
  "name": "KRINO",
  "greeting": "%s",
  "voice": {"voice": "krino", "rate": 1.0, "pitch": 0.95},
  "default_expression": "neutral",
  "portrait": {"kind": "chibi", "src": "/static/chibi/krino/chibi.json"},
  …
}""" % (ID_C, _greeting(zh))),
    "export": lambda zh: ("json", """{
  "format": "krino-persona/1",
  "id": "krino",
  "version": 1,
  "persona": {"name": "KRINO", "personality": …, "speech": …, "greeting": …, …},
  "behavior": {…},
  "lore": […]
}"""),
    "session": lambda zh: ("json", """{
  "id": "%s",
  "character_id": "%s",
  "title": null,
  "ended": false,
  "created_at": "2026-11-13T14:34:05+00:00",
  "updated_at": "2026-11-13T14:34:05+00:00",
  "greeting": "%s"
}""" % (ID_S, ID_C, _greeting(zh))),
    "sessions": lambda zh: ("json", """[
  {
    "id": "%s",
    "character_id": "%s",
    "title": "%s",
    "ended": false,
    "created_at": "2026-11-13T14:34:05+00:00",
    "updated_at": "2026-11-13T14:36:12+00:00"
  }
]""" % (ID_S, ID_C, "今天过得怎么样？" if zh else "How was your day?")),
    "session_full": lambda zh: ("json", """{
  "id": "%s",
  "character_id": "%s",
  "ended": false,
  "messages": [
    {"id": 89, "role": "user", "content": "%s", "created_at": "…"},
    {"id": 90, "role": "assistant", "content": "%s", "state": {"expression": "happy", "mood": "happy"}, "created_at": "…"}
  ],
  …
}""" % (ID_S, ID_C, "今天过得怎么样？" if zh else "How was your day?", _reply(zh))),
    "turn": lambda zh: ("json", """{
  "reply": {
    "id": 90,
    "role": "assistant",
    "content": "%s",
    "state": {"expression": "happy", "animation": null, "mood": "happy"},
    "created_at": "2026-11-13T14:34:05+00:00"
  },
  "user": {"id": 89, "role": "user", "content": "%s", …},
  "actions": [{"type": "say", "text": "%s"}],
  "decision": {"policy": "rules", "primary": {"action": "RESPOND", …}, …},
  "memory_job": "40a37bb9a38c48a580d9a67e454f49cb"
}""" % (_reply(zh), "今天过得怎么样？" if zh else "How was your day?", _reply(zh))),
    "stream": lambda zh: ("sse", """event: decision
data: {"actions": ["RESPOND"], "policy": "rules"}

event: delta
data: {"text": "%s"}

event: delta
data: {"text": "%s"}

event: done
data: {"reply": {…}, "user": {…}, "actions": […], "decision": {…}, "memory_job": "…"}""" % (("从前，", "有一头大蓝鲸……") if zh else ("Once upon a time, ", "there was a big blue whale…"))),
    "end": lambda zh: ("json", """{
  "id": "%s",
  "character_id": "%s",
  "ended": true,
  "summary": {"id": "b6a975397f63406dbc8f63c98676a1f5", "title": "%s"},
  …
}""" % (ID_S, ID_C, "聊天 11-13 22:34：今天过得怎么样？" if zh else "Chat 11-13 22:34: How was your day?")),
    "memories": lambda zh: ("json", "[\n  " + _mem(zh).replace("\n", "\n  ") + "\n]"),
    "memory": lambda zh: ("json", _mem(zh)),
    "memory_forgotten": lambda zh: ("json", _mem(zh, "forgotten", '"%s"' % ("你说不再记住" if zh else "You asked me to forget"))),
    "removed": lambda zh: ("json", '{"ok": true, "removed": {"memories": 1, "messages": 0}}'),
    "candidates": lambda zh: ("json", """[
  {"id": "…", "character_id": "%s", "content": "%s", "type": "commitment", …}
]""" % (ID_C, "明天去跑步" if zh else "Going for a run tomorrow")),
    "job": lambda zh: ("json", """{
  "id": "40a37bb9a38c48a580d9a67e454f49cb",
  "status": "done",
  "result": {"created": [], "updated": [], "confirmed": [], "pending": [], "dropped": []},
  "error": null
}"""),
    "relation": lambda zh: ("json", """{
  "format": "krino-relation/1",
  "character": {"slug": "krino", "name": "KRINO"},
  "exported_at": "2026-11-13T14:37:20+00:00",
  "memories": […],
  "bond": {"closeness": 0.8, "stage_index": 0, "turns": 1, "days": 1, …}
}"""),
    "relation_import": lambda zh: ("json", '{"created": 12, "duplicate": 0}'),
    "tts": lambda zh: ("bash", "# %s\nContent-Type: audio/ogg   # %s" % (
        ("返回的是音频字节", "opus_file=false 时是 audio/wav") if zh else ("The body is the audio bytes", "audio/wav when opus_file is false"))),
    "stt": lambda zh: ("json", '{"text": "%s"}' % ("今天过得怎么样" if zh else "How was your day")),
    "voice_config": lambda zh: ("json", """{
  "stt": {"provider": "dashscope", "server": true},
  "tts": {"provider": "qwen", "server": true, "voices": […], "default": "…"},
  "vlm": {"provider": "openai", "simulated": false},
  "hear": true
}"""),
    "vision": lambda zh: ("json", '{"text": "%s"}' % ("一只蓝色的像素小鲸鱼。" if zh else "A small blue pixel-art whale.")),
    "health": lambda zh: ("json", '{"ok": true}'),
    "credits": lambda zh: ("json", '{"limit": 100.0, "spent": 12.5, "per_cny": 10.0, "image": 2.5}'),
}

ERRORS = [
    ("400", ("请求不完整，比如消息是空的", "The request is incomplete, for example an empty message")),
    ("401", ("没带密钥、密钥已删除，或登录 token 过期了", "Missing or deleted API key, or an expired login token")),
    ("403", ("API 密钥不能做这件事（管理密钥、注销账号要在网页上登录后操作）", "An API key can't do this (managing keys and deleting the account need a signed-in browser)")),
    ("404", ("不存在，或者不是你的", "It doesn't exist, or it isn't yours")),
    ("409", ("对话属于另一个角色", "The session belongs to a different character than the one you named")),
    ("413 / 415", ("上传的文件太大 / 格式不支持", "The upload is too large / in a format we don't take")),
    ("422", ("请求体和参数格式对不上，<code>detail</code> 里说明是哪个字段", "The body doesn't match the schema; <code>detail</code> says which field")),
    ("429", ("今天的额度用完了，第二天恢复", "Today's credits are used up; they reset tomorrow")),
    ("502 / 503", ("上游的模型或语音服务出错，重试一般就好", "An upstream model or voice service failed; retrying usually works")),
]


# ---------------------------------------------------------------- 从 openapi.json 读参数
def _openapi():
    return json.loads(OPENAPI.read_text(encoding="utf-8"))


def _op(spec, method, path):
    return spec["paths"].get("/api" + path, {}).get(method.lower())


def _resolve(spec, s):
    while "$ref" in s:
        s = spec["components"]["schemas"][s["$ref"].split("/")[-1]]
    return s


def _type(s):
    if "anyOf" in s:
        ts = [_type(x) for x in s["anyOf"] if x.get("type") != "null"]
        return " | ".join(ts) or "null"
    return {"string": "string", "integer": "int", "number": "number", "boolean": "bool", "object": "object", "array": "array"}.get(s.get("type"), s.get("type", "any"))


def _rules(s, zh):
    """默认值、长度、范围、可选值，写成一行短说明。"""
    parts = []
    m = re.fullmatch(r"\^\((.+)\)\$", s.get("pattern", ""))
    if m:
        parts.append(" / ".join(f"<code>{esc(x)}</code>" for x in m.group(1).split("|")))
    for a, b, unit in (("minLength", "maxLength", ("字", " chars")), ("minimum", "maximum", ("", ""))):
        lo, hi = s.get(a), s.get(b)
        if lo is not None or hi is not None:
            fmt = lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)  # noqa: E731
            u = tr(unit, zh)
            parts.append(f"{fmt(lo)}–{fmt(hi)}{u}" if lo is not None and hi is not None else (f"≤ {fmt(hi)}{u}" if hi is not None else f"≥ {fmt(lo)}{u}"))
    if "default" in s and s["default"] not in (None, ""):
        d = json.dumps(s["default"], ensure_ascii=False)
        parts.append(f"{'默认' if zh else 'default'} <code>{esc(d)}</code>")
    return "；".join(parts) if zh else "; ".join(parts)


def params(spec, method, path):
    """[(名字, 位置, 类型, 必填, 规则 schema)]：路径参数、查询参数、请求体字段。"""
    op = _op(spec, method, path)
    out = []
    for p in op.get("parameters", []):
        if p["in"] in ("path", "query"):
            out.append((p["name"], p["in"], p["schema"], p.get("required", False)))
    for ctype, c in op.get("requestBody", {}).get("content", {}).items():
        s = _resolve(spec, c["schema"])
        where = "form" if "form" in ctype else "body"
        for name, f in s.get("properties", {}).items():
            out.append((name, where, f, name in s.get("required", [])))
    return [x for x in out if f"{method} {path}:{x[0]}" not in SKIP]


def _pdoc(method, path, name):
    return P.get(f"{method} {path}:{name}") or P.get(name)


def validate():
    spec = _openapi()
    missing = []
    for _, _, eps in ENDPOINTS:
        for method, path, _, _, ex in eps:
            if not _op(spec, method, path):
                missing.append(f"openapi.json 里没有 {method} {path}")
                continue
            if ex not in EXAMPLES:
                missing.append(f"{method} {path} 的返回示例 {ex} 不存在")
            for name, *_ in params(spec, method, path):
                if not _pdoc(method, path, name):
                    missing.append(f"{method} {path} 的参数 {name} 没有说明（写进 devdocs.P）")
    methods = {m for m, _, _ in sdk_methods()}
    for m in methods - set(SDK_DOC):
        missing.append(f"SDK 方法 {m} 没有说明（写进 devdocs.SDK_DOC）")
    for m in set(SDK_DOC) - methods:
        missing.append(f"SDK_DOC 里的 {m} 在 client.py 里已经没有了")
    if missing:
        raise SystemExit("开发者文档和代码对不上：\n  " + "\n  ".join(missing))


# ---------------------------------------------------------------- SDK（从 client.py 读签名）
SDK_GROUPS = {"plumbing": ("通用请求", "Any endpoint"), "account": ("账号", "Account"), "characters": ("角色", "Characters"),
              "chat": ("对话", "Chat"), "memory": ("记忆", "Memory"), "voice": ("语音", "Voice")}
SDK_DOC = {
    "request": ("调用 <code>/api/</code> 下的任意接口（上面没有专门方法的），返回解析好的 JSON。其余参数原样交给 httpx。",
                "Call any endpoint under <code>/api/</code> that has no method of its own. Returns the decoded JSON; extra arguments go to httpx."),
    "register": ("注册并登录，token 存在客户端上。返回账号信息。", "Register and sign in; the token is kept on the client. Returns your account."),
    "login": ("用密码登录（没有 API 密钥时用），token 存在客户端上，一周后过期。返回账号信息。", "Sign in with a password when you have no API key; the token is kept on the client and expires after a week. Returns your account."),
    "logout": ("退出登录，token 失效。", "Sign out and revoke the token."),
    "me": ("账号和设置。", "Your account and settings."),
    "health": ("服务是否在线。", "Whether the service is up."),
    "characters": ("你的角色，新的在前。新账号自带官方角色。", "Your characters, newest first. A new account already has the official characters."),
    "character": ("一个角色的完整资料。", "One character in full."),
    "export_character": ("导出成 <code>krino-persona/1</code> 角色包。", "The character as a <code>krino-persona/1</code> package."),
    "sessions": ("和某个角色的所有对话。", "Your conversations with a character."),
    "start_session": ("开始新对话，返回里有开场白 <code>greeting</code>。", "Start a conversation; the result carries the <code>greeting</code>."),
    "session": ("一段对话和全部消息。", "A conversation with all its messages."),
    "send": ("说一句话，等完整回复。回复文字在 <code>turn[\"reply\"][\"content\"]</code>。", "Say something and wait for the whole reply, at <code>turn[\"reply\"][\"content\"]</code>."),
    "stream": ("说一句话，回复一段段到：逐个产出 <code>Event</code>。", "Say something and get the reply in pieces: yields <code>Event</code>s."),
    "gesture": ("做个手势（<code>wave</code>、<code>pat</code>……），角色自己决定怎么回应。", "Make a gesture (<code>wave</code>, <code>pat</code>…); the character decides how to respond."),
    "end_session": ("结束对话，角色写一份小结。", "Close the conversation; the character writes a summary."),
    "delete_session": ("删除对话。", "Delete a conversation."),
    "memories": ("角色记得的关于你的事，可按状态、类型、关键词筛选。", "What the character remembers about you, filtered by status, type or search text."),
    "remember": ("告诉角色一件事让它记住。<code>type</code>：fact / preference / event / commitment。", "Tell the character something to remember. <code>type</code>: fact, preference, event or commitment."),
    "edit_memory": ("改一条记忆，只传要改的字段。", "Change a memory; pass only the fields you change."),
    "forget": ("忘掉一条记忆，<code>restore()</code> 能找回。", "Forget a memory; <code>restore()</code> brings it back."),
    "restore": ("找回忘掉的记忆。", "Bring a forgotten memory back."),
    "delete_memory": ("彻底删除一条记忆。", "Delete a memory for good."),
    "speak": ("语音合成，返回 <code>(音频字节, 媒体类型)</code>。", "Synthesize speech: returns <code>(audio bytes, media type)</code>."),
}


def sdk_methods():
    """[(方法名, 签名, 分组)]，按 client.py 里的顺序；分组看方法前面的 “# ---- account” 这类分隔注释。"""
    src = CLIENT.read_text(encoding="utf-8")
    marks = [(i + 1, m.group(1)) for i, line in enumerate(src.splitlines()) if (m := re.match(r"\s*# -+ (\w+)", line))]
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Client")
    out = []
    for f in cls.body:
        if not isinstance(f, ast.FunctionDef) or f.name.startswith("_") or f.name in ("close",):
            continue
        group = next((g for line, g in reversed(marks) if line < f.lineno), "plumbing")
        a = f.args
        a.args = a.args[1:]  # 去掉 self
        sig = f"{f.name}({ast.unparse(a)})" + (f" -> {ast.unparse(f.returns)}" if f.returns else "")
        out.append((f.name, sig, group))
    return out


def sdk_version():
    m = re.search(r'^version\s*=\s*"([^"]+)"', PYPROJECT.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- 页面
def ep_id(method, path):
    return "ep-" + method.lower() + "-" + re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def badge(method):
    return f'<span class="m m-{method.lower()}">{method}</span>'


def sidebar(rel, zh):
    """三页共用的左侧目录。链接都写成 {base}developers/…#…，在哪一页都能点。"""
    T = lambda x: tr(x, zh)  # noqa: E731
    D = "{base}developers/"
    groups = [
        (("开始使用", "Get started"), "", [("overview", ("概览", "Overview")), ("quickstart", ("快速开始", "Quick start")), ("basics", ("基本信息", "Basics"))]),
        (("API 参考", "API reference"), "api/", [("base", ("接口地址", "Base URL")), ("auth", ("鉴权", "Authentication")),
                                                ("streaming", ("流式回复", "Streaming")), ("errors", ("错误码", "Errors"))]),
    ]
    html_ = ['<nav class="dev-side" aria-label="docs">',
             f'<button type="button" class="dev-toggle" aria-expanded="false">{T(("目录", "Contents"))}</button><div class="dev-nav">']

    def link(page, anchor, label, extra=""):
        cur = ' aria-current="page"' if page == rel and not anchor else ""
        return f'<a href="{D}{page}{"#" + anchor if anchor else ""}"{cur}>{extra}{label}</a>'

    for title, page, items in groups:
        html_.append(f'<h4><a href="{D}{page}">{T(title)}</a></h4>')
        html_.extend(link(page, a, T(lbl)) for a, lbl in items)
        if page == "api/":
            for key, gtitle, eps in ENDPOINTS:
                html_.append(f'<h5><a href="{D}api/#g-{key}">{T(gtitle)}</a></h5>')
                html_.extend(link("api/", ep_id(m, p), esc(T(t)), badge(m)) for m, p, t, _, _ in eps)
    html_.append(f'<h4><a href="{D}sdk/">{T(("Python SDK", "Python SDK"))}</a></h4>')
    html_.extend(link("sdk/", a, T(lbl)) for a, lbl in [("install", ("安装", "Install")), ("client", ("Client", "Client")),
                                                       *[(f"sdk-{g}", SDK_GROUPS[g]) for g in SDK_GROUPS],
                                                       ("event", ("Event", "Event")), ("krinoerror", ("KrinoError", "KrinoError"))])
    html_.append(f'<h4>{T(("资源", "Resources"))}</h4>')
    html_.append(f'<a href="{{root}}{OPENAPI_PUBLISHED}" download>openapi.json</a>')
    html_.append(f'<a href="{GITHUB}" target="_blank" rel="noopener">GitHub ↗</a>')
    html_.append(f'<a href="{PYPI}" target="_blank" rel="noopener">PyPI ↗</a>')
    html_.append("</div></nav>")
    return "\n".join(html_)


def layout(rel, zh, body):
    return f'<div class="dev">\n{sidebar(rel, zh)}\n<article class="dev-main">\n{body}\n</article>\n</div>'


def api_base(R):
    from regions import SITE
    return f"{SITE}{R['products'][0]['app']}api"


def _json_lit(v, zh):
    """请求示例的 JSON：(中, 英) 取一个；"$VAR" 留给 shell 展开时要换引号，这里简单处理成字面量。"""
    if isinstance(v, tuple):
        return tr(v, zh)
    if isinstance(v, dict):
        return {k: _json_lit(x, zh) for k, x in v.items()}
    return v


def curl(method, path, zh):
    key = f"{method} {path}"
    url_path = re.sub(r"\{(\w+)\}", lambda m: "$" + VARS[m.group(1)], path)
    spec_q = [n for n, where, _, req in params(_openapi(), method, path) if where == "query" and req]
    q = "&".join([f"{n}=${VARS.get(n, n.upper())}" for n in spec_q] + ([QUERY[key]] if key in QUERY else []))
    url = f"$API{url_path}" + (f"?{q}" if q else "")
    lines = [f'curl{" -X " + method if method not in ("GET", "POST") or (method == "POST" and key not in REQ and path != "/voice/stt") else ""} "{url}"']
    if path not in ("/auth/register", "/auth/login", "/health"):
        lines.append('-H "Authorization: Bearer $KRINO_API_KEY"')
    if path == "/voice/stt":
        lines.append("-F file=@speech.webm")
    elif key in REQ:
        body = json.dumps(_json_lit(REQ[key], zh), ensure_ascii=False)
        if "$" in body:  # 要展开变量：用双引号
            lines += ["-H 'Content-Type: application/json'", '-d "' + body.replace('"', '\\"') + '"']
        else:
            lines += ["-H 'Content-Type: application/json'", f"-d '{body}'"]
    if path == "/voice/tts":
        lines.append("-o speech.ogg")
    if path.endswith("/stream"):
        lines[0] = lines[0].replace("curl ", "curl -N ")
    return " \\\n  ".join(lines)


def endpoint(spec, method, path, title, desc, ex, zh):
    T = lambda x: tr(x, zh)  # noqa: E731
    op = _op(spec, method, path)
    authed = any(p["name"] == "authorization" for p in op.get("parameters", []))
    rows = []
    where_label = {"path": ("路径", "path"), "query": ("查询", "query"), "body": ("请求体", "body"), "form": ("表单", "form")}
    for name, where, s, req in params(spec, method, path):
        doc = T(_pdoc(method, path, name))
        rules = _rules(s, zh)
        rows.append((f"<code>{esc(name)}</code>", T(where_label[where]), f"<code>{esc(_type(s))}</code>",
                     f'<span class="req">{T(("必填", "required"))}</span>' if req else f'<span class="opt">{T(("可选", "optional"))}</span>', doc + (f'<span class="prule">{rules}</span>' if rules else "")))
    ptable = table([T(("参数", "Name")), T(("位置", "In")), T(("类型", "Type")), T(("必填", "Required")), T(("说明", "Description"))], rows, "params") \
        if rows else f'<p class="none">{T(("无参数。", "No parameters."))}</p>'
    lang, sample = EXAMPLES[ex](zh)
    auth = f'<span class="lock">{T(("需要登录", "Auth"))}</span>' if authed else f'<span class="lock open">{T(("无需登录", "Public"))}</span>'
    return f"""<section class="ep" id="{ep_id(method, path)}">
  <h3>{esc(T(title))}</h3>
  <p class="ep-line">{badge(method)}<code>{esc(path)}</code>{auth}</p>
  <p>{T(desc)}</p>
  <h4>{T(("参数", "Parameters"))}</h4>
  {ptable}
  <div class="ep-ex">
    <div><h4>{T(("请求示例", "Request"))}</h4>{code(curl(method, path, zh), "bash", zh, "cURL")}</div>
    <div><h4>{T(("返回示例", "Response"))}</h4>{code(sample, lang, zh)}</div>
  </div>
</section>"""


def py_quick(region, zh):
    return f'''from krino_world import Client

with Client(region="{region}") as kw:     # {"密钥从环境变量 KRINO_API_KEY 读；也可以写 api_key='km_...'" if zh else "reads the key from KRINO_API_KEY; or pass api_key='km_...'"}
    character = kw.characters()[0]           # {"新账号自带官方角色" if zh else "a new account already has the official characters"}
    session = kw.start_session(character["id"])
    print(session["greeting"])

    turn = kw.send(session["id"], "{"今天过得怎么样？" if zh else "How was your day?"}")
    print(turn["reply"]["content"])'''


def curl_quick(R, zh):
    return f'''API={api_base(R)}

# {"1. 选一个角色，开始对话（KRINO_API_KEY 是你在设置里建的密钥）" if zh else "1. Pick a character and start a session (KRINO_API_KEY is the key from Settings)"}
CHARACTER_ID=$(curl -s $API/characters -H "Authorization: Bearer $KRINO_API_KEY" | jq -r '.[0].id')
SESSION_ID=$(curl -s $API/sessions -H "Authorization: Bearer $KRINO_API_KEY" -H 'Content-Type: application/json' \\
  -d "{{\\"character_id\\": \\"$CHARACTER_ID\\"}}" | jq -r .id)

# {"2. 说一句话" if zh else "2. Say something"}
curl -s $API/sessions/$SESSION_ID/messages -H "Authorization: Bearer $KRINO_API_KEY" -H 'Content-Type: application/json' \\
  -d '{{"text": "{"今天过得怎么样？" if zh else "How was your day?"}"}}' | jq -r .reply.content'''


def py_stream(zh):
    return f'''for event in kw.stream(session["id"], "{"讲个故事吧" if zh else "Tell me a story"}"):
    if event.name == "delta":
        print(event.data["text"], end="", flush=True)
    elif event.name == "error":
        print("\\n", event.data["message"])'''


def overview_page(region, R):
    zh = R["lang"].startswith("zh")
    T = lambda x: tr(x, zh)  # noqa: E731
    app = "{app:world}"
    other = ("国际站" if zh else "the mainland China site")
    body = f"""<section class="dev-hero" id="overview">
  <p class="tag">// DEVELOPERS</p>
  <h1 class="title">{T(("开发者<em>中心</em>", "Build with <em>KRINO</em>"))}</h1>
  <p class="lead">{T(("用 HTTP 接口或 Python SDK，把会记得你的 AI 角色接进你自己的应用：对话、记忆、语音、视觉。KRINO WORLD 网页版用的就是同一套接口，它能做的你都能做。",
                      "Bring AI characters that remember you into your own app over HTTP or with the Python SDK: chat, memory, voice and vision. The KRINO WORLD web app uses the very same API, so anything it does, you can do."))}</p>
  <div class="dev-doors">
    <a href="#quickstart"><b>01</b><h3>{T(("快速开始", "Quick start"))}</h3><p>{T(("三步跑通第一次对话", "Your first conversation in three steps"))}</p></a>
    <a href="{{base}}developers/api/"><b>02</b><h3>{T(("API 参考", "API reference"))}</h3><p>{T(("每个接口的参数、请求和返回示例", "Every endpoint with parameters and examples"))}</p></a>
    <a href="{{base}}developers/sdk/"><b>03</b><h3>Python SDK</h3><p><code>pip install krino-world</code></p></a>
  </div>
</section>
<section id="quickstart">
  <h2>{T(("快速开始", "Quick start"))}</h2>
  <ol class="dev-steps">
    <li><h3>{T(("创建 API 密钥", "Create an API key"))}</h3>
      <p>{T((f'登录 <a href="{app}">KRINO WORLD</a>，在 <b>设置 → API 密钥</b> 里创建一把。它以 <code>km_</code> 开头，只显示一次，删掉之前一直有效。像密码一样保管，放进环境变量最方便：',
             f'Sign in to <a href="{app}">KRINO WORLD</a> and create one under <b>Settings → API keys</b>. It starts with <code>km_</code>, is shown only once and stays valid until you delete it. Keep it like a password; an environment variable is easiest:'))}</p>
      {code("export KRINO_API_KEY=km_...", "bash", zh)}
      <p class="note">{T((f"账号和密钥按地区分开：本站的密钥只能用在本站的接口上，和{other}不通。", f"Accounts and keys belong to one region: a key from this site works only with this site’s API, not with {other}."))}</p></li>
    <li><h3>{T(("安装 SDK", "Install the SDK"))}</h3>
      {code("pip install krino-world", "bash", zh)}
      <p>{T(("需要 Python 3.10 以上，唯一的依赖是 httpx。不用 Python 也行，所有功能都是普通的 HTTP 接口。", "Python 3.10 or newer; its only dependency is httpx. No Python? Everything is a plain HTTP endpoint."))}</p></li>
    <li><h3>{T(("第一次对话", "Say hello"))}</h3>
      {tabs([("py", "Python", py_quick(region, zh), "python"), ("curl", "cURL", curl_quick(R, zh), "bash")], zh)}
      <p>{T(("想让回复一个字一个字地出来，用流式：", "To show the reply as it's written, stream it:"))}</p>
      {code(py_stream(zh), "python", zh)}</li>
  </ol>
</section>
<section id="basics">
  <h2>{T(("基本信息", "Basics"))}</h2>
  {table([T(("项目", "Item")), T(("说明", "Details"))], [
        (T(("接口地址", "Base URL")), f"<code>{api_base(R)}</code>"),
        (T(("鉴权", "Authentication")), T(("在设置里建一把 API 密钥，请求头带 <code>Authorization: Bearer &lt;密钥&gt;</code>", "Create an API key in Settings and send <code>Authorization: Bearer &lt;key&gt;</code>"))),
        (T(("数据格式", "Format")), T(("请求和返回都是 JSON（UTF-8）；流式回复是 server-sent events；语音合成返回音频", "JSON (UTF-8) both ways; streamed replies are server-sent events; speech comes back as audio"))),
        (T(("额度", "Limits")), T(("每个账号每天有额度，用完返回 <code>429</code>，第二天恢复", "Each account has a daily credit budget; when it runs out you get <code>429</code> until the next day"))),
        (T(("报错", "Errors")), T(('<code>{"detail": "…"}</code>，说明是给人看的。<a href="{base}developers/api/#errors">错误码</a>', '<code>{"detail": "…"}</code> with a human-readable message. <a href="{base}developers/api/#errors">Error codes</a>'))),
        (T(("开源", "Open source")), T((f'SDK 和接口定义以 Apache-2.0 开源：<a href="{GITHUB}" target="_blank" rel="noopener">GitHub</a>', f'The SDK and API definitions are Apache-2.0: <a href="{GITHUB}" target="_blank" rel="noopener">GitHub</a>'))),
    ], "kv")}
  <p class="note">{T(("有问题、想要更高的额度或测试账号，写信到", "Questions, higher limits or a test account: write to"))} <a href="mailto:{{contact}}?subject=Developer">{{contact}}</a></p>
</section>"""
    meta = {"title": T(("开发者中心", "Developers")),
            "description": T(("KRINO WORLD 开放接口：快速开始、API 参考和 Python SDK（pip install krino-world）。",
                              "The KRINO WORLD API: quick start, API reference and the Python SDK (pip install krino-world)."))}
    return meta, layout("", zh, body)


def api_page(region, R):
    zh = R["lang"].startswith("zh")
    T = lambda x: tr(x, zh)  # noqa: E731
    spec = _openapi()
    base = api_base(R)
    groups = []
    for key, gtitle, eps in ENDPOINTS:
        groups.append(f'<section class="egroup" id="g-{key}"><h2>{T(gtitle)}</h2>'
                      + "\n".join(endpoint(spec, *e, zh) for e in eps) + "</section>")
    stream_ex = EXAMPLES["stream"](zh)[1]
    auth_ex = f"""API={base}
export KRINO_API_KEY=km_...   # {"设置 → API 密钥 里创建" if zh else "create one under Settings → API keys"}

curl -s $API/characters -H "Authorization: Bearer $KRINO_API_KEY\""""
    body = f"""<header class="dev-head">
  <p class="tag">// API</p>
  <h1 class="title">{T(("API <em>参考</em>", "API <em>reference</em>"))}</h1>
  <p class="lead">{T(("KRINO WORLD 的 HTTP 接口。这里列出常用的接口；全部接口（包括角色编辑、工坊、社交圈、眼镜）的完整定义在",
                      "The KRINO WORLD HTTP API. The common endpoints are here; the full definition of every endpoint (including the character editor, workshop, social circle and glasses) is in"))}
    <a href="{{root}}{OPENAPI_PUBLISHED}" download>openapi.json</a>{T(("（OpenAPI 3.1）。", " (OpenAPI 3.1)."))}</p>
</header>
<section id="base">
  <h2>{T(("接口地址", "Base URL"))}</h2>
  {code(base, "bash", zh, "Base URL")}
  <p>{T(("下面的路径都接在这个地址后面，比如 <code>POST /auth/login</code> 就是 <code>" + base + "/auth/login</code>。另一个地区是独立的部署，账号和数据各自分开。自己部署的服务器在 <code>http://&lt;主机&gt;:8630/api</code>。",
         "Every path below goes after this, so <code>POST /auth/login</code> is <code>" + base + "/auth/login</code>. The other region is a separate deployment with its own accounts and data. A server you run yourself is at <code>http://&lt;host&gt;:8630/api</code>."))}</p>
</section>
<section id="auth">
  <h2>{T(("鉴权", "Authentication"))}</h2>
  <p>{T(("登录应用，在 <b>设置 → API 密钥</b> 里创建一把密钥（以 <code>km_</code> 开头，只显示一次），之后每个请求带上 <code>Authorization: Bearer &lt;密钥&gt;</code>。密钥删掉之前一直有效；泄露了就在设置里删掉，用它的程序马上失效。",
         "Sign in to the app and create a key under <b>Settings → API keys</b> (it starts with <code>km_</code> and is shown only once), then send <code>Authorization: Bearer &lt;key&gt;</code> on every request. A key works until you delete it; if one leaks, delete it in Settings and it stops working at once."))}</p>
  <p>{T(("密钥能做应用里能做的一切，只有管理密钥和注销账号不行（返回 <code>403</code>），这两件要在网页上登录后操作。也可以用 <a href='#" + ep_id("POST", "/auth/login") + "'>密码登录</a> 拿一个登录 token 代替密钥，它一周后过期。",
         "A key can do everything the app does except manage keys and delete the account (those get <code>403</code> and need a signed-in browser). You can also <a href='#" + ep_id("POST", "/auth/login") + "'>log in with a password</a> for a login token instead; it expires after a week."))}</p>
  {code(auth_ex, "bash", zh)}
</section>
<section id="streaming">
  <h2>{T(("流式回复", "Streaming"))}</h2>
  <p>{T(("<code>POST /sessions/{sid}/stream</code> 用 server-sent events 返回，顺序是：",
         "<code>POST /sessions/{sid}/stream</code> answers with server-sent events, in this order:"))}</p>
  {table([T(("事件", "Event")), T(("内容", "Data"))], [
        ("<code>decision</code>", T(("最先到：这一轮角色决定做什么（回复、保持安静、做个动作……）", "First: what the character decided to do this turn (reply, stay quiet, make a gesture…)"))),
        ("<code>delta</code>", T(("回复的一小段文字 <code>text</code>，按顺序拼起来就是整句", "A piece of the reply in <code>text</code>; join them in order"))),
        ("<code>done</code>", T(("结束，内容和 <code>/messages</code> 的返回一样", "The end, with the same object <code>/messages</code> returns"))),
        ("<code>error</code>", T(("生成中途失败时代替 <code>done</code>：<code>{&quot;message&quot;: &quot;…&quot;}</code>", "Replaces <code>done</code> if generation fails partway: <code>{&quot;message&quot;: &quot;…&quot;}</code>"))),
    ])}
  {code(stream_ex, "sse", zh)}
  <p class="note">{T(("自己在前面加反向代理的话，要给这个接口关掉响应缓冲。", "If you put a reverse proxy in front, turn off response buffering for this endpoint."))}</p>
</section>
<section id="errors">
  <h2>{T(("错误码", "Errors"))}</h2>
  <p>{T(("出错时返回 <code>{&quot;detail&quot;: &quot;…&quot;}</code>，说明是给人看的，用本站的语言。", "Errors come back as <code>{&quot;detail&quot;: &quot;…&quot;}</code>, written for people, in the site's language."))}</p>
  {table([T(("状态码", "Status")), T(("意思", "Meaning"))], [(f"<code>{c}</code>", T(d)) for c, d in ERRORS])}
</section>
{"".join(groups)}"""
    meta = {"title": T(("API 参考", "API reference")),
            "description": T(("KRINO WORLD 接口参考：账号、角色、对话（含流式）、记忆、语音，每个接口都有参数说明和请求、返回示例。",
                              "KRINO WORLD API reference: accounts, characters, chat (with streaming), memory and voice, each with parameters and examples."))}
    return meta, layout("api/", zh, body)


def sdk_page(region, R):
    zh = R["lang"].startswith("zh")
    T = lambda x: tr(x, zh)  # noqa: E731
    by_group = {}
    for name, sig, group in sdk_methods():
        by_group.setdefault(group, []).append((name, sig))
    sections = []
    for g, title in SDK_GROUPS.items():
        items = "".join(f'<div class="fn" id="sdk-fn-{n}"><code class="sig">{hl(s, "python")}</code><p>{T(SDK_DOC[n])}</p></div>'
                        for n, s in by_group.get(g, []))
        sections.append(f'<section id="sdk-{g}"><h2>{T(title)}</h2>{items}</section>')
    ver = sdk_version()
    body = f"""<header class="dev-head">
  <p class="tag">// PYTHON SDK</p>
  <h1 class="title">Python <em>SDK</em></h1>
  <p class="lead">{T(("<code>krino-world</code> 把接口包成了几十个方法，返回普通的 dict 和 list。", "<code>krino-world</code> wraps the API in a few dozen methods that return plain dicts and lists."))}
    <span class="ver">v{esc(ver)}</span> · <a href="{PYPI}" target="_blank" rel="noopener">PyPI</a> · <a href="{GITHUB}/tree/main/sdk/python" target="_blank" rel="noopener">{T(("源码", "Source"))}</a></p>
</header>
<section id="install">
  <h2>{T(("安装", "Install"))}</h2>
  {code("pip install krino-world", "bash", zh)}
  <p>{T(("需要 Python 3.10 以上，唯一的依赖是 httpx。", "Python 3.10 or newer; its only dependency is httpx."))}</p>
  {code(py_quick(region, zh), "python", zh)}
</section>
<section id="client">
  <h2>Client</h2>
  <div class="fn"><code class="sig">{hl(f'Client(region="global", base_url=None, api_key=None, token=None, timeout=120)', "python")}</code></div>
  {table([T(("参数", "Argument")), T(("说明", "Description"))], [
        ("<code>region</code>", T(('<code>"cn"</code> 中国大陆站，<code>"global"</code> 国际站。两边账号不通', '<code>"cn"</code> for the mainland China site, <code>"global"</code> for the international one. Their accounts are separate'))),
        ("<code>base_url</code>", T(("连自己部署的服务器，比如 <code>http://127.0.0.1:8630</code>（填了就不看 region）", "Your own server, such as <code>http://127.0.0.1:8630</code> (overrides region)"))),
        ("<code>api_key</code>", T(("设置 → API 密钥 里建的密钥（<code>km_</code> 开头）。不填就读环境变量 <code>KRINO_API_KEY</code>", "A key from Settings → API keys (starts with <code>km_</code>). If omitted, read from the <code>KRINO_API_KEY</code> environment variable"))),
        ("<code>token</code>", T(("已有的登录 token（用密码登录时拿到的），不用再登录", "A login token you already have (from a password login), so you needn't log in again"))),
        ("<code>timeout</code>", T(("请求超时，秒", "Request timeout in seconds"))),
    ])}
  <p>{T(("用 <code>with</code> 会在结束时关掉连接；不用 <code>with</code> 就自己调 <code>close()</code>。没有 API 密钥时也可以 <code>kw.login(用户名, 密码)</code>，拿到的 token 一周后过期。",
         "<code>with</code> closes the connection when you're done; otherwise call <code>close()</code>. Without an API key you can <code>kw.login(username, password)</code> instead; that token expires after a week."))}</p>
</section>
{"".join(sections)}
<section id="event">
  <h2>Event</h2>
  <p>{T(("<code>stream()</code> 产出的事件，有 <code>name</code> 和 <code>data</code> 两个字段。<code>name</code> 是 <code>decision</code>、<code>delta</code>、<code>done</code> 或 <code>error</code>，含义见 <a href='{base}developers/api/#streaming'>流式回复</a>。",
         "What <code>stream()</code> yields: <code>name</code> and <code>data</code>. <code>name</code> is <code>decision</code>, <code>delta</code>, <code>done</code> or <code>error</code>; see <a href='{base}developers/api/#streaming'>Streaming</a>."))}</p>
  {code(py_stream(zh), "python", zh)}
</section>
<section id="krinoerror">
  <h2>KrinoError</h2>
  <p>{T(("服务器拒绝请求时抛出：<code>.status</code> 是 HTTP 状态码，<code>.message</code> 是服务器给的说明。", "Raised when the server refuses a request: <code>.status</code> is the HTTP status, <code>.message</code> the server's explanation."))}</p>
  {code(f'''from krino_world import Client, KrinoError

try:
    kw.send(session["id"], "")
except KrinoError as e:
    print(e.status, e.message)   # {"400 消息不能为空" if zh else "400 Message is empty"}''', "python", zh)}
</section>"""
    meta = {"title": "Python SDK",
            "description": T(("KRINO WORLD 的 Python SDK：pip install krino-world，几行代码和会记得你的 AI 角色对话。",
                              "The KRINO WORLD Python SDK: pip install krino-world and talk to AI characters that remember you in a few lines."))}
    return meta, layout("sdk/", zh, body)


PAGES = {"developers/": overview_page, "developers/api/": api_page, "developers/sdk/": sdk_page}
