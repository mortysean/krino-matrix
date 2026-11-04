"""官方精选：服务启动时把官方角色上架到创意工坊（作者是系统账号“KRINO 官方”）。

现在只有两位：大肥鱼（每个新用户默认就有，工坊里可以再领养一份）和 KRINO。按站点版本用中文或英文人设。
按标题去重，重复启动不会重复上架；内容改了就发一个新版本；以前上架过、现在不在列表里的官方作品会下架。
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import persona_io
from .auth import hash_password
from .config import locale
from .models import User, WorkshopItem
from .personas import krino, official, validate_behavior

log = logging.getLogger("krino.catalog")
OFFICIAL_USERNAME = "krino_official"


def picks() -> list[dict]:
    """当前站点版本的官方精选：[{persona, behavior, lore, category}]。"""
    o = official()
    kp, kb = krino()
    return [{**o, "category": "companion"}, {"persona": kp, "behavior": kb, "lore": [], "category": "companion"}]


def _system_user(db: Session) -> User:
    u = db.scalar(select(User).where(User.username == OFFICIAL_USERNAME))
    if u is None:  # 系统账号：随机密码，没人能登录
        u = User(username=OFFICIAL_USERNAME, password_hash=hash_password(secrets.token_urlsafe(32)),
                 display_name="KRINO 官方" if locale() == "zh" else "KRINO Official", settings={})
        db.add(u)
        db.flush()
    return u


def seed(db: Session) -> int:
    """把官方精选上架到工坊。返回新上架或更新的数量。"""
    from .workshop import WorkshopError, _publish_package

    author = _system_user(db)
    zh = locale() == "zh"
    changed, titles = 0, []
    for entry in picks():
        p = entry["persona"]
        titles.append(p["name"])
        pkg = persona_io.to_package(p, validate_behavior(entry["behavior"]), entry["lore"], persona_io.make_slug(p["name"]), 1)
        item = db.scalar(select(WorkshopItem).where(WorkshopItem.author_id == author.id, WorkshopItem.title == p["name"]))
        try:
            item = _publish_package(db, author, pkg, item=item, title=p["name"], tagline=p["tagline"],
                                    description="KRINO 官方角色" if zh else "Official KRINO character",
                                    category=entry["category"], tags=p["tags"], changelog="官方" if zh else "Official",
                                    color=p["color"], source_character_id=None, forked_from=None, check_duplicates=False)
            changed += 1
        except WorkshopError:
            pass  # 内容没变
        item.status, item.status_note = "published", None  # 官方角色不需要审核
    # 以前上架过、现在不在列表里的官方作品：下架（已经领养的人不受影响）
    for old in db.scalars(select(WorkshopItem).where(WorkshopItem.author_id == author.id, WorkshopItem.title.not_in(titles),
                                                     WorkshopItem.status != "removed")):
        old.status, old.status_note = "removed", "官方精选调整" if zh else "Retired official pick"
        changed += 1
    db.commit()
    if changed:
        log.info("官方精选：上架 / 更新 / 下架了 %d 个", changed)
    return changed
