"""括号动作 → 人物动作 / 颜文字，以及外观工作台（mock 图像服务）。"""
from app import cues
from app.config import settings
from app.prompt import StreamFilter


def test_bracket_actions_become_kaomoji_and_cues():
    text, found = cues.convert("哼！（叉腰）才不是特意等你的 (｀・ω・´)（歪头）")
    assert text == "哼！(｀へ´)才不是特意等你的 (｀・ω・´)(・ω・?)"
    assert [(c.animation, c.expression) for c in found] == [("pout", "angry"), ("tilt_head", "surprised")]
    assert cues.convert("答案是 3（三）个") == ("答案是 3（三）个", [])  # 补充说明不是动作，原样留着
    assert cues.convert("I'm here (waves)")[1][0].animation == "wave"


def test_stream_filter_holds_half_written_action():
    f = StreamFilter()
    out = "".join(f.feed(x) for x in ["哼！（叉", "腰）才不", "是<st", "ate>{}</state>"])
    assert out == "哼！(｀へ´)才不是"


def test_actions_follow_brackets_but_respect_switches():
    from types import SimpleNamespace

    from app.chat import _actions
    p = SimpleNamespace(decision=SimpleNamespace(primary=SimpleNamespace(action="RESPOND"), extras=[]), fixed_text=None)
    char = SimpleNamespace(behavior={"animations": ["wave", "spin"]})
    found = cues.convert("（转了个圈）（脸红）")[1]
    acts = _actions(p, char, "hi", None, found, {})
    assert {"type": "animate", "name": "spin"} in acts and {"type": "emote", "expression": "happy"} in acts
    acts = _actions(p, char, "hi", None, found, {"interaction": {"animations": False}})  # 用户关了动作
    assert not any(a["type"] == "animate" for a in acts)
    acts = _actions(p, char, "hi", None, cues.convert("（歪头）")[1], {})  # 角色动作列表里没有歪头
    assert not any(a["type"] == "animate" for a in acts)


def test_workbench_design_edit_expressions_apply(user, monkeypatch):
    info = user.ok("get", "/api/workbench")
    assert info["ready"] and info["used"] == 0
    r = user.ok("post", "/api/workbench/design", json={"prompt": "蓝发、鲸鱼发饰、连帽卫衣", "n": 2})
    assert len(r["images"]) == 2 and r["used"] == 2
    first = r["images"][0]
    assert first.startswith(f"/media/u/{user.info['id']}/") and first.endswith(".webp")
    img = user.c.get(first)
    assert img.status_code == 200 and img.content[:4] == b"RIFF"
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(img.content)).getpixel((2, 2))[3] == 0  # 白底去掉了

    edit = user.ok("post", "/api/workbench/design", json={"prompt": "头发换成粉色", "base": first})
    assert len(edit["images"]) == 1  # 一个角色一张形象
    faces = user.ok("post", "/api/workbench/expressions", json={"base": first, "expressions": ["happy", "shy"]})
    assert set(faces["images"]) == {"happy", "shy"} and not faces["errors"]

    cid = user.official["id"]
    full = user.ok("get", f"/api/characters/{cid}")
    portrait = {"kind": "image", "src": first, "expressions": faces["images"]}
    saved = user.ok("put", f"/api/characters/{cid}", json={"behavior": {**full["behavior"], "portrait": portrait}})
    assert saved["behavior"]["portrait"]["expressions"]["shy"] == faces["images"]["shy"]


def test_workbench_rejects_bad_input_and_limits(user, monkeypatch):
    assert user.post("/api/workbench/design", json={"prompt": "x", "base": "https://evil.example/a.png"}).status_code == 400
    assert user.post("/api/workbench/design", json={"prompt": "x", "base": "/media/../../etc/passwd"}).status_code == 400
    assert user.post("/api/workbench/expressions", json={"base": "/static/assets/whale-girl.png", "expressions": ["smug"]}).status_code == 400
    cid = user.official["id"]
    full = user.ok("get", f"/api/characters/{cid}")
    bad = {"kind": "image", "src": "/static/assets/whale-girl.png", "expressions": {"happy": "data:image/png;base64,AAAA"}}
    assert user.put(f"/api/characters/{cid}", json={"behavior": {**full["behavior"], "portrait": bad}}).status_code == 400
    monkeypatch.setattr(settings, "image_daily_limit", 1)
    assert user.post("/api/workbench/design", json={"prompt": "蓝发", "n": 2}).status_code == 429


