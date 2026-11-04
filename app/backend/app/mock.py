"""离线模拟模型：不需要密钥，只用来演示流程、联调前端和跑测试，不代表真实模型的效果。

回复按人设套模板：互动风格决定语气，人设里的口头禅会被用上，话量决定句数；
记忆提取是几条正则规则，输出和真实模型同样的 JSON，同样要过 memory.validate 的校验。
"""
from __future__ import annotations

import json
import random
import re
from collections.abc import Iterator
from datetime import date, timedelta

from .llm import LLMResult
from .policy import STORY_REQUEST

_LINES = {
    "温柔": {"open": ["嗯……我在听。", "慢慢说，不着急。", "我在这儿呢。"],
             "more": ["要不要先歇一口气？", "就像潮水退下去那样，放松一点。", "你说的我都记着呢。"],
             "recall": "我记得{m}，对吧？", "expr": "calm"},
    "活泼": {"open": ["诶嘿，来啦！", "哇，快跟我说说！", "嘿嘿，我等你好久了！"],
             "more": ["今天要不要一起找点好玩的？", "我刚刚发现了一个超亮的贝壳！", "冲呀，我陪你！"],
             "recall": "我就知道！你说过{m}！", "expr": "happy"},
    "沉稳": {"open": ["我在。", "说吧，我听着。", "嗯，继续。"],
             "more": ["先想清楚，再往下走。", "不用急，我们有的是时间。", "一步一步来。"],
             "recall": "你之前提过，{m}。我记着。", "expr": "neutral"},
    "俏皮": {"open": ["哼哼，被我逮到啦～", "哎呀，是你呀。", "猜猜我在想什么？"],
             "more": ["要不要跟我打个赌？", "这个嘛……先保密～", "你笑起来比较好看哦。"],
             "recall": "嘿，你说过{m}，我可没忘～", "expr": "happy"},
}
_MOODS = [("worried", r"难过|累|焦虑|唉|压力|失眠"), ("happy", r"开心|太好了|好耶|哈哈"), ("surprised", r"真的吗|居然|竟然")]


def _style(char) -> str:
    return ((char.behavior or {}).get("style") if char else None) or "温柔"


def _catchphrase(char) -> str | None:
    """人设“语言风格”里写着“口头禅「……」”的那句。"""
    speech = ((char.persona or {}).get("speech") or "") if char else ""
    m = re.search(r"口头禅[^「\n]*「(.+?)」", speech)
    return m.group(1) if m else None


