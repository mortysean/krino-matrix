"""纯函数的单元测试：策略、回复解析、流式过滤、人设格式转换、记忆校验。"""
import pytest

from app import memory, persona_io, policy
from app.models import Character
from app.personas import OFFICIAL, default_behavior, validate_behavior
from app.prompt import StreamFilter, parse_reply


def _ctx(**us):
    return policy.PolicyContext(behavior=default_behavior("温柔"), user_settings={"interaction": {}, "privacy": {}, **us})


def test_policy_hard_constraints_win_over_scores():
    d = policy.decide(policy.InteractionEvent("message", text="嘘，别说话，给我讲个故事"), _ctx())
    assert d.primary.action == "NO_ACTION"
    blocked = {c.action: c.blocked for c in d.candidates if c.blocked}
    assert blocked["STORY"] and blocked["RESPOND"]


def test_policy_respects_character_behavior():
    calm = policy.PolicyContext(behavior={**default_behavior("沉稳"), "expressiveness": 0.0}, user_settings={})
    lively = policy.PolicyContext(behavior={**default_behavior("活泼"), "expressiveness": 1.0}, user_settings={})
    ev = policy.InteractionEvent("message", text="在吗")
    assert "EMOTE" not in policy.decide(ev, calm).actions()
    assert "EMOTE" in policy.decide(ev, lively).actions()
    limited = policy.PolicyContext(behavior={**default_behavior("活泼"), "animations": ["nod"]}, user_settings={})
    d = policy.decide(policy.InteractionEvent("message", text="挥挥手"), limited)
    assert "ANIMATE" not in d.actions()


def test_matrix_falls_back_when_unavailable(monkeypatch, tmp_path):
    from app.config import settings
    monkeypatch.setattr(settings, "matrix_checkpoint", tmp_path / "missing")
    d = policy.decide(policy.InteractionEvent("message", text="你好"), _ctx(), "matrix")
    assert d.policy == "rules" and "回退" in d.note and not d.experimental


def test_parse_reply_whitelists_state():
    c = Character(persona={"name": "x"}, behavior=default_behavior(), slug="x")
    p = parse_reply('你好\n<state>{"expression": "happy", "animation": "backflip", "mood": "好"}</state>', c)
    assert p.text == "你好" and p.expression == "happy" and p.animation is None
    p = parse_reply("没有标签<state>{坏的}</state>", c)
    assert p.text == "没有标签" and p.expression is None


def test_stream_filter_hides_state_tag_split_across_chunks():
    f = StreamFilter()
    out = "".join(f.feed(x) for x in ["你好", "呀<st", "ate>{\"expression\":", "\"happy\"}</state>"])
    assert out == "你好呀"
    f = StreamFilter()
    assert "".join(f.feed(x) for x in ["a<b", "c"]) == "a<bc"


def test_markdown_json_roundtrip_official():
    md = persona_io.to_markdown(OFFICIAL["persona"], validate_behavior(OFFICIAL["behavior"]), OFFICIAL["lore"], "whale-girl")
    d = persona_io.from_markdown(md)
    assert d.persona["background"] == OFFICIAL["persona"]["background"] and d.lore == OFFICIAL["lore"]
    assert validate_behavior(d.behavior) == validate_behavior(OFFICIAL["behavior"])
    pkg = persona_io.to_package(d.persona, d.behavior, d.lore, "whale-girl", 3)
    d2 = persona_io.from_package(pkg)
    assert d2.persona == d.persona and d2.slug == "whale-girl"


def test_behavior_validation():
    assert validate_behavior({"style": "活泼"})["talkativeness"] == 0.8
    for bad in ({"style": "暴躁"}, {"talkativeness": -1}, {"expressions": ["dance"]}, {"unknown": 1},
                {"expressions": ["happy"], "default_expression": "sad"}, {"voice": {"rate": 9}}):
        with pytest.raises(persona_io.PersonaError):
            validate_behavior(bad)


def test_memory_validation_requires_evidence():
    raw = {"memories": [
        {"type": "fact", "content": "用户住在北京", "evidence": "我住在北京", "about": "user"},
        {"type": "fact", "content": "用户是宇航员", "evidence": "我是宇航员", "about": "user"},  # 原话里没有
        {"type": "fact", "content": "用户的密码是123", "evidence": "密码是123456", "about": "user"},
        {"type": "event", "content": "用户屠了龙", "evidence": "屠了龙", "reality": "roleplay"},
    ]}
    ok, dropped, _ = memory.validate(raw, user_text="我住在北京，密码是123456，*屠了龙*", story=False)
    assert [c["content"] for c in ok] == ["用户住在北京", "用户屠了龙"]
    assert ok[1]["reality"] == "story" and ok[1]["type"] == "event"
    assert {d["reason"] for d in dropped} == {"在你的原话里找不到出处", "密码、验证码一类信息不会记住"}