def test_workbench_edits_builtin_portrait(user):
    r = user.ok("post", "/api/workbench/design", json={"prompt": "换成红色卫衣", "base": "/static/assets/whale-girl.png", "n": 1})
    assert len(r["images"]) == 1


def _designed(user):
    """在官方角色上做一套形象：生成 → 两个表情 → 保存。"""
    first = user.ok("post", "/api/workbench/design", json={"prompt": "蓝发、鲸鱼发饰", "n": 1})["images"][0]
    faces = user.ok("post", "/api/workbench/expressions", json={"base": first, "expressions": ["happy", "shy"]})["images"]
    cid = user.official["id"]
    full = user.ok("get", f"/api/characters/{cid}")
    import uuid
    persona = {**full["persona"], "name": "工作台鲸" + uuid.uuid4().hex[:4],  # 名字各不相同：工坊里不出现重名
               "speech": full["persona"].get("speech", "") + "\n- 口头禅「开饭」"}  # 和官方原版不一样，才能发布
    user.ok("put", f"/api/characters/{cid}", json={"persona": persona,
                                                    "behavior": {**full["behavior"], "portrait": {"kind": "image", "src": first, "expressions": faces}}})
    return cid, first, faces


def test_export_carries_soul_and_body_to_another_account(user, other):
    cid, first, faces = _designed(user)
    r = user.get(f"/api/characters/{cid}/export", params={"format": "json"})
    pkg = r.json()
    p = pkg["behavior"]["portrait"]
    assert p["src"].startswith("data:image/webp;base64,") and set(p["expressions"]) == {"happy", "shy"}
    assert "口头禅「开饭」" in pkg["persona"]["speech"]

    # 另一个人导入这个文件：灵魂和肉体都在，图片存成了他自己的文件
    c = other.ok("post", "/api/characters/import", files={"file": ("whale.krino.json", r.content, "application/json")})
    q = c["behavior"]["portrait"]
    assert q["src"].startswith("/media/c/") and q["src"] != first
    assert set(q["expressions"]) == {"happy", "shy"} and all(v.startswith("/media/") for v in q["expressions"].values())
    assert other.c.get(q["expressions"]["shy"]).status_code == 200
    assert "口头禅「开饭」" in c["persona"]["speech"]


def test_exported_file_uploads_to_workshop_with_cover(user, other):
    cid, first, faces = _designed(user)
    data = user.get(f"/api/characters/{cid}/export", params={"format": "json"}).content
    item = other.ok("post", "/api/workshop/upload", files={"file": ("whale.krino.json", data, "application/json")},
                    data={"category": "other"})
    assert item["portrait"] and item["portrait"].startswith("/media/c/")
    # 同一个文件别人再上传一次：图片地址一样，认得出是重复内容
    from tests.conftest import make_user as mk
    r = mk(user.c).post("/api/workshop/upload", files={"file": ("whale.krino.json", data, "application/json")}, data={"category": "other"})
    assert r.status_code == 400 and "一模一样" in r.json()["detail"]
    # 第三个人领养：形象跟着过来；从工坊下载的文件里图片也是内嵌的
    from tests.conftest import make_user
    third = make_user(user.c)
    third.ok("post", f"/api/workshop/items/{item['id']}/install")
    got = next(c for c in third.ok("get", "/api/characters") if c["name"] == item["title"] and not c["official"])
    assert got["portrait"]["src"] == item["portrait"] and set(got["portrait"]["expressions"]) == {"happy", "shy"}
    dl = third.get(f"/api/workshop/items/{item['id']}/download").json()
    assert dl["behavior"]["portrait"]["src"].startswith("data:image/webp;base64,")