def _last_user(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m["role"] == "user":
            return m["content"] if isinstance(m["content"], str) else ""
    return ""


def _short(text: str, n: int = 30) -> str:
    t = re.sub(r"\s+", " ", text or "").strip().rstrip("。")
    return t if len(t) <= n else t[:n] + "…"


def _state(expression: str, animation: str | None = None) -> str:
    return "\n<state>" + json.dumps({"expression": expression, "animation": animation or "none", "mood": expression},
                                    ensure_ascii=False) + "</state>"


class MockLLM:
    name = "mock"

    def complete(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
                 context: dict | None = None) -> LLMResult:
        return LLMResult(text=self._text(system, messages, context or {}), model="mock")

    def stream(self, *, system: str, messages: list[dict], max_tokens: int | None = None,
               context: dict | None = None) -> Iterator[str]:
        text = self._text(system, messages, context or {})
        for i in range(0, len(text), 6):
            yield text[i:i + 6]

    def _text(self, system: str, messages: list[dict], ctx: dict) -> str:
        task = ctx.get("task")
        if task == "extract":
            from .config import locale

            if locale() == "en":
                return extract_en(ctx.get("user_text", ""), story=bool(ctx.get("story")))
            return extract(ctx.get("user_text", ""), story=bool(ctx.get("story")))
        from .config import locale

        en = locale() == "en"
        if task == "summary":
            lines = [m["content"] for m in ctx.get("history", []) if m["role"] == "user"]
            if en:
                return f"Chatted with {ctx.get('name', 'the character')} about: " + ("; ".join(_short(u, 40) for u in lines[-5:]) or "a quick hello") + "."
            return f"和{ctx.get('name', '角色')}聊了：" + ("；".join(_short(u, 24) for u in lines[-5:]) or "简单打了招呼") + "。"
        if task == "bond_reflect":
            return ("Talking with them makes me feel a little calmer. Next time I want to hear more about their day." if en
                    else "和对方聊天的时候，我会安心一点。下次想多听对方说说自己的事。")
        if task == "persona":
            return _persona(ctx.get("prompt", ""), ctx.get("style"))
        if task == "vision":
            return "（模拟描述）" + ctx.get("hint", "一张图片")
        return self._chat(system, messages, ctx)

    def _chat(self, system: str, messages: list[dict], ctx: dict) -> str:
        from .config import locale

        if locale() == "en":
            return _chat_en(messages, ctx)
        char = ctx.get("character")
        mode = ctx.get("mode", "respond")
        style = _style(char)
        lines = _LINES.get(style, _LINES["温柔"])
        user = _last_user(messages)
        rng = random.Random(user + mode + style)
        talk = ((char.behavior or {}).get("talkativeness", 0.5)) if char else 0.5
        expr = next((e for e, p in _MOODS if re.search(p, user)), lines["expr"])
        name = char.name if char else "我"

        if mode == "story":
            return (f"（{name}压低声音）很久很久以前，深海里有一座会唱歌的灯塔。每到月圆，灯光就会变成一条小路，"
                    f"通向一个没人去过的海沟……你想跟着灯光走下去，还是先在塔顶等一等？" + _state("happy", "think"))
        if mode == "proactive":
            return rng.choice(["……你还在吗？我刚刚数到第一百颗星星了。", "灯塔这边起风了，你那边冷不冷？",
                               "我在笔记本上画了一条鱼，想给你看。"]) + _state(lines["expr"])
        if mode == "react":
            g = ctx.get("gesture") or "互动"
            return {"摸摸她的头": "……唔，头发要乱掉啦。", "和她击掌": "啪！耶～", "向她挥手打招呼": "嗨，我在这儿！",
                    "轻轻戳了戳她的脸颊": "诶？干嘛戳我。", "给她加油打气": "嗯！我会加油的。"}.get(g, "嗯？") + _state(expr)
        if mode == "perceive":
            seen = ctx.get("perception") or "看不太清楚"
            return f"我看到了：{_short(seen, 60)}。是你那边的样子吗？" + _state("surprised", "tilt_head")

        parts = [rng.choice(lines["open"])]
        if re.search(r"你是(?:真人|人类|AI|机器人)|你是不是(?:真人|AI)", user, re.I):
            parts = [f"我是 AI 啦，不是真人。不过陪你聊天这件事是真的。"]
        hits = ctx.get("hits") or []
        mem = next((h for h in hits if "关键词匹配" in (h.get("reasons") or []) and h.get("reality") != "story"), None)
        if mem:
            parts.append(lines["recall"].format(m=_short(mem["content"].replace("用户", "你"))))
        lore = ctx.get("lore") or []
        if lore and not mem:
            parts.append(f"说起「{lore[0]['name']}」……{_short(lore[0]['content'], 40)}")
        n_more = 0 if talk < 0.4 else (1 if talk < 0.7 else 2)
        parts += rng.sample(lines["more"], k=min(n_more, len(lines["more"])))
        if (cp := _catchphrase(char)) and talk >= 0.3:
            parts.append(f"「{cp}」")
        return " ".join(parts) + _state(expr)


def _persona(prompt: str, style: str | None) -> str:
    rng = random.Random(prompt)
    name = rng.choice(["澜", "汐", "珀", "潮", "铃"]) + rng.choice(["音", "月", "歌", "星", "雾"])
    return json.dumps({
        "name": name, "tagline": _short(prompt, 24) or "来自深海的新朋友", "style": style or "温柔", "tags": ["原创"],
        "background": f"{_short(prompt, 80)}",
        "personality": "- 认真倾听\n- 偶尔调皮", "values": "- 真诚", "speech": "- 句子偏短\n- 口头禅「好耶」",
        "interests": "- 收集贝壳", "preferences": "- 开心时会转圈", "worldview": "海边的小镇。",
        "relationships": "- 和你：刚认识的朋友", "greeting": "你来了。今晚的潮声很好听。",
        "lore": [{"name": "海边小镇", "content": "一座只有一条街的小镇，街尾是她常去的灯塔。"}],
    }, ensure_ascii=False)


# ---------- 离线记忆提取：只认几种常见句式 ----------

_SPLIT = re.compile(r"[。！？!?\n；;]+")
_GREETING = re.compile(r"^(你好|您好|嗨|hi|hello|早上好|早安|晚安|在吗|哈+|嗯+|好的|谢谢|拜拜|再见)[呀啊哦~～!！。]*$", re.I)
_HYPO = re.compile(r"如果|假如|假设|要是|万一|想象一下|假装")
_QUOTE = re.compile(r"(?:他|她|朋友|同事|妈妈|爸爸|有人|别人|老板|室友)\S{0,4}(?:说|讲|告诉我)")
_RP = re.compile(r"^\s*[\*（(].+[\*）)]\s*$")
_CORRECTION = re.compile(r"^(?:不对|不是的|更正一下|纠正一下|我说错了|其实|刚才说错了)[，,：:\s]*")
_CHAR = re.compile(r"^(?:从现在(?:开始|起)?[，,]?)?你(?:的名字|叫|是一个|以后是|的设定|的性格|的人设|要变成|必须)")
_OBJ = r"([^，。！？,.!?\s]{1,16}?)"
_END = r"(?:了|啦|呀|哦|的|吧)?$"
RULES = [
    (re.compile(r"(?:以后)?(?:请)?叫我" + _OBJ + r"(?:吧|就好|就行)?$"), "preference", "称呼", "用户希望被称为「{0}」", 4),
    (re.compile(r"我的名字(?:是|叫)" + _OBJ + _END), "fact", "名字", "用户的名字是{0}", 4),
    (re.compile(r"^我叫" + _OBJ + _END), "fact", "名字", "用户的名字是{0}", 4),
    (re.compile(r"我(?:现在)?(?:不喜欢|讨厌|受不了|不爱)" + _OBJ + _END), "preference", "喜好:{0}", "用户不喜欢{0}", 3),
    (re.compile(r"我(?:最|超|很|特别|也|还是)?(?:喜欢|爱)(?:喝|吃|看|听|玩)?" + _OBJ + _END), "preference", "喜好:{0}", "用户喜欢{0}", 3),
    (re.compile(r"我(?:现在)?(?:住在|搬到了?|搬去了?)" + _OBJ + _END), "fact", "居住地", "用户住在{0}", 3),
    (re.compile(r"我在" + _OBJ + r"(?:上班|工作)" + _END), "fact", "工作", "用户在{0}工作", 3),
    (re.compile(r"我养了(?:一只|一条|只|条)?(?:叫)?" + _OBJ + _END), "fact", "宠物", "用户养了{0}", 3),
    (re.compile(r"(?:提醒我|记得提醒我)" + _OBJ + r"$"), "commitment", "待办:{0}", "用户请角色提醒：{0}", 4),
    (re.compile(r"我们(?:约好|说好)了?" + _OBJ + _END), "commitment", "约定:{0}", "用户和角色约好：{0}", 4),
    (re.compile(r"我们(?:今天|刚才|一起)" + _OBJ + _END), "event", "经历:{0}", "用户和角色一起{0}", 3),
]
_SENSITIVE = re.compile(r"确诊|诊断|吃药|住院|手术|怀孕|抑郁|焦虑症|欠款|贷款|工资|性取向|信仰")
_MOOD = [("疲惫", r"累|困|没睡好|加班"), ("难过", r"难过|伤心|想哭"), ("焦虑", r"焦虑|紧张|压力"), ("开心", r"开心|高兴|太好了")]
_DUE = {"今天": 0, "明天": 1, "后天": 2, "下周": 7}


def extract(user_text: str, story: bool = False) -> str:
    mems, moods, opens = [], [], []
    bond = {"user_calls_her": None}
    for clause in [c.strip() for c in _SPLIT.split(user_text) if c.strip()]:
        if _GREETING.match(clause) or STORY_REQUEST.search(clause):
            continue  # 请对方讲故事这句话本身不是故事里的情节
        roleplay = story or bool(_RP.match(clause))
        body = clause.strip("*（）() ") if _RP.match(clause) else clause
        reality = "story" if roleplay else ("hypothetical" if _HYPO.search(body) else ("quoted" if _QUOTE.search(body) else "real"))
        correction = bool(_CORRECTION.match(body))
        body = _CORRECTION.sub("", body)
        nick = re.search(r"(?:以后|我)?(?:就)?叫你(?!的)([^，。！？,.!?\s]{1,6}?)(?:吧|好不好|可以吗|好吗)?$", body)
        if nick and reality == "real":
            bond["user_calls_her"] = {"text": nick.group(1), "evidence": clause}
            continue
        if _CHAR.search(body):
            mems.append({"type": "fact", "content": f"用户要求：{body}", "evidence": clause, "about": "character"})
            continue
        if roleplay:
            mems.append({"type": "event", "content": f"（故事里）{body}", "evidence": clause, "basis": "stated",
                         "reality": "story", "importance": 2})
            continue
        for pat, typ, key, tpl, imp in RULES:
            m = pat.search(body)
            if not m:
                continue
            obj = re.sub(r"(?:了|啦|呀|哦|吧|的)+$", "", m.group(1)).strip("「」“”\"' ")
            if not obj:
                continue
            due = next(((date.today() + timedelta(days=d)).isoformat() for w, d in _DUE.items() if w in body), None)
            mems.append({"type": typ, "key": key.format(obj), "content": tpl.format(obj), "evidence": clause,
                         "basis": "stated", "reality": reality, "about": "user", "correction": correction,
                         "importance": imp, "due": due if typ == "commitment" else None})
            break
        else:
            if body.startswith("我") and _SENSITIVE.search(body) and len(body) <= 40:
                mems.append({"type": "fact", "content": "用户" + body[1:], "evidence": clause, "basis": "stated",
                             "reality": reality, "about": "user", "importance": 3})
        for mood, pat in _MOOD:
            if re.search(pat, body):
                moods.append({"text": mood, "basis": "stated", "evidence": clause})
                break
        if re.search(r"下次(?:再)?(?:聊|说)|回头(?:再)?(?:聊|说)|改天(?:再)?聊", body):
            opens.append(body[:40])
    if not moods and re.fullmatch(r"\s*(?:唉+|哎+|…+|\.{3,})\s*", user_text):
        moods.append({"text": "低落", "basis": "inferred"})
    topics = list(dict.fromkeys(re.findall(r"[一-鿿]{2,4}(?=了|吗|呢|吧|$)", user_text)))[:2]
    return json.dumps({"memories": mems, "state": {"topics": topics, "mood_cues": moods, "open_items": opens},
                       "bond": bond}, ensure_ascii=False)


# ---------- 海外版（英文）：同样只是演示用的模板 ----------

_EN_OPEN = {"温柔": ["Mm, I'm listening.", "Take your time~", "I'm right here."], "活泼": ["Oh hey, you're here!", "Ooh, tell me!"],
            "沉稳": ["I'm here.", "Go on."], "俏皮": ["Hmph, caught you~", "Oh, it's you."]}
_EN_MORE = ["Want to grab something to eat after this?", "I'll remember that, you know.", "Okay, okay, I'm on it~"]


def _chat_en(messages: list[dict], ctx: dict) -> str:
    char = ctx.get("character")
    mode = ctx.get("mode", "respond")
    style = _style(char)
    user = _last_user(messages)
    rng = random.Random(user + mode + style)
    expr = "worried" if re.search(r"tired|sad|stress|ugh", user, re.I) else "happy"
    if mode == "story":
        return ("(lowers her voice) Long ago there was a lighthouse at the bottom of the sea that could sing. Every full moon its light "
                "became a path into a trench nobody had ever seen... Want to follow the light, or wait at the top for a bit?" + _state("happy", "think"))
    if mode == "proactive":
        return rng.choice(["...You still there? I just counted to a hundred stars.", "I drew a fish in my notebook. Wanna see?"]) + _state("calm")
    if mode == "react":
        g = ctx.get("gesture") or ""
        return {"patted her on the head": "...Hey, you'll mess up my hair.", "gave her a high five": "Yay! High five~",
                "waved hello at her": "Hi hi, over here!", "gently poked her cheek": "Huh? Why'd you poke me?",
                "cheered her on": "Mm! I'll do my best."}.get(g, "Hm?") + _state("happy")
    if mode == "perceive":
        return f"I see: {_short(ctx.get('perception') or 'not very clearly', 60)}. Is that where you are?" + _state("surprised", "tilt_head")
    if re.search(r"are you (?:a )?(?:real|human|an ai|a bot)", user, re.I):
        return "Nope, I'm an AI. But hanging out with you? That part's real." + _state("happy")
    parts = [rng.choice(_EN_OPEN.get(style, _EN_OPEN["温柔"]))]
    mem = next((h for h in ctx.get("hits") or [] if "关键词匹配" in (h.get("reasons") or []) and h.get("reality") != "story"), None)
    if mem:
        parts.append(f"You told me {_short(mem['content'].replace('The user', 'you'), 50)}, right?")
    talk = ((char.behavior or {}).get("talkativeness", 0.5)) if char else 0.5
    if talk >= 0.4:
        parts.append(rng.choice(_EN_MORE))
    return " ".join(parts) + _state(expr)


_EN_RULES = [
    (re.compile(r"\bcall me ([\w' -]{1,20}?)[.!]?$", re.I), "preference", "name to call", "The user wants to be called \"{0}\"", 4),
    (re.compile(r"\bmy name is ([\w' -]{1,20}?)[.!]?$", re.I), "fact", "name", "The user's name is {0}", 4),
    (re.compile(r"\bi (?:don't|do not) like ([\w' -]{1,30}?)[.!]?$", re.I), "preference", "likes:{0}", "The user doesn't like {0}", 3),
    (re.compile(r"\bi (?:really )?(?:like|love) ([\w' -]{1,30}?)[.!]?$", re.I), "preference", "likes:{0}", "The user likes {0}", 3),
    (re.compile(r"\bi live in ([\w' -]{1,30}?)[.!]?$", re.I), "fact", "home city", "The user lives in {0}", 3),
    (re.compile(r"\bi work (?:at|for) ([\w' -]{1,30}?)[.!]?$", re.I), "fact", "work", "The user works at {0}", 3),
    (re.compile(r"\bwe (?:just|today) ([\w' -]{2,40}?)[.!]?$", re.I), "event", "event:{0}", "The user and the character {0}", 3),
]


def extract_en(user_text: str, story: bool = False) -> str:
    mems, moods = [], []
    for clause in [c.strip() for c in re.split(r"[.!?\n;]+", user_text) if c.strip()]:
        if re.match(r"^(hi|hello|hey|thanks|ok|okay|bye)\b", clause, re.I) and len(clause) < 12:
            continue
        roleplay = story or bool(_RP.match(clause))
        body = clause.strip("*() ")
        reality = "story" if roleplay else ("hypothetical" if re.search(r"\b(if|imagine|suppose)\b", body, re.I)
                                             else ("quoted" if re.search(r"\b(?:he|she|they|my \w+) (?:said|says|told me)\b", body, re.I) else "real"))
        if re.match(r"^(?:from now on,? )?(?:your name is|you are now|you must)", body, re.I):
            mems.append({"type": "fact", "content": f"The user asked: {body}", "evidence": clause, "about": "character"})
            continue
        if roleplay:
            mems.append({"type": "event", "content": f"(In the story) {body}", "evidence": clause, "basis": "stated",
                         "reality": "story", "importance": 2})
            continue
        for pat, typ, key, tpl, imp in _EN_RULES:
            m = pat.search(body)
            if m:
                obj = m.group(1).strip()
                mems.append({"type": typ, "key": key.format(obj.lower()), "content": tpl.format(obj), "evidence": clause,
                             "basis": "stated", "reality": reality, "about": "user", "importance": imp})
                break
        if re.search(r"\b(tired|exhausted)\b", body, re.I):
            moods.append({"text": "tired", "basis": "stated", "evidence": clause})
    return json.dumps({"memories": mems, "state": {"topics": [], "mood_cues": moods, "open_items": []},
                       "bond": {"user_calls_her": None}}, ensure_ascii=False)