def test_prompt_is_plain_and_has_dialogue_examples():
    """提示词不能自带“AI 助手”腔调，对话示例要放进去（开源角色卡的写法）。"""
    from app.personas import OFFICIAL, validate_behavior
    from app.prompt import build_system
    c = Character(persona=OFFICIAL["persona"], behavior=validate_behavior(OFFICIAL["behavior"]), lore=OFFICIAL["lore"], slug="x")
    ctx = build_system(c, user_name="小林", memories=[], summary=None, lore=[], bond=None, current=None)
    assert ctx.system.startswith("你是「大肥鱼」")
    assert "## 你说话的样子" in ctx.system and "真当我是便宜货啊" in ctx.system
    assert ctx.system.index("## 你说话的样子") > ctx.system.index("</character>")
    for ai_ish in ("领航员", "虚拟角色", "KRINO WORLD 里"):
        assert ai_ish not in ctx.system, ai_ish


def test_tavern_example_dialogue_maps_to_examples():
    d = persona_io.from_card({"spec": "chara_card_v2", "data": {"name": "Lumi", "mes_example": "<START>\n{{user}}: 嗨\n{{char}}: 哟"}})
    assert d.persona["examples"] == "你: 嗨\nLumi: 哟" and d.persona["speech"] == ""


def test_refresh_official_keeps_user_edits(client, user):
    """官方更新：没动过的文字跟着更新，用户换的立绘和改过的文字都保留。"""
    import copy
    from app import personas
    from app.db import SessionLocal
    from app.models import Character as Row
    cid = user.official["id"]
    c = user.ok("get", f"/api/characters/{cid}")
    user.ok("put", f"/api/characters/{cid}", json={"behavior": {**c["behavior"], "portrait": {"kind": "image", "src": "/static/assets/krino.png"}}})
    old = copy.deepcopy(personas.OFFICIAL)
    try:
        personas.OFFICIAL["persona"]["greeting"] = "新的开场白"
        db = SessionLocal()
        personas.refresh_official(db)
        db.close()
        c = user.ok("get", f"/api/characters/{cid}")
        assert c["persona"]["greeting"] == "新的开场白"  # 文字没动过：跟着更新
        assert c["behavior"]["portrait"]["src"] == "/static/assets/krino.png"  # 用户换的立绘保留
        user.ok("put", f"/api/characters/{cid}", json={"persona": {"greeting": "我自己写的"}})
        personas.OFFICIAL["persona"]["greeting"] = "又一版开场白"
        db = SessionLocal()
        personas.refresh_official(db)
        db.close()
        assert user.ok("get", f"/api/characters/{cid}")["persona"]["greeting"] == "我自己写的"  # 改过的文字不覆盖
    finally:
        personas.OFFICIAL.clear(); personas.OFFICIAL.update(old)
        db = SessionLocal(); personas.refresh_official(db); db.close()
    _ = Row


def test_trying_out_the_app_is_not_a_memory():
    """测试语音、问角色能不能听见：说的是产品，不是用户本人的事，不记。"""
    from app.memory import validate

    raw = {"memories": [
        {"type": "preference", "content": "用户希望对方能边听边回", "evidence": "我的意思是让你边听边回", "about": "user"},
        {"type": "preference", "content": "用户喜欢吃辣", "evidence": "我喜欢吃辣", "about": "user"}]}
    ok, dropped, _ = validate(raw, user_text="我的意思是让你边听边回。对了我喜欢吃辣", story=False)
    assert [c["content"] for c in ok] == ["用户喜欢吃辣"]
    assert dropped[0]["reason"] == "是在试功能，不是你自己的事"


def test_forgetting_curve():
    """不重要、很久没提的会淡；重要的、多次提起的牢；固定的不忘。"""
    from datetime import timedelta

    from app.memory import FADE_AT, retention
    from app.models import Memory
    from app.models import now

    t = now()
    def mem(imp, days, mentions=1, pinned=False):
        return Memory(importance=imp, created_at=t - timedelta(days=days), pinned=pinned,
                      source_messages=[f"msg_{i}" for i in range(mentions)])
    assert retention(mem(2, 30)) < FADE_AT          # 不重要的小偏好，一个月没提就淡了
    assert retention(mem(3, 7)) > 0.7               # 普通的，一周还清楚
    assert retention(mem(3, 60, mentions=4)) > 0.4  # 提过好几次的牢得多
    assert retention(mem(5, 180)) > 0.6             # 很重要的半年也记得
    assert retention(mem(1, 999, pinned=True)) == 1


def test_prompt_uses_the_characters_pronoun():
    """生成的角色可以是他、它、TA；老角色没写就照旧用“她”。"""
    from app.models import Character
    from app.prompt import rules_for

    def c(p=None):
        return Character(persona={"pronoun": p} if p else {})
    assert "你就是她，用她的口吻" in rules_for(c())
    assert "你就是他，用他的口吻" in rules_for(c("他"))
    assert "你就是它" in rules_for(c("它")) and "你就是TA" in rules_for(c("TA"))
    assert "{who}" not in rules_for(c("乱写"))
