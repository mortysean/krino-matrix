"""像素小人：官方角色是手调的；新建角色和形象、声音一起定下来；已有的、改过设定的角色打开小镇时后台补；只认得给定的选项。"""
import time

from app import pixel
from app.db import SessionLocal
from app.models import Character


def _town_cast(u):
    return {c["id"]: c for c in u.ok("get", "/api/social/town")["cast"]}


def test_officials_have_their_own_look(user):
    cast = _town_cast(user)
    k, w = cast[user.krino["id"]]["pixel"], cast[user.official["id"]]["pixel"]
    assert "glasses" in k["extras"] and k["style"] == "low_tie"
    assert {"fins", "tail"} <= set(w["extras"]) and w["hair2"]


def test_new_character_gets_a_pixel_figure_at_creation(user):
    """一句话新建角色：像素小人和立绘、声音一起做好，按设定里的样子（这里离线模型按关键词：白发、猫耳、眼镜）。"""
    r = user.ok("post", "/api/workbench/character", json={"prompt": "一个白发、戴眼镜的猫娘图书管理员", "wait": True})
    px = r["character"]["behavior"]["pixel"]
    assert px["hair"] == "#eceef4" and {"cat_ears", "glasses"} <= set(px["extras"]) and px["src"]
    assert _town_cast(user)[r["character"]["id"]]["pixel"]["extras"] == px["extras"]


def test_existing_character_is_filled_in_and_redone_after_edits(user):
    """没有像素小人的角色：打开小镇时后台补；改了外貌设定，再打开就按新的重新定。"""
    db = SessionLocal()
    c = Character(owner_id=user.info["id"], slug="t-px", public_id="KR-PIXEL1", persona={"name": "小狐", "tagline": "红发双马尾的狐狸巫女", "color": "#c8423c"},
                  behavior={}, lore=[], origin={"source": "created"})
    db.add(c)
    db.commit()
    cid = c.id
    db.close()

    def wait_pixel(pred):
        for _ in range(50):
            px = _town_cast(user)[cid]["pixel"]
            if px and pred(px):
                return px
            time.sleep(0.1)
        raise AssertionError(_town_cast(user)[cid]["pixel"])

    px = wait_pixel(lambda p: True)
    assert px["hair"] == "#c8423c" and px["style"] == "twin" and "fox_ears" in px["extras"]
    db = SessionLocal()
    c = db.get(Character, cid)
    c.persona = {**c.persona, "tagline": "金发短发、戴耳机的狐狸巫女"}
    db.commit()
    db.close()
    px = wait_pixel(lambda p: p["hair"] == "#f2cf5b")
    assert px["style"] == "short" and "headphones" in px["extras"]


def test_only_known_options_survive():
    out = pixel.clean({"hair": "red", "hair2": "#ABCDEF", "style": "mohawk", "bottom": "dress", "extras": ["glasses", "laser", "glasses"], "top": "#12345"})
    assert out == {"hair2": "#abcdef", "bottom": "dress", "extras": ["glasses"]}
