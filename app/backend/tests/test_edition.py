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


class _Resp:
    def __init__(self, status=200, json=None, content=b"", ctype="audio/wav"):
        self.status_code, self._json, self.content, self.text = status, json, content, str(json)
        self.headers = {"content-type": ctype}

    def json(self):
        return self._json


class _FakeClient:
    """记录请求、按顺序给出响应的 httpx.Client 替身。"""
    def __init__(self, responses, calls):
        self.responses, self.calls = responses, calls

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json))
        return self.responses.pop(0)

    def get(self, url):
        self.calls.append(("GET", url, None))
        return self.responses.pop(0)


def _fake(monkeypatch, responses):
    from app import voice
    calls = []
    monkeypatch.setattr(voice, "_client", lambda timeout=60: _FakeClient(responses, calls))
    return calls


def test_dashscope_tts_uses_persona_voice(monkeypatch):
    from app import voice
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    calls = _fake(monkeypatch, [_Resp(json={"output": {"audio": {"url": "https://oss.example/a.wav", "data": ""}}}),
                                _Resp(content=b"RIFFwav")])
    audio, mime = voice.synthesize("本肥鱼饿了", "zf_017", 1.0)  # 以前存的 Kokoro 编号也能认出是大肥鱼
    assert audio == b"RIFFwav" and mime == "audio/wav"
    body = calls[0][2]
    assert calls[0][1].endswith("/services/audio/tts/SpeechSynthesizer") and body["model"] == "qwen-audio-3.1-tts-plus"
    assert body["input"]["voice"] == "longanhuan_v3.1" and "傲娇" in body["input"]["instruction"]
    assert calls[1] == ("GET", "https://oss.example/a.wav", None)
    assert voice._tts_config()["voices"] == ["dafeiyu-zh", "krino-zh"]


def test_tts_skips_actions_and_kaomoji(monkeypatch):
    from app import voice
    assert voice.speakable("（歪头）才不胖 (╯°□°）╯︵ ┻━┻ *叉腰* 好呀～(〃∀〃)💕") == "才不胖 好呀"
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    calls = _fake(monkeypatch, [_Resp(json={"output": {"audio": {"data": "UklGRg=="}}})])
    voice.synthesize("哼 (｀・ω・´)", "dafeiyu-zh", 1.0)
    assert calls[0][2]["input"]["text"] == "哼"
    with pytest.raises(voice.ServiceError):
        voice.synthesize("(￣▽￣)", "dafeiyu-zh", 1.0)


def test_dashscope_legacy_model(monkeypatch):
    from app import voice
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "dashscope_tts_model", "qwen3-tts-instruct-flash")
    monkeypatch.setattr(settings, "dashscope_workspace", "ws1")
    calls = _fake(monkeypatch, [_Resp(json={"output": {"audio": {"data": "UklGRg=="}}})])
    assert voice.synthesize("你好", "krino-zh", 1.0) == (b"RIFF", "audio/wav")
    body = calls[0][2]
    assert calls[0][1].endswith("/services/aigc/multimodal-generation/generation")
    assert body["input"]["voice"] == "Serena" and "instructions" in body["input"]


def test_dashscope_workspace_domain(monkeypatch):
    from app import voice
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    monkeypatch.setattr(settings, "dashscope_workspace", "ws1")
    calls = _fake(monkeypatch, [_Resp(json={"output": {"audio": {"data": "UklGRg=="}}})])
    voice.synthesize("你好", "krino-zh", 1.0)
    assert calls[0][1] == "https://ws1.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer"
    assert calls[0][2]["input"]["voice"] == "longanlingxin_v3.1"


def test_elevenlabs_tts(monkeypatch):
    from app import voice
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "xi-test")
    calls = _fake(monkeypatch, [_Resp(content=b"ID3mp3", ctype="audio/mpeg")])
    assert voice.synthesize("你好", "krino-zh", 2.0) == (b"ID3mp3", "audio/mpeg")
    assert "/text-to-speech/Xb7hH8MSUJpSbSDYk0k2" in calls[0][1]
    assert calls[0][2]["model_id"] == "eleven_v4" and calls[0][2]["voice_settings"]["speed"] == 1.2
    assert voice._tts_config()["provider"] == "elevenlabs"


def test_openai_tts_global(monkeypatch, global_edition):
    from app import voice
    monkeypatch.setattr(settings, "tts_provider", "openai")
    monkeypatch.setattr(settings, "tts_api_key", "sk-test")
    calls = _fake(monkeypatch, [_Resp(content=b"ID3mp3", ctype="audio/mpeg")])
    audio, mime = voice.synthesize("Hi there", "krino-en", 1.0)
    assert audio == b"ID3mp3" and mime == "audio/mpeg"
    body = calls[0][2]
    assert body["voice"] == "sage" and body["model"] == "gpt-4o-mini-tts" and "researcher" in body["instructions"]


def test_cloud_tts_falls_back_to_kokoro(monkeypatch):
    from app import tts_local, voice
    monkeypatch.setattr(settings, "tts_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "test-key")
    _fake(monkeypatch, [_Resp(status=401, json={"code": "InvalidApiKey"})])
    monkeypatch.setattr(tts_local, "available", lambda: (True, ""))
    monkeypatch.setattr(tts_local, "synthesize", lambda text, voice, speed: b"kokoro")
    assert voice.synthesize("你好", "dafeiyu-zh", 1.0) == (b"kokoro", "audio/wav")


def test_landing_page(client):
    r = client.get("/landing/")
    assert r.status_code == 200 and "cn.krinomatrix.com" in r.text and "/static/assets/krino-mark.svg" in r.text
    assert client.get("/static/assets/krino-mark.svg").status_code == 200
