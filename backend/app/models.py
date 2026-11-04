"""PostgreSQL 表结构：KRINO WORLD 的全部数据（用户、人设、记忆、聊天、创意工坊、3D 模型、运行事件）。

改了这里要同时加一个 alembic 迁移：
    scripts/world.sh db revision "说明"      # 自动生成，检查后提交
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> Mapped[str]:
    return mapped_column(String(32), primary_key=True, default=new_id)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=now)


DEFAULT_USER_SETTINGS: dict = {
    # 敏感个人信息（健康、财务、证件等）总是先进“想问你的”；打开后，确认过的敏感记忆才会用于聊天
    "save_sensitive": False,
    "privacy": {"camera": False, "microphone": False},
    "voice": {"stt": "auto", "tts": "auto", "autoplay": True, "voice": ""},
    "interaction": {"proactive": True, "idle_seconds": 45, "animations": True, "stories": True},
    "evaluator": {"mode": None},  # None = 跟随服务端 KRINO_POLICY
}


# ---------- 用户 ----------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = _id()
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str | None] = mapped_column(String(64))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---------- 人设 ----------

class Character(Base):
    """一个角色的人格配置。owner_id 为空的是官方角色（模板）；用户的角色都是自己名下的一份。

    persona：名称、简介、背景、性格、价值倾向、语言风格、兴趣、行为偏好、世界观、角色关系……（personas.FIELDS）
    behavior：结构化的互动偏好，交给互动策略和 3D 形象（表情、动作、话量、语音参数）
    lore：设定笔记 [{name, content, keys}]
    私人记忆不在这里，在 memories 表，导出人设不会带上。
    """

    __tablename__ = "characters"

    id: Mapped[str] = _id()
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(64))  # 人类可读的 ID，同一个主人下唯一
    persona: Mapped[dict] = mapped_column(JSONB, default=dict)
    behavior: Mapped[dict] = mapped_column(JSONB, default=dict)
    lore: Mapped[list] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)  # 人格核心版本，每次明确保存 +1
    origin: Mapped[dict] = mapped_column(JSONB, default=dict)  # {source, template, workshop:{item, version, own}}
    model: Mapped[str | None] = mapped_column(String(80))
    avatar_model_id: Mapped[str | None] = mapped_column(ForeignKey("avatar_models.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (UniqueConstraint("owner_id", "slug"),)

    @property
    def name(self) -> str:
        return (self.persona or {}).get("name") or self.slug


class CharacterVersion(Base):
    """保存人格核心之前的快照，可以恢复。"""

    __tablename__ = "character_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    persona: Mapped[dict] = mapped_column(JSONB)
    behavior: Mapped[dict] = mapped_column(JSONB)
    lore: Mapped[list] = mapped_column(JSONB)
    note: Mapped[str] = mapped_column(String(80), default="")
    saved_at: Mapped[datetime] = _created()


class AvatarModel(Base):
    """用户上传的 VRM 模型（文件本身也在库里）。meta 是 VRM 文件自带的作者与许可信息。"""

    __tablename__ = "avatar_models"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    vrm_version: Mapped[str] = mapped_column(String(8))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (UniqueConstraint("user_id", "sha256"),)


# ---------- 聊天 ----------

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list[Message]] = relationship(back_populates="session", cascade="all, delete-orphan",
                                                   order_by="Message.id")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 稳定 ID：记忆的 source_messages 引用它
    uid: Mapped[str] = mapped_column(String(40), default=lambda: "msg_" + uuid.uuid4().hex[:16], index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | event（用户触发的互动、安静时的事件）
    content: Mapped[str] = mapped_column(Text)
    state: Mapped[dict | None] = mapped_column(JSONB)  # 角色的表情 / 动作等结构化输出
    meta: Mapped[dict | None] = mapped_column(JSONB)  # 本轮的策略决策、用到的记忆、模型用量等
    created_at: Mapped[datetime] = _created()

    session: Mapped[ChatSession] = relationship(back_populates="messages")


# ---------- 记忆与关系（用户 × 角色私有） ----------

class Memory(Base):
    """一条长期记忆，只属于“这个用户 × 这个角色”。

    type     fact 关于用户 / preference 偏好 / event 共同经历 / commitment 约定 / summary 会话回忆
    origin   stated 用户亲口说 / corrected 用户更正 / manual 用户自己写 / inferred 模型推断 / imported / summary
    reality  real 现实 / story 虚构故事（角色扮演、幻想剧情里发生的事）
    status   active / archived 淡了 / forgotten 不再记住 / superseded 被更正后的旧版本
    """

    __tablename__ = "memories"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(16))
    key: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16))
    reality: Mapped[str] = mapped_column(String(8), default="real")
    status: Mapped[str] = mapped_column(String(16), default="active")
    status_reason: Mapped[str | None] = mapped_column(String(120))
    importance: Mapped[int] = mapped_column(Integer, default=3)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    evidence: Mapped[str | None] = mapped_column(Text)
    source_messages: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    supersedes: Mapped[str | None] = mapped_column(String(32))
    superseded_by: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_confirmed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_recalled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_text: Mapped[str] = mapped_column(Text, default="")  # jieba 分词后的文本
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', search_text)", persisted=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("ix_memories_scope", "user_id", "character_id", "status"),
        Index("ix_memories_tsv", "tsv", postgresql_using="gin"),
    )


class MemoryCandidate(Base):
    """等用户确认的记忆：模型推断、敏感信息、与固定记忆冲突的内容。过期自动清理。"""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(16))  # inferred | sensitive | conflict | suggested
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryTombstone(Base):
    """删除记录：只存哈希。删除时还在跑的整理任务不会把已删的内容写回去。"""

    __tablename__ = "memory_tombstones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    content_hash: Mapped[str] = mapped_column(String(64))
    key_hash: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_tombstones_scope", "user_id", "character_id"),)


class MemoryJob(Base):
    """聊天回复后的异步记忆整理任务。"""

    __tablename__ = "memory_jobs"

    id: Mapped[str] = _id()
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Bond(Base):
    """关系状态：亲近度与阶段、称呼、里程碑、她怎么看对方，以及会过期的“此刻”（近期话题、情绪线索）。"""

    __tablename__ = "bonds"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    closeness: Mapped[float] = mapped_column(Float, default=0.0)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    sessions: Mapped[int] = mapped_column(Integer, default=0)
    first_met: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gained_today: Mapped[dict] = mapped_column(JSONB, default=dict)  # {date, value}
    user_calls_her: Mapped[str | None] = mapped_column(String(24))
    milestones: Mapped[list] = mapped_column(JSONB, default=list)  # [{at, text}]
    her_view: Mapped[str | None] = mapped_column(Text)
    current: Mapped[dict] = mapped_column(JSONB, default=dict)  # {topics, mood_cues, open_items}，每项带 expires

    __table_args__ = (PrimaryKeyConstraint("user_id", "character_id"),)


# ---------- 创意工坊（所有用户共享的公开内容） ----------

class WorkshopItem(Base):
    __tablename__ = "workshop_items"

    id: Mapped[str] = _id()
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_character_id: Mapped[str | None] = mapped_column(ForeignKey("characters.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(40))
    tagline: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(16), default="other", index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    color: Mapped[str] = mapped_column(String(16), default="#1414a8")
    latest_version: Mapped[int] = mapped_column(Integer, default=1)
    # 审核状态：pending 待审核 / published 已上架 / hidden 因举报暂时隐藏 / removed 下架
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    status_note: Mapped[str | None] = mapped_column(String(200))
    forked_from: Mapped[str | None] = mapped_column(String(32), index=True)
    installs: Mapped[int] = mapped_column(Integer, default=0)
    up: Mapped[int] = mapped_column(Integer, default=0)
    down: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkshopVersion(Base):
    __tablename__ = "workshop_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("workshop_items.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    changelog: Mapped[str] = mapped_column(Text, default="")
    package: Mapped[dict] = mapped_column(JSONB)  # krino-persona/1 人设包（不含任何私人记忆）
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (UniqueConstraint("item_id", "version"),)


class WorkshopInstall(Base):
    """导入 = 装一份到自己的角色里；作者更新后可以一键更新。"""

    __tablename__ = "workshop_installs"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(ForeignKey("workshop_items.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    installed_version: Mapped[int] = mapped_column(Integer)
    installed_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (PrimaryKeyConstraint("user_id", "item_id"),)


class WorkshopVote(Base):
    __tablename__ = "workshop_votes"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[str] = mapped_column(ForeignKey("workshop_items.id", ondelete="CASCADE"), index=True)
    value: Mapped[int] = mapped_column(Integer)  # 1 | -1

    __table_args__ = (PrimaryKeyConstraint("user_id", "item_id"),)


class WorkshopComment(Base):
    __tablename__ = "workshop_comments"

    id: Mapped[str] = _id()
    item_id: Mapped[str] = mapped_column(ForeignKey("workshop_items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="visible")  # visible | removed
    created_at: Mapped[datetime] = _created()


class WorkshopReport(Base):
    __tablename__ = "workshop_reports"

    id: Mapped[str] = _id()
    item_id: Mapped[str] = mapped_column(ForeignKey("workshop_items.id", ondelete="CASCADE"), index=True)
    comment_id: Mapped[str | None] = mapped_column(String(32))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)  # open | dismissed | actioned
    created_at: Mapped[datetime] = _created()


# ---------- 运行记录 ----------

class WorldEvent(Base):
    """互动策略决策、设备（眼镜模拟器）输入、AR 输出、语音/视觉调用、服务错误。只记结构化信息与耗时，不存音视频。"""

    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16), index=True)  # policy | llm | device | ar | voice | vision | error
    name: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
