"""外观工作台走 OpenRouter：画新角色用 IMAGE_MODEL，改图用 IMAGE_EDIT_MODEL（带参考图）；画新角色的模型被账号排除时改用改图模型。"""
import base64
import io
import json

import httpx
from PIL import Image

from app import workbench
from app.config import settings


def _png() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (8, 12), "white").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _fake(monkeypatch, blocked=()):
    calls = []

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body)
        if body["model"] in blocked:
            return httpx.Response(404, json={"error": {"code": 404, "message": "0 endpoints out of 1 requested are available"}})
        return httpx.Response(200, json={"data": [{"b64_json": _png(), "media_type": "image/png"}], "usage": {"cost": 0.04}})

    real = httpx.Client
    monkeypatch.setattr(workbench.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(settings, "image_provider", "openrouter")
    monkeypatch.setattr(settings, "image_model", "openai/gpt-image-2.6-sunburst")
    monkeypatch.setattr(settings, "image_edit_model", "bytedance-seed/seedream-5-5")
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    return calls


def test_design_and_edit_use_their_own_models(monkeypatch):
    calls = _fake(monkeypatch)
    raw, used, cny = workbench._generate([{"text": "一个女孩"}], 2, "768*1152")
    assert len(raw) == 2 and used == "openai/gpt-image-2.6-sunburst" and abs(cny - 2 * 0.04 * settings.usd_cny) < 1e-9
    assert all(c["aspect_ratio"] == "2:3" and c["n"] == 1 and "input_references" not in c for c in calls)

    calls.clear()
    raw, used, _ = workbench._generate([{"image": "data:image/jpeg;base64,AAAA"}, {"text": "换成红头发"}], 1, "768*1152", edit=True)
    assert used == "bytedance-seed/seedream-5-5"
    assert calls[0]["input_references"] == [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}}]
    assert calls[0]["prompt"] == "换成红头发"


def test_blocked_design_model_falls_back_to_edit_model(monkeypatch):
    calls = _fake(monkeypatch, blocked={"openai/gpt-image-2.6-sunburst"})
    raw, used, _ = workbench._generate([{"text": "一个女孩"}], 1, "768*1152")
    assert raw and used == "bytedance-seed/seedream-5-5"
    assert [c["model"] for c in calls] == ["openai/gpt-image-2.6-sunburst", "bytedance-seed/seedream-5-5"]


def test_aspect_ratio_from_size():
    assert workbench._aspect("768*1152") == "2:3" and workbench._aspect("1024*1024") == "1:1" and workbench._aspect("1152*768") == "3:2"
