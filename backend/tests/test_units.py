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