def test_upload_portrait_becomes_file(user):
    import base64
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (40, 60), (255, 0, 0, 128)).save(buf, "PNG")
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    src = user.ok("post", "/api/workbench/upload", json={"image": uri})["src"]
    assert src.startswith("/media/c/") and user.c.get(src).status_code == 200
    assert user.post("/api/workbench/upload", json={"image": "/static/assets/whale-girl.png"}).status_code == 400
    assert user.post("/api/workbench/upload", json={"image": "data:image/png;base64,bm90IGFuIGltYWdl"}).status_code == 400


def test_per_account_limit(user, other, monkeypatch):
    """IMAGE_USER_LIMITS 里单独设了的账号（比如测试账号）按自己的额度，其他人不受影响。"""
    monkeypatch.setattr(settings, "image_user_limits", {user.info["username"]: 1})
    assert user.ok("get", "/api/workbench")["limit"] == 1
    assert other.ok("get", "/api/workbench")["limit"] == settings.image_daily_limit
    assert user.post("/api/workbench/design", json={"prompt": "蓝发", "n": 2}).status_code == 429
    assert other.post("/api/workbench/design", json={"prompt": "蓝发", "n": 2}).status_code == 200


def test_user_limits_parse():
    from app.config import _user_limits
    assert _user_limits("krino_demo:20, tester:0,bad,x:y") == {"krino_demo": 20, "tester": 0}


