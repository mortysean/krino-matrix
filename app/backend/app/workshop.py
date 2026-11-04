"""创意工坊：所有用户共享的公开人设库。公开内容只有人设包（krino-persona/1），私人记忆、聊天、关系永远不会进工坊。

    我的角色 ──发布──▶ 工坊作品（每次更新是一个新版本）    人设包文件 ──上传──▶ 工坊作品
    工坊作品 ──导入──▶ 我名下的一位新角色；作者更新后可以一键更新（本地改过的要确认覆盖）
    评分、评论、举报；被足够多的人举报先自动隐藏；管理员可以审核（待审核 → 上架）、隐藏、下架。
第一版不做付费和推荐算法：排序只有最新 / 最热 / 好评 / 导入最多。
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import persona_io, personas
from .auth import current_user, is_admin
from .config import settings
from .db import get_db
from .models import (Character, User, WorkshopComment, WorkshopInstall, WorkshopItem, WorkshopReport, WorkshopVersion,
                     WorkshopVote, now)
from .persona_io import PersonaError, check_content

router = APIRouter(prefix="/api/workshop", tags=["workshop"])

CATEGORIES = {"companion": "日常陪伴", "fantasy": "奇幻冒险", "healing": "治愈", "comedy": "搞笑",
              "study": "学习伙伴", "scifi": "科幻", "other": "其他"}
REASONS = {"explicit": "露骨或成人内容", "real_person": "真实人物", "copyright": "侵权 / 搬运",
           "harmful": "有害或歧视内容", "spam": "广告或刷屏", "other": "其他"}
STATUS_LABELS = {"pending": "待审核", "published": "已上架", "hidden": "暂时隐藏", "removed": "已下架"}
SORTS = ("new", "hot", "top", "installs")
PAGE = 24
MAX_PUBLISH_PER_DAY = 20
MAX_COMMENTS_PER_HOUR = 30


class WorkshopError(ValueError):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def package_hash(pkg: dict) -> str:
    """内容哈希：不算 id 和 version（装到别人那里会变）。"""
    core = {k: pkg.get(k) for k in ("persona", "behavior", "lore")}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _item(db: Session, item_id: str) -> WorkshopItem:
    i = db.get(WorkshopItem, item_id)
    if i is None:
        raise WorkshopError("作品不存在", 404)
    return i


def _visible(i: WorkshopItem, user: User) -> bool:
    return i.status == "published" or i.author_id == user.id or is_admin(user)


def _latest(db: Session, i: WorkshopItem) -> WorkshopVersion:
    return db.scalar(select(WorkshopVersion).where(WorkshopVersion.item_id == i.id)
                     .order_by(WorkshopVersion.version.desc()).limit(1))


def card(db: Session, i: WorkshopItem, user: User, inst: WorkshopInstall | None = None) -> dict:
    author = db.get(User, i.author_id)
    votes = i.up + i.down
    return {"id": i.id, "title": i.title, "tagline": i.tagline, "category": i.category,
            "category_label": CATEGORIES.get(i.category, "其他"), "tags": i.tags or [], "color": i.color,
            "author": author.display_name if author else "?", "own": i.author_id == user.id, "version": i.latest_version,
            "status": i.status, "status_label": STATUS_LABELS[i.status], "status_note": i.status_note,
            "installs": i.installs, "up": i.up, "down": i.down, "comments": i.comments,
            "rating": round(i.up / votes, 2) if votes else None, "forked_from": i.forked_from,
            "updated_at": i.updated_at.isoformat(),
            "installed": {"character_id": inst.character_id, "version": inst.installed_version,
                          "update": inst.installed_version < i.latest_version} if inst else None}


# ---------- 发布 ----------

_official_hash: str | None = None


def official_hash() -> str:
    """没改过的官方角色的内容哈希。"""
    global _official_hash
    if _official_hash is None:
        o = personas.OFFICIAL
        _official_hash = package_hash(persona_io.to_package(o["persona"], personas.validate_behavior(o["behavior"]),
                                                            persona_io._clean_lore(o["lore"]), personas.OFFICIAL_SLUG, 1))
    return _official_hash


def _check_rate(db: Session, user: User) -> None:
    n = db.scalar(select(func.count()).select_from(WorkshopVersion).join(WorkshopItem)
                  .where(WorkshopItem.author_id == user.id, WorkshopVersion.created_at > now() - timedelta(days=1)))
    if n >= MAX_PUBLISH_PER_DAY:
        raise WorkshopError("今天发布得太多了，明天再来吧", 429)


def _publish_package(db: Session, user: User, pkg: dict, *, item: WorkshopItem | None, title: str, tagline: str,
                     description: str, category: str, tags: list[str], changelog: str, color: str,
                     source_character_id: str | None, forked_from: str | None,
                     check_duplicates: bool = True) -> WorkshopItem:
    if category not in CATEGORIES:
        raise WorkshopError("分类不对")
    check_content(title, tagline, description, " ".join(tags))
    digest = package_hash(pkg)
    if check_duplicates:
        if digest == official_hash():
            raise WorkshopError("官方角色不能原样发布。先在“人格”里改出你自己的版本，再发布吧")
        # 同样的内容已经在工坊里（不管谁发的）：不再重复上架，免得工坊里全是一模一样的角色
        dup = db.scalar(select(WorkshopItem.title).join(WorkshopVersion, WorkshopVersion.item_id == WorkshopItem.id)
                        .where(WorkshopVersion.content_hash == digest, WorkshopVersion.version == WorkshopItem.latest_version,
                               WorkshopItem.status != "removed", WorkshopItem.id != (item.id if item else "")).limit(1))
        if dup:
            raise WorkshopError(f"工坊里已经有一模一样的角色「{dup}」了，改出一些不同再发布吧")
    if item is None:
        item = WorkshopItem(author_id=user.id, source_character_id=source_character_id, forked_from=forked_from,
                            latest_version=1, status="pending" if settings.workshop_require_review else "published",
                            title=title[:40])
        db.add(item)
        db.flush()
        version = 1
    else:
        last = _latest(db, item)
        if last and last.content_hash == digest:
            raise WorkshopError("内容和上一个版本一样，没有可以更新的")
        version = item.latest_version + 1
        item.latest_version = version
        if settings.workshop_require_review and item.status == "published":
            item.status = "pending"
    item.title, item.tagline, item.description = title[:40], tagline[:80], description[:4000]
    item.category, item.tags, item.color, item.updated_at = category, [t[:12] for t in tags][:8], color[:16], now()
    db.add(WorkshopVersion(item_id=item.id, version=version, changelog=changelog[:500],
                           package={**pkg, "version": version}, content_hash=digest))
    db.flush()
    return item


def publish_character(db: Session, user: User, c: Character, **meta) -> WorkshopItem:
    _check_rate(db, user)
    pkg = personas.package_of(c)
    origin = (c.origin or {}).get("workshop") or {}
    src = db.get(WorkshopItem, origin["item"]) if origin.get("item") else None
    own = src is not None and src.author_id == user.id and src.status != "removed"
    if src is not None and not own:
        same = db.scalar(select(WorkshopVersion.id).where(WorkshopVersion.item_id == src.id,
                                                          WorkshopVersion.content_hash == package_hash(pkg)))
        if same:
            raise WorkshopError("和原作一模一样。先改一些地方，再作为衍生作品发布")
    item = _publish_package(db, user, pkg, item=src if own else None, source_character_id=c.id,
                            forked_from=src.id if src is not None and not own else None,
                            color=(c.persona or {}).get("color") or "#1414a8", **meta)
    c.origin = {**(c.origin or {}), "workshop": {"item": item.id, "version": item.latest_version, "own": True}}
    return item


# ---------- 导入与更新 ----------

def install(db: Session, user: User, i: WorkshopItem) -> dict:
    if not _visible(i, user) or i.status != "published" and i.author_id != user.id:
        raise WorkshopError("这个作品现在不能导入", 403)
    have = db.get(WorkshopInstall, (user.id, i.id))
    if have and db.get(Character, have.character_id):
        raise WorkshopError("你已经导入过这个作品了")
    v = _latest(db, i)
    d = persona_io.from_package(v.package)
    c = personas.install_draft(db, user, d, {"source": "workshop",
                                              "workshop": {"item": i.id, "version": v.version, "own": False}})
    if have:
        db.delete(have)
        db.flush()
    db.add(WorkshopInstall(user_id=user.id, item_id=i.id, character_id=c.id, installed_version=v.version,
                           installed_hash=v.content_hash))
    i.installs += 1
    db.flush()
    return personas.summary(c)


def update_install(db: Session, user: User, i: WorkshopItem, force: bool) -> dict:
    inst = db.get(WorkshopInstall, (user.id, i.id))
    c = db.get(Character, inst.character_id) if inst else None
    if inst is None or c is None:
        raise WorkshopError("你还没有导入这个作品")
    v = _latest(db, i)
    if v.version <= inst.installed_version:
        return {"updated": False, "reason": "已经是最新版本"}
    if package_hash(personas.package_of(c)) != inst.installed_hash and not force:
        return {"updated": False, "conflict": True, "reason": "你在本地改过这个角色，更新会覆盖你的修改（会先存一个版本）"}
    d = persona_io.from_package(v.package)
    personas.save(db, c, persona=d.persona, behavior=d.behavior, lore=d.lore, note=f"工坊更新到 v{v.version}")
    c.origin = {**(c.origin or {}), "workshop": {"item": i.id, "version": v.version, "own": False}}
    inst.installed_version, inst.installed_hash = v.version, v.content_hash
    return {"updated": True, "version": v.version}


def vote(db: Session, user: User, i: WorkshopItem, value: int) -> None:
    row = db.get(WorkshopVote, (user.id, i.id))
    if row:
        i.up -= row.value == 1
        i.down -= row.value == -1
        if value == 0 or value == row.value:
            db.delete(row)
            return
        row.value = value
    elif value:
        db.add(WorkshopVote(user_id=user.id, item_id=i.id, value=value))
    i.up += value == 1
    i.down += value == -1


def report(db: Session, user: User, i: WorkshopItem, reason: str, detail: str, comment_id: str | None) -> dict:
    if not _visible(i, user):
        raise WorkshopError("作品不存在", 404)
    if reason not in REASONS:
        raise WorkshopError("举报原因不对")
    if comment_id:
        c = db.get(WorkshopComment, comment_id)
        if c is None or c.item_id != i.id:
            raise WorkshopError("评论不存在", 404)
    dup = db.scalar(select(WorkshopReport.id).where(WorkshopReport.item_id == i.id, WorkshopReport.user_id == user.id,
                                                    WorkshopReport.comment_id == comment_id, WorkshopReport.status == "open"))
    if dup:
        return {"ok": True, "duplicate": True}
    db.add(WorkshopReport(item_id=i.id, user_id=user.id, reason=reason, detail=detail[:500], comment_id=comment_id))
    db.flush()
    n = db.scalar(select(func.count(func.distinct(WorkshopReport.user_id))).where(
        WorkshopReport.item_id == i.id, WorkshopReport.status == "open", WorkshopReport.comment_id.is_(None)))
    if comment_id is None and n >= settings.workshop_auto_hide_reports and i.status == "published":
        i.status, i.status_note = "hidden", "被多人举报，等待复核"
    return {"ok": True}


# ---------- 接口 ----------

def _run(fn):
    try:
        return fn()
    except WorkshopError as e:
        raise HTTPException(e.status, str(e)) from e
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e


def _admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(403, "只有管理员可以处理")


@router.get("/meta")
def meta(user: User = Depends(current_user)):
    return {"categories": CATEGORIES, "reasons": REASONS, "sorts": SORTS, "statuses": STATUS_LABELS,
            "admin": is_admin(user), "require_review": settings.workshop_require_review}


@router.get("/items")
def browse(q: str = "", category: str = "", tag: str = "", sort: str = "new", page: int = 1, mine: bool = False,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    qry = select(WorkshopItem)
    if mine:
        qry = qry.where(WorkshopItem.author_id == user.id, WorkshopItem.status != "removed")
    else:
        qry = qry.where(WorkshopItem.status == "published")
    if q.strip():
        like = f"%{q.strip()[:40]}%"
        qry = qry.where(or_(WorkshopItem.title.ilike(like), WorkshopItem.tagline.ilike(like),
                            WorkshopItem.description.ilike(like), WorkshopItem.tags.any(q.strip()[:12])))
    if category in CATEGORIES:
        qry = qry.where(WorkshopItem.category == category)
    if tag:
        qry = qry.where(WorkshopItem.tags.any(tag[:12]))
    order = {"new": WorkshopItem.updated_at.desc(), "top": (WorkshopItem.up - WorkshopItem.down).desc(),
             "installs": WorkshopItem.installs.desc(),
             "hot": (WorkshopItem.installs * 2 + WorkshopItem.up + WorkshopItem.comments).desc()}.get(sort, WorkshopItem.updated_at.desc())
    page = max(1, page)
    rows = db.scalars(qry.order_by(order, WorkshopItem.id).offset((page - 1) * PAGE).limit(PAGE + 1)).all()
    installs = {r.item_id: r for r in db.scalars(select(WorkshopInstall).where(WorkshopInstall.user_id == user.id))}
    tags = db.execute(select(func.unnest(WorkshopItem.tags).label("t"), func.count()).where(WorkshopItem.status == "published")
                      .group_by("t").order_by(func.count().desc()).limit(20)).all()
    return {"items": [card(db, i, user, installs.get(i.id)) for i in rows[:PAGE]], "more": len(rows) > PAGE,
            "tags": [{"tag": t, "count": n} for t, n in tags]}


@router.get("/items/{item_id}")
def detail(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _run(lambda: _item(db, item_id))
    if not _visible(i, user):
        raise HTTPException(404, "作品不存在")
    v = _latest(db, i)
    p = v.package.get("persona") or {}
    versions = db.scalars(select(WorkshopVersion).where(WorkshopVersion.item_id == i.id).order_by(WorkshopVersion.version.desc()))
    comments = db.execute(select(WorkshopComment, User.display_name).join(User, User.id == WorkshopComment.user_id)
                          .where(WorkshopComment.item_id == i.id, WorkshopComment.status == "visible")
                          .order_by(WorkshopComment.created_at.desc()).limit(100)).all()
    my_vote = db.get(WorkshopVote, (user.id, i.id))
    return {**card(db, i, user, db.get(WorkshopInstall, (user.id, i.id))), "description": i.description,
            "preview": {"persona": {k: p.get(k) for k in ("name", "tagline", "background", "personality", "speech",
                                                          "interests", "worldview", "greeting")},
                        "style": (v.package.get("behavior") or {}).get("style"),
                        "lore": [x.get("name") for x in v.package.get("lore") or []]},
            "versions": [{"version": x.version, "changelog": x.changelog, "at": x.created_at.isoformat()} for x in versions],
            "comments": [{"id": c.id, "body": c.body, "author": name, "own": c.user_id == user.id,
                          "at": c.created_at.isoformat()} for c, name in comments],
            "my_vote": my_vote.value if my_vote else 0, "admin": is_admin(user)}


@router.get("/items/{item_id}/download")
def download(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _run(lambda: _item(db, item_id))
    if not _visible(i, user):
        raise HTTPException(404, "作品不存在")
    v = _latest(db, i)
    return Response(json.dumps(v.package, ensure_ascii=False, indent=2).encode(), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{v.package.get("id", "persona")}.krino.json"'})


class PublishIn(BaseModel):
    character_id: str
    title: str | None = Field(default=None, max_length=40)
    tagline: str | None = Field(default=None, max_length=80)
    description: str = Field(default="", max_length=4000)
    category: str = "other"
    tags: list[str] = Field(default_factory=list, max_length=8)
    changelog: str = Field(default="", max_length=500)


@router.post("/publish")
def publish(body: PublishIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = personas.get_owned(db, user, body.character_id)
    item = _run(lambda: publish_character(
        db, user, c, title=body.title or c.name, tagline=body.tagline if body.tagline is not None else c.persona.get("tagline", ""),
        description=body.description, category=body.category, tags=body.tags or c.persona.get("tags") or [],
        changelog=body.changelog))
    db.commit()
    return card(db, item, user)


@router.post("/upload")
async def upload(file: UploadFile = File(...), category: str = Form("other"), description: str = Form(""),
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    """直接上传一个人设包 / 角色卡发布到工坊（不用先导入成自己的角色）。"""
    data = await personas._read_upload(file)

    def run():
        _check_rate(db, user)
        d = persona_io.parse_any(file.filename or "", data)
        pkg = persona_io.to_package(d.persona, personas.validate_behavior(d.behavior), d.lore, d.slug, 1)
        return _publish_package(db, user, pkg, item=None, title=d.persona["name"], tagline=d.persona.get("tagline", ""),
                                description=description[:4000], category=category, tags=d.persona.get("tags") or [],
                                changelog="上传", color=d.persona.get("color") or "#1414a8",
                                source_character_id=None, forked_from=None)
    item = _run(run)
    db.commit()
    return card(db, item, user)


@router.post("/items/{item_id}/install")
def install_item(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _run(lambda: install(db, user, _item(db, item_id)))
    db.commit()
    return r


@router.post("/items/{item_id}/update")
def update_item(item_id: str, force: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _run(lambda: update_install(db, user, _item(db, item_id), force))
    db.commit()
    return r


@router.delete("/items/{item_id}")
def withdraw(item_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _run(lambda: _item(db, item_id))
    if i.author_id != user.id:
        raise HTTPException(403, "只能撤下自己的作品")
    i.status, i.status_note = "removed", "作者撤下"
    db.commit()
    return {"ok": True}


class VoteIn(BaseModel):
    value: int = Field(ge=-1, le=1)


@router.post("/items/{item_id}/vote")
def vote_item(item_id: str, body: VoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _run(lambda: _item(db, item_id))
    if not _visible(i, user):
        raise HTTPException(404, "作品不存在")
    if i.author_id == user.id:
        raise HTTPException(400, "不能给自己的作品评分")
    vote(db, user, i, body.value)
    db.commit()
    return {"up": i.up, "down": i.down}


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=1000)


@router.post("/items/{item_id}/comments")
def comment(item_id: str, body: CommentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _run(lambda: _item(db, item_id))
    if not _visible(i, user):
        raise HTTPException(404, "作品不存在")
    n = db.scalar(select(func.count()).select_from(WorkshopComment).where(
        WorkshopComment.user_id == user.id, WorkshopComment.created_at > now() - timedelta(hours=1)))
    if n >= MAX_COMMENTS_PER_HOUR:
        raise HTTPException(429, "评论太频繁了，歇一会儿")
    _run(lambda: check_content(body.body))
    c = WorkshopComment(item_id=i.id, user_id=user.id, body=body.body.strip())
    db.add(c)
    i.comments += 1
    db.commit()
    return {"id": c.id}


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(WorkshopComment, comment_id)
    if c is None or (c.user_id != user.id and not is_admin(user)):
        raise HTTPException(404, "评论不存在")
    if c.status == "visible":
        c.status = "removed"
        i = db.get(WorkshopItem, c.item_id)
        i.comments = max(0, i.comments - 1)
    db.commit()
    return {"ok": True}


class ReportIn(BaseModel):
    reason: str
    detail: str = Field(default="", max_length=500)
    comment_id: str | None = None


@router.post("/items/{item_id}/report")
def report_item(item_id: str, body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    r = _run(lambda: report(db, user, _item(db, item_id), body.reason, body.detail, body.comment_id))
    db.commit()
    return r


@router.get("/reports")
def reports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(user)
    rows = db.execute(select(WorkshopReport, WorkshopItem.title, WorkshopItem.status)
                      .join(WorkshopItem, WorkshopItem.id == WorkshopReport.item_id)
                      .where(WorkshopReport.status == "open").order_by(WorkshopReport.created_at.desc()).limit(200)).all()
    pending = db.scalars(select(WorkshopItem).where(WorkshopItem.status == "pending").order_by(WorkshopItem.updated_at)).all()
    return {"reports": [{"id": r.id, "item_id": r.item_id, "title": t, "item_status": s, "reason": REASONS.get(r.reason, r.reason),
                         "detail": r.detail, "comment_id": r.comment_id, "at": r.created_at.isoformat()} for r, t, s in rows],
            "pending": [card(db, i, user) for i in pending]}


class ResolveIn(BaseModel):
    action: str = Field(pattern="^(dismiss|hide|remove)$")


@router.post("/reports/{report_id}")
def resolve(report_id: str, body: ResolveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(user)
    r = db.get(WorkshopReport, report_id)
    if r is None:
        raise HTTPException(404, "举报不存在")
    i = db.get(WorkshopItem, r.item_id)
    same = db.scalars(select(WorkshopReport).where(WorkshopReport.item_id == r.item_id, WorkshopReport.status == "open",
                                                   WorkshopReport.comment_id == r.comment_id)).all()
    for x in same:
        x.status = "dismissed" if body.action == "dismiss" else "actioned"
    if r.comment_id and body.action != "dismiss":
        c = db.get(WorkshopComment, r.comment_id)
        if c and c.status == "visible":
            c.status, i.comments = "removed", max(0, i.comments - 1)
    elif body.action == "dismiss" and i.status == "hidden" and i.status_note == "被多人举报，等待复核":
        i.status, i.status_note = "published", None
    elif body.action in ("hide", "remove"):
        i.status, i.status_note = ("hidden", "管理员隐藏") if body.action == "hide" else ("removed", "管理员下架")
    db.commit()
    return {"ok": True}


class ModerateIn(BaseModel):
    status: str = Field(pattern="^(published|hidden|removed)$")
    note: str = Field(default="", max_length=200)


@router.post("/items/{item_id}/moderate")
def moderate(item_id: str, body: ModerateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _admin(user)
    i = _run(lambda: _item(db, item_id))
    i.status, i.status_note = body.status, body.note or None
    db.commit()
    return card(db, i, user)
