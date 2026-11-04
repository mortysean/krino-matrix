"""海外版（SITE_EDITION=global）：英文默认角色、英文提示词、报错翻译、英文语音音色。

测试进程整体是国内版；这里临时把 settings.edition 切到 global，结束后切回。
"""
import pytest

from app.config import settings


@pytest.fixture
def global_edition():
    from app import i18n
    old = settings.edition
    settings.edition = "global"
    i18n._table.cache_clear()
    yield
    settings.edition = old
    i18n._table.cache_clear()


def test_site_info_cn(client):
    s = client.get("/api/site").json()
    assert s["edition"] == "cn" and s["locale"] == "zh" and s["company"] == "杭州决策矩阵科技有限公司"


def test_global_edition_is_english(client, global_edition):
    from tests.conftest import make_user
    s = client.get("/api/site").json()
    assert s["edition"] == "global" and s["locale"] == "en" and s["icp"] == ""
    u = make_user(client)
    c = u.official
    assert c["name"] == "Whale-chan" and "rice" in c["tagline"]
    full = u.ok("get", f"/api/characters/{c['id']}")
    assert full["behavior"]["voice"]["voice"] == "dafeiyu-en"  # 按人设设计的音色（语音服务不在时退回 Kokoro af_maple）
    # 提示词是英文的
    from app.models import Character
    from app.personas import validate_behavior
    from app.prompt import build_system
    ch = Character(persona=full["persona"], behavior=validate_behavior(full["behavior"]), lore=full["lore"], slug="x")
    sys_prompt = build_system(ch, user_name="Lin", memories=[], summary=None, lore=[], bond=None, current=None).system
    assert sys_prompt.startswith('You are "Whale-chan"') and "Reply in English." in sys_prompt and "## How you talk" in sys_prompt
    assert not any("一" <= ch <= "鿿" for ch in sys_prompt.replace(full["persona"]["name"], ""))  # 没有中文
    # 聊天和记忆走英文
    sid = u.session(c["id"])
    r = u.say(sid, "Call me Lin. I live in Seattle.")
    assert r["reply"]["content"] and r["job"]["status"] == "done"
    assert {m["content"] for m in u.memories(c["id"])} >= {'The user wants to be called "Lin"', "The user lives in Seattle"}
    # 报错翻译成英文（翻译表里有的话）；没有的保持原样
    r = u.get("/api/characters/nope")
    assert r.status_code == 404
    from app.i18n import _table
    if "角色不存在" in _table()[0]:
        assert r.json()["detail"] == _table()[0]["角色不存在"]


def test_global_tts_voices(global_edition):
    from app import tts_local
    if not tts_local.available()[0]:
        pytest.skip("没有本地语音模型")
    assert set(tts_local.voices()) <= {"af_maple", "af_sol", "bf_vale"} and tts_local.default_voice() == "af_maple"
