"""KRINO Evaluator 的新职责：内部互动策略（Interaction Policy）。不向用户展示排名或决策矩阵。

    事件输入 → 人格及记忆上下文 → 候选交互行为 → 策略打分（+ 硬约束）→ 行为执行（chat.py）→ 用户反馈

七种行为：
    NO_ACTION 保持安静   RESPOND 回应   STORY 幻想剧情   PERCEIVE 多模态理解        ← 主行为，每次只选一个
    EMOTE 表情           ANIMATE 预设动作   REMEMBER 建议保存共同记忆                 ← 附加行为，可以叠加

策略实现
    rules   规则策略（默认）。可解释、确定性，参数来自人设的 behavior 和用户设置。输出标注为“规则策略，非模型输出”。
    matrix  KRINO Matrix 3-Head 模型（实验）。沿用现有接口：目标 + 约束 + 候选行为 → 选择头概率。
            现有权重训练于“决策问题 + 候选行动”数据，没有针对互动行为训练，输出只作实验对照，不代表效果。
            模型不可用时自动回退到规则策略并注明。
    off     只在用户说话时回应，不做额外动作。
硬约束（无论哪种策略都由代码强制）：用户要求安静就不说话；没授权摄像头就不请求画面；关掉动作/剧情就不执行；
安静时主动开口至少隔 5 分钟。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .auth import current_user, user_settings
from .config import settings
from .db import get_db
from .models import User
from .personas import ANIMATION_LABELS, ANIMATIONS, EXPRESSIONS, default_behavior, get_owned

log = logging.getLogger("krino.policy")
router = APIRouter(prefix="/api/policy", tags=["policy"])

PRIMARY = ("NO_ACTION", "RESPOND", "STORY", "PERCEIVE")
MODIFIERS = ("EMOTE", "ANIMATE", "REMEMBER")
EXTRA_THRESHOLD = 0.5
PROACTIVE_GAP_S = 300  # 安静时主动开口的最小间隔

# 用户可以主动触发的有限预设互动：名字 → (说明, 角色的反应动作, 反应表情)
GESTURES = {
    "wave": ("向她挥手打招呼", "wave", "happy"),
    "pat_head": ("摸摸她的头", "tilt_head", "shy"),
    "high_five": ("和她击掌", "cheer", "happy"),
    "poke": ("轻轻戳了戳她的脸颊", "shake_head", "surprised"),
    "cheer_up": ("给她加油打气", "nod", "happy"),
}

_SILENCE = re.compile(r"安静(?:一会|一下|点)|别说话|先别说|不想聊|让我静静|嘘+|闭嘴|别吵")
STORY_REQUEST = re.compile(r"(?:讲|编|说).{0,8}故事|来(?:一)?段剧情|一起冒险|我们来(?:演|玩)|角色扮演|继续(?:讲|编)|接着(?:讲|编)|然后呢")
_LOOK = re.compile(r"看看|你看|帮我看|这是什么|看得到|看一下|我拍(?:了|的)?")
_ANIM_REQ = [("wave", r"挥(?:挥)?手"), ("nod", r"点(?:个|点)?头"), ("shake_head", r"摇(?:摇)?头"), ("bow", r"鞠(?:个)?躬"),
             ("spin", r"转(?:个)?圈"), ("tilt_head", r"歪(?:个)?头"), ("cheer", r"欢呼|跳一下|蹦一下"), ("think", r"想一想|思考一下")]
_ANIM_CUE = [("wave", r"^(?:你好|嗨|hi|hello|早上好|早安|晚安|拜拜|再见)"), ("bow", r"谢谢|感谢|辛苦了"),
             ("think", r"为什么|怎么办|你觉得|是不是|[?？]$"), ("cheer", r"太好了|好耶|成功了|通过了")]
_EMOTION = [("happy", r"开心|高兴|太好了|好耶|哈哈|嘿嘿"), ("sad", r"难过|伤心|想哭|失落"),
            ("worried", r"累|焦虑|压力|担心|失眠|烦"), ("surprised", r"真的吗|居然|竟然|哇|不会吧"),
            ("shy", r"喜欢你|好可爱|夸你|你真好")]
_REMEMBER = re.compile(r"我们(?:今天|刚才|一起)|约好|说好了|记住(?:这|今天)|别忘了|纪念|第一次")


@dataclass
class InteractionEvent:
    type: Literal["message", "idle", "gesture", "perception"]
    text: str = ""
    gesture: str | None = None
    has_image: bool = False
    source: str = "app"  # app | glasses
    idle_count: int = 0


@dataclass
class PolicyContext:
    behavior: dict
    user_settings: dict
    seconds_since_proactive: float | None = None


@dataclass
class Candidate:
    id: str
    action: str
    description: str
    params: dict = field(default_factory=dict)
    score: float = 0.0
    reason: str = ""
    blocked: str | None = None


@dataclass
class Decision:
    primary: Candidate
    extras: list[Candidate]
    candidates: list[Candidate]
    policy: str
    label: str
    experimental: bool = False
    note: str = ""
    latency_ms: float = 0.0

    def actions(self) -> list[str]:
        return [self.primary.action] + [c.action for c in self.extras]

    def as_dict(self) -> dict:
        return {"policy": self.policy, "label": self.label, "experimental": self.experimental, "note": self.note,
                "primary": asdict(self.primary), "extras": [asdict(c) for c in self.extras],
                "candidates": [asdict(c) for c in self.candidates], "latency_ms": round(self.latency_ms, 2)}


# ---------- 候选 ----------

def _first(pairs, text: str) -> str | None:
    return next((name for name, pat in pairs if re.search(pat, text, re.I)), None)


def build_candidates(ev: InteractionEvent, ctx: PolicyContext) -> list[Candidate]:
    """列出这次事件可能的行为，并标出被硬约束挡住的。"""
    b = {**default_behavior(ctx.behavior.get("style", "温柔")), **ctx.behavior}
    us = ctx.user_settings
    inter, privacy = us.get("interaction", {}), us.get("privacy", {})
    text = ev.text.strip()
    silence = ev.type == "message" and bool(_SILENCE.search(text))
    expr_cue = _first(_EMOTION, text) if text else None
    anim_req = _first(_ANIM_REQ, text) if text else None
    anim_cue = _first(_ANIM_CUE, text) if text else None
    gesture = GESTURES.get(ev.gesture or "")

    cands = [
        Candidate("no_action", "NO_ACTION", "保持安静，只在一旁陪着"),
        Candidate("respond", "RESPOND", "用一两句话回应对方"),
        Candidate("tell_story", "STORY", "讲一段幻想剧情，邀请对方一起编"),
        Candidate("perceive_scene", "PERCEIVE", "看看对方分享的画面再回应",
                  params={"has_image": ev.has_image}),
    ]
    expression = (gesture[2] if gesture else None) or expr_cue
    cands.append(Candidate(f"emote_{expression or 'auto'}", "EMOTE", "换一个表情表达此刻的情绪",
                           params={"expression": expression}))
    anim = anim_req or (gesture[1] if gesture else None) or anim_cue or ("tilt_head" if ev.type == "idle" else None)
    if anim:
        cands.append(Candidate(f"animate_{anim}", "ANIMATE", f"做一个“{ANIMATION_LABELS[anim]}”的动作", params={"name": anim}))
    if ev.type == "message" and _REMEMBER.search(text):
        cands.append(Candidate("remember_moment", "REMEMBER", "提议把这段共同经历记下来"))

    for c in cands:  # 硬约束
        if c.action != "NO_ACTION" and silence:  # 要求安静 = 不说话、不做表情和动作，只安静陪着
            c.blocked = "对方希望安静一会儿"
        elif c.action == "RESPOND" and ev.type == "idle" and not inter.get("proactive", True):
            c.blocked = "用户关闭了主动互动"
        elif c.action == "RESPOND" and ev.type == "idle" and (
                ev.idle_count < 2 or (ctx.seconds_since_proactive is not None and ctx.seconds_since_proactive < PROACTIVE_GAP_S)):
            c.blocked = "主动开口太频繁了（至少隔 5 分钟）"
        elif c.action == "STORY" and not inter.get("stories", True):
            c.blocked = "用户关闭了幻想剧情"
        elif c.action == "STORY" and ev.type != "message":
            c.blocked = "只在对方开口时讲故事"
        elif c.action == "PERCEIVE" and not ev.has_image and not privacy.get("camera", False):
            c.blocked = "没有画面，也没有摄像头授权"
        elif c.action == "ANIMATE" and not inter.get("animations", True):
            c.blocked = "用户关闭了预设动作"
        elif c.action == "ANIMATE" and c.params["name"] not in b.get("animations", ANIMATIONS):
            c.blocked = "这个动作不在角色的动作列表里"
        elif c.action == "EMOTE" and expression and expression not in b.get("expressions", EXPRESSIONS):
            c.blocked = "这个表情不在角色的表情列表里"
    return cands


# ---------- 规则策略 ----------

class RulesPolicy:
    name = "rules"
    label = "规则策略（非模型输出）"

    def score(self, ev: InteractionEvent, ctx: PolicyContext, cands: list[Candidate]) -> None:
        b = {**default_behavior(ctx.behavior.get("style", "温柔")), **ctx.behavior}
        talk, expr, pro, story = b["talkativeness"], b["expressiveness"], b["proactivity"], b["story_affinity"]
        text = ev.text
        for c in cands:
            a = c.action
            if a == "NO_ACTION":
                c.score, c.reason = {"message": (0.05, "对方在说话"), "idle": (0.5, "安静时默认陪着"),
                                     "gesture": (0.05, "对方主动互动"), "perception": (0.2, "")}[ev.type]
                if _SILENCE.search(text):
                    c.score, c.reason = 0.97, "对方希望安静"
            elif a == "RESPOND":
                if ev.type == "message":
                    c.score, c.reason = 0.85, "对方在说话"
                elif ev.type == "gesture":
                    c.score, c.reason = round(0.3 + 0.5 * talk, 2), "话量决定要不要开口"
                elif ev.type == "idle":  # 频率限制在硬约束里
                    c.score = round(0.5 + 0.4 * pro, 2) if pro >= 0.3 else 0.1
                    c.reason = "安静了一阵，主动开个头" if c.score > 0.5 else "不爱主动"
                else:
                    c.score, c.reason = 0.3, ""
            elif a == "STORY":
                asked = bool(STORY_REQUEST.search(text))
                c.score = round(0.9 + 0.05 * story, 2) if asked else 0.0
                c.reason = "对方想听故事" if asked else ""
            elif a == "PERCEIVE":
                if ev.has_image:
                    c.score, c.reason = 0.95, "对方分享了画面"
                elif ev.type == "message" and _LOOK.search(text):
                    c.score, c.reason = 0.9, "对方想让她看看"
            elif a == "EMOTE":
                if ev.type == "gesture":
                    c.score, c.reason = 0.9, "回应对方的互动"
                elif c.params.get("expression"):
                    c.score, c.reason = round(0.5 + 0.5 * expr, 2), "话里有情绪"
                else:
                    c.score, c.reason = round(0.25 + 0.4 * expr, 2), "表情丰富度"
                if ev.type == "idle":
                    c.score = round(c.score * 0.5, 2)
            elif a == "ANIMATE":
                if ev.type == "gesture":
                    c.score, c.reason = 0.9, "回应对方的互动"
                elif _first(_ANIM_REQ, text):
                    c.score, c.reason = 0.95, "对方请她做这个动作"
                elif ev.type == "idle":
                    c.score = 0.6 if ev.idle_count % 2 == 1 and expr >= 0.5 else 0.2
                    c.reason = "待机时的小动作"
                else:
                    c.score, c.reason = round(0.3 + 0.5 * expr, 2), "打招呼/道谢/思考时自然的动作"
            elif a == "REMEMBER":
                c.score, c.reason = 0.75, "像是值得记住的共同经历"


# ---------- Matrix 3-Head 模型（实验） ----------

class MatrixPolicy:
    """把互动行为套进现有的决策模型接口：goal = 自然地互动，constraints = 硬约束，actions = 候选行为。

    只用选择头（selection）的相对概率排序；硬约束仍由 build_candidates 在代码里强制，不依赖约束头。
    """

    name = "matrix"
    label = "KRINO Matrix 3-Head（实验：权重未针对互动行为训练）"
    _lock = threading.Lock()
    _evaluator = None
    _failed: str | None = None

    @classmethod
    def available(cls) -> tuple[bool, str]:
        if cls._failed:
            return False, cls._failed
        if not (settings.matrix_checkpoint / "matrix_config.json").exists():
            return False, f"找不到模型权重：{settings.matrix_checkpoint.name}"
        return True, ""

    @classmethod
    def evaluator(cls):
        with cls._lock:
            if cls._evaluator is None and cls._failed is None:
                try:
                    import sys

                    from .config import ROOT_DIR
                    if str(ROOT_DIR) not in sys.path:
                        sys.path.insert(0, str(ROOT_DIR))
                    from krino.evaluator.matrix import MatrixModelEvaluator

                    cls._evaluator = MatrixModelEvaluator(str(settings.matrix_checkpoint))
                    cls._evaluator.model  # noqa: B018  立即加载，失败就回退
                except Exception as e:  # noqa: BLE001
                    cls._failed = f"模型加载失败：{type(e).__name__}: {e}"[:200]
                    log.exception("Matrix 模型加载失败")
            return cls._evaluator

    def score(self, ev: InteractionEvent, ctx: PolicyContext, cands: list[Candidate]) -> None:
        from krino.common.schema import Action, Constraint, Problem, State

        live = [c for c in cands if not c.blocked]
        problem = Problem(
            goal="作为虚拟角色，在当前事件下选择最自然、贴合人设、尊重对方意愿的互动行为",
            constraints=[Constraint(id="respect_user_wishes", text="尊重对方的明确要求（例如要求安静）", hard=True),
                         Constraint(id="no_unauthorized_camera", text="没有授权时不请求摄像头画面", hard=True),
                         Constraint(id="stay_in_character", text="行为符合角色的人设和风格", hard=False)],
            state=State(data={"event": ev.type, "text": ev.text[:300], "gesture": ev.gesture, "has_image": ev.has_image,
                              "style": ctx.behavior.get("style"), "talkativeness": ctx.behavior.get("talkativeness"),
                              "expressiveness": ctx.behavior.get("expressiveness")}),
        )
        evaluation = self.evaluator().evaluate(problem, [Action(id=c.id, description=c.description) for c in live])
        scores = evaluation.scores or {}
        for c in live:
            c.score = round(float(scores.get(c.id, 0.0)), 4)
            c.reason = "选择头相对概率（实验）"


class OffPolicy:
    name = "off"
    label = "已关闭：只回应，不做额外动作"

    def score(self, ev, ctx, cands) -> None:
        for c in cands:
            c.score = {"RESPOND": 1.0 if ev.type in ("message", "gesture") else 0.0,
                       "NO_ACTION": 0.0 if ev.type in ("message", "gesture") else 1.0,
                       "PERCEIVE": 1.0 if ev.has_image else 0.0}.get(c.action, 0.0)


POLICIES = {"rules": RulesPolicy, "matrix": MatrixPolicy, "off": OffPolicy}


def mode_for(us: dict) -> str:
    m = (us.get("evaluator") or {}).get("mode") or settings.policy_mode
    return m if m in POLICIES else "rules"


def decide(ev: InteractionEvent, ctx: PolicyContext, mode: str | None = None) -> Decision:
    t0 = time.perf_counter()
    mode = mode or mode_for(ctx.user_settings)
    cands = build_candidates(ev, ctx)
    policy, note = POLICIES[mode](), ""
    if mode == "matrix":
        ok, why = MatrixPolicy.available()
        if ok and MatrixPolicy.evaluator() is None:
            ok, why = MatrixPolicy.available()
        if not ok:
            policy, note = RulesPolicy(), f"Matrix 模型不可用，已回退规则策略（{why}）"
    try:
        policy.score(ev, ctx, cands)
    except Exception as e:  # noqa: BLE001  策略出错不能影响聊天
        log.exception("互动策略出错")
        policy, note = RulesPolicy(), f"{policy.name} 出错，已回退规则策略：{type(e).__name__}"
        policy.score(ev, ctx, cands)

    live = [c for c in cands if not c.blocked]
    primaries = [c for c in live if c.action in PRIMARY]
    primary = max(primaries, key=lambda c: c.score) if primaries else next(c for c in cands if c.action == "NO_ACTION")
    if mode == "matrix" and policy.name == "matrix":
        # 选择头的概率在所有候选之间归一：附加行为只要不低于主行为的一半就执行
        threshold = max(0.05, primary.score * 0.5)
    else:
        threshold = EXTRA_THRESHOLD
    extras = [c for c in live if c.action in MODIFIERS and c.score >= threshold]
    if primary.action == "NO_ACTION":
        extras = [c for c in extras if c.action != "REMEMBER"]
    return Decision(primary=primary, extras=extras, candidates=cands, policy=policy.name, label=policy.label,
                    experimental=policy.name == "matrix", note=note, latency_ms=(time.perf_counter() - t0) * 1000)


def policy_status(user: User) -> dict:
    mode = mode_for(user_settings(user))
    ok, why = MatrixPolicy.available()
    return {"mode": mode, "server_default": settings.policy_mode, "label": POLICIES[mode].label,
            "matrix": {"available": ok, "reason": why, "checkpoint": settings.matrix_checkpoint.name,
                       "loaded": MatrixPolicy._evaluator is not None,
                       "note": "权重训练于决策任务，未针对互动行为训练；输出仅作实验对照"}}


# ---------- 接口：测试状态 ----------

SCENARIOS = [
    ("打招呼", InteractionEvent("message", text="你好呀")),
    ("要求安静", InteractionEvent("message", text="让我安静一会儿")),
    ("想听故事", InteractionEvent("message", text="给我讲个深海的故事吧")),
    ("想让她看看（未授权摄像头）", InteractionEvent("message", text="你看看我这边")),
    ("分享了一张图", InteractionEvent("message", text="这是什么", has_image=True)),
    ("共同经历", InteractionEvent("message", text="我们今天一起看了日落")),
    ("摸摸头", InteractionEvent("gesture", gesture="pat_head")),
    ("安静了一阵", InteractionEvent("idle", idle_count=3)),
]


class TestIn(BaseModel):
    character_id: str
    mode: str | None = None


@router.get("/status")
def status(user: User = Depends(current_user)):
    return policy_status(user)


@router.post("/test")
def test(body: TestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """用当前角色跑几个固定场景，看策略会选什么（不调模型、不写聊天记录）。"""
    c = get_owned(db, user, body.character_id)
    ctx = PolicyContext(behavior=c.behavior, user_settings=user_settings(user))
    mode = body.mode if body.mode in POLICIES else None
    rows = []
    for name, ev in SCENARIOS:
        d = decide(ev, ctx, mode)
        rows.append({"scenario": name, "actions": d.actions(), "primary_reason": d.primary.reason,
                     "blocked": {x.action: x.blocked for x in d.candidates if x.blocked},
                     "latency_ms": round(d.latency_ms, 2), "policy": d.policy, "note": d.note})
    return {"policy": rows[0]["policy"] if rows else mode, "label": POLICIES[rows[0]["policy"]].label,
            "experimental": rows[0]["policy"] == "matrix", "results": rows}