def test_dashscope_rate_limit_retries(monkeypatch):
    """百炼限流（429）时等一等再试，而不是直接让这张表情失败。"""
    import httpx

    from app import workbench
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.method == "POST" and len([c for c in calls if "generation" in c]) <= 2:
            return httpx.Response(429, json={"code": "Throttling.RateQuota"})
        if req.method == "POST":
            return httpx.Response(200, json={"output": {"choices": [{"message": {"content": [{"image": "https://img.test/a.png"}]}}]}})
        return httpx.Response(200, content=b"PNG")

    real = httpx.Client
    monkeypatch.setattr(workbench.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(workbench, "RETRY_WAITS", (0, 0, 0))
    monkeypatch.setattr(workbench.time, "sleep", lambda s: None)
    monkeypatch.setattr(settings, "dashscope_api_key", "k")
    assert workbench._dashscope([{"text": "x"}], 1, "768*1152") == [b"PNG"]
    monkeypatch.setattr(workbench, "RETRY_WAITS", ())  # 不再重试：给用户一句能看懂的话
    calls.clear()
    try:
        workbench._dashscope([{"text": "x"}], 1, "768*1152")
        raise AssertionError("应该报错")
    except workbench.ImageError as e:
        assert "太忙" in str(e)


def test_kaomoji_never_spoken():
    """颜文字不能被念出来：括号外的装饰（ヾ o m ゞ ٩ و zzZ）和少了右括号的都要去掉；正常文字不受影响。"""
    from app.voice import speakable
    for *_, k in cues.RULES:
        assert speakable(f"好{k}的") == "好的", k
    assert speakable("(・_・ゞ我不知道。") == "我不知道。"
    assert speakable("Hello (world) and m(_ _)m thanks") == "Hello and thanks"
    assert speakable("email: a_b@x.com，价格 $5") == "email: a_b@x.com，价格 $5"


def test_one_sentence_makes_soul_body_and_voice(user, monkeypatch):
    """工作台一句话：灵魂 + 一张形象 + 声音一起生成。官方角色上点 → 新建角色（KRINO 不变）；自己的角色上点 → 直接换掉（可恢复）。"""
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    k = user.krino
    before = user.ok("get", f"/api/characters/{k['id']}")
    r = user.ok("post", "/api/workbench/character", json={"prompt": "一只戴围巾、爱读诗的小水獭", "character_id": k["id"]})
    c = r["character"]
    assert r["created"] and c["id"] != k["id"] and c["name"] != "KRINO"
    assert c["behavior"]["portrait"]["kind"] == "image" and c["behavior"]["portrait"]["src"].startswith("/media/")
    assert c["behavior"]["voice"]["voice"] == "longanlingxin_v3.1" and "温柔" in c["behavior"]["voice"]["style"]
    assert "glasses" not in c["behavior"]["animations"]  # 普通形象只会通用动作
    assert user.ok("get", f"/api/characters/{k['id']}")["persona"] == before["persona"]  # KRINO 原样
    assert len(r["character"]["behavior"]["portrait"]) and r["used"] == 1  # 只生成一张
    # 在自己的角色上再点：也是新建，她自己的灵魂不变（灵魂只在新建时设计）
    r2 = user.ok("post", "/api/workbench/character", json={"prompt": "一个总在打瞌睡的机器人管家", "character_id": c["id"]})
    assert r2["created"] and r2["character"]["id"] != c["id"]
    assert user.ok("get", f"/api/characters/{c['id']}")["persona"] == c["persona"]
    # 新角色窗口里自己改过的灵魂：照着建，不再让模型重写
    draft = user.ok("post", "/api/characters/generate", json={"prompt": "爱下棋的老猫"})
    draft["persona"]["name"] = "棋棋"
    draft["persona"]["speech"] = "- 口头禅「将军喵」"
    r3 = user.ok("post", "/api/workbench/character", json={"draft": draft})
    assert r3["character"]["persona"]["name"] == "棋棋" and "将军喵" in r3["character"]["persona"]["speech"]
    assert r3["character"]["behavior"]["portrait"]["src"].startswith("/media/")
    assert user.post("/api/workbench/character", json={"draft": {"persona": {"name": ""}}}).status_code == 400


def test_generate_researches_known_characters_and_keeps_pronoun(user, monkeypatch):
    """一句话里提到已有作品的角色：生成时打开联网搜索；称呼（他 / 她 / 它 / TA）跟着设定走，存下来、导出也在。"""
    from app import llm, mock

    seen = {}
    real = mock.MockLLM.complete

    def spy(self, *, system, messages, max_tokens=None, context=None):
        seen.update(context or {})
        r = real(self, system=system, messages=messages, max_tokens=max_tokens, context=context)
        if (context or {}).get("task") == "persona":
            import json as _j
            d = _j.loads(r.text); d.update(name="德拉科·马尔福", pronoun="他", voice_style="年轻男性，冷淡傲慢，语速偏慢")
            r.text = _j.dumps(d, ensure_ascii=False)
        return r

    monkeypatch.setattr(mock.MockLLM, "complete", spy)
    monkeypatch.setattr(llm, "_llm", None)
    d = user.ok("post", "/api/characters/generate", json={"prompt": "哈利·波特里的德拉科·马尔福"})
    assert seen.get("web") is True  # 让模型先查设定
    assert d["persona"]["pronoun"] == "他" and "男性" in d["behavior"]["voice"]["style"]
    c = user.ok("post", "/api/characters", json={"persona": d["persona"], "behavior": d["behavior"], "lore": d["lore"]})
    assert c["persona"]["pronoun"] == "他"
    md = user.c.get(f"/api/characters/{c['id']}/export?format=md", headers=user.h).text
    assert "pronoun: 他" in md
    bad = user.ok("post", "/api/characters", json={"persona": {**d["persona"], "name": "某人", "pronoun": "xx"}})
    assert "pronoun" not in bad["persona"]  # 不认识的称呼不存


def test_voice_design_needs_self_hosted_tts_and_is_billed(user, monkeypatch):
    """按描述设计声音：没有自建语音时说清楚；有的话返回试听和新音色编号，按百炼的价记一笔积分。"""
    from app import voice

    monkeypatch.setattr(settings, "tts_provider", "mock")
    r = user.c.post("/api/voice/design", json={"description": "低沉的老年巫师"}, headers=user.h)
    assert r.status_code == 400 and "自建语音" in r.json()["detail"]

    monkeypatch.setattr(settings, "tts_provider", "qwen")
    monkeypatch.setattr(voice, "design_voice", lambda desc, sample="": ("v0123456789-zh", b"RIFFfake"))
    charged = []
    from app import credits
    monkeypatch.setattr(credits, "charge", lambda uid, what, cny, **kw: charged.append((what, cny)))
    r = user.c.post("/api/voice/design", json={"description": "低沉的老年巫师", "sample": "你好"}, headers=user.h)
    assert r.status_code == 200 and r.headers["x-voice-id"] == "v0123456789-zh" and r.content == b"RIFFfake"
    assert charged == [("voice_design", settings.voice_design_price_cny)]
