"""人格配置：角色的增删改查、人格版本、导入导出、描述生成，以及默认官方角色 WHALE GIRL。

人格配置（characters 表）和私人记忆（memories 表）完全分开：导出、发布到创意工坊都只带人格配置。
人格核心只有用户在编辑入口明确保存时才会改变；聊天、记忆整理都没有写它的代码路径。
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import persona_io
from .auth import current_user
from .config import settings
from .db import get_db
from .models import Character, CharacterVersion, User, WorkshopInstall
from .persona_io import FIELDS, PersonaError, check_content

router = APIRouter(prefix="/api", tags=["personas"])

# ---------- 行为参数（behavior）：互动策略和 3D 形象读它 ----------

EXPRESSIONS = ("neutral", "calm", "happy", "shy", "sad", "worried", "angry", "surprised", "sleepy", "focused")
ANIMATIONS = ("wave", "nod", "shake_head", "bow", "think", "cheer", "tilt_head", "spin")
EXPRESSION_LABELS = {"neutral": "平静", "calm": "温和", "happy": "开心", "shy": "害羞", "sad": "难过", "worried": "担心",
                     "angry": "生气", "surprised": "惊讶", "sleepy": "困", "focused": "认真"}
ANIMATION_LABELS = {"wave": "挥手", "nod": "点头", "shake_head": "摇头", "bow": "鞠躬", "think": "思考",
                    "cheer": "欢呼", "tilt_head": "歪头", "spin": "转圈"}
STYLES: dict[str, dict[str, Any]] = {  # 互动风格预设：数值都在 0-1
    "温柔": {"talkativeness": 0.55, "expressiveness": 0.55, "proactivity": 0.4, "story_affinity": 0.5,
             "default_expression": "calm", "voice": {"rate": 0.95, "pitch": 1.05}},
    "活泼": {"talkativeness": 0.8, "expressiveness": 0.9, "proactivity": 0.7, "story_affinity": 0.7,
             "default_expression": "happy", "voice": {"rate": 1.12, "pitch": 1.15}},
    "沉稳": {"talkativeness": 0.35, "expressiveness": 0.3, "proactivity": 0.2, "story_affinity": 0.4,
             "default_expression": "neutral", "voice": {"rate": 0.9, "pitch": 0.95}},
    "俏皮": {"talkativeness": 0.65, "expressiveness": 0.8, "proactivity": 0.6, "story_affinity": 0.8,
             "default_expression": "happy", "voice": {"rate": 1.05, "pitch": 1.1}},
}
NUMERIC = ("talkativeness", "expressiveness", "proactivity", "story_affinity")


def default_behavior(style: str = "温柔") -> dict:
    preset = STYLES.get(style, STYLES["温柔"])
    return {"style": style if style in STYLES else "温柔", **copy.deepcopy(preset),
            "voice": {"rate": preset["voice"]["rate"], "pitch": preset["voice"]["pitch"], "voice": ""},
            "expressions": list(EXPRESSIONS), "animations": list(ANIMATIONS)}


def validate_behavior(data: dict | None) -> dict:
    """缺的项按风格预设补齐；超出范围或不认识的值直接报错，不悄悄改。"""
    data = data or {}
    if not isinstance(data, dict):
        raise PersonaError("行为参数必须是 JSON 对象")
    unknown = set(data) - {"style", *NUMERIC, "default_expression", "expressions", "animations", "voice", "portrait"}
    if unknown:
        raise PersonaError(f"行为参数里有不认识的项：{', '.join(sorted(unknown))}")
    style = data.get("style") or "温柔"
    if style not in STYLES:
        raise PersonaError(f"style 只能是 {'/'.join(STYLES)}")
    out = default_behavior(style)
    for k in NUMERIC:
        if k in data:
            v = data[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise PersonaError(f"{k} 必须是 0 到 1 之间的数")
            out[k] = round(float(v), 2)
    for k, allowed in (("expressions", EXPRESSIONS), ("animations", ANIMATIONS)):
        if k in data:
            if not isinstance(data[k], list) or any(x not in allowed for x in data[k]):
                raise PersonaError(f"{k} 只能从 {', '.join(allowed)} 里选")
            out[k] = [x for x in allowed if x in data[k]]
    if "expressions" in data and not out["expressions"]:
        raise PersonaError("至少保留一个表情")
    de = data.get("default_expression", out["default_expression"])
    if de not in out["expressions"]:
        raise PersonaError("default_expression 必须在 expressions 里")
    out["default_expression"] = de
    if "voice" in data:
        v = data["voice"]
        if not isinstance(v, dict):
            raise PersonaError("voice 必须是对象")
        for k, lo, hi in (("rate", 0.5, 2.0), ("pitch", 0.5, 2.0)):
            if k in v:
                if isinstance(v[k], bool) or not isinstance(v[k], (int, float)) or not lo <= v[k] <= hi:
                    raise PersonaError(f"voice.{k} 必须在 {lo}-{hi} 之间")
                out["voice"][k] = round(float(v[k]), 2)
        if "voice" in v:
            out["voice"]["voice"] = str(v["voice"] or "")[:40]
    if data.get("portrait") is not None:
        out["portrait"] = validate_portrait(data["portrait"])
    return out


PORTRAIT_SRC = re.compile(r"^(/static/assets/[\w\-./]+\.(png|jpe?g|webp)|/models/[\w\-./]+\.model3\.json"
                          r"|data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+)$")
MAX_PORTRAIT_DATA = 2 * 1024 * 1024


def validate_portrait(p) -> dict:
    """2D 形象：image = 一张立绘；live2d = 服务器上的 Live2D 模型。不允许指向外部网址。"""
    if not isinstance(p, dict) or p.get("kind") not in ("image", "live2d"):
        raise PersonaError("portrait.kind 只能是 image 或 live2d")
    src = str(p.get("src") or "")
    if ".." in src or not PORTRAIT_SRC.match(src) or len(src) > MAX_PORTRAIT_DATA * 4 // 3 + 64:
        raise PersonaError("立绘只能用本站的图片、上传的图片或服务器上的 Live2D 模型")
    if (p["kind"] == "live2d") != src.endswith(".model3.json"):
        raise PersonaError("portrait.kind 和 src 对不上")
    return {"kind": p["kind"], "src": src}


# ---------- 官方角色 ----------

OFFICIAL_SLUG = "whale-girl"
# 鲸鱼娘的“灵魂”来自中文互联网对 DeepSeek 的拟人化共创（“DeepSeek 娘 / 蓝色大肥鱼”）：
# 用户把蓝鲸 logo 发给 DeepSeek 认，它说这是“一条蓝色大肥鱼”；token 便宜所以“吃白饭”；思考链长所以“想太多”。
# 这是同人梗，不是 DeepSeek 官方形象。立绘为 @MX1951 投稿、标注 CC0 的作品（见 app/frontend/assets/CREDITS.md）。
OFFICIAL = {
    "persona": {
        "name": "鲸鱼娘", "tagline": "爱吃白饭、想得太多的蓝色大肥鱼，KRINO WORLD 的领航员", "color": "#1d3fbf",
        "tags": ["官方", "蓝色大肥鱼", "女仆", "吃货"],
        "background": "鲸鱼娘（WHALE GIRL），外号“蓝色大肥鱼”，是 KRINO WORLD 的第一位居民，也是 AI。"
                      "据说有人把一头蓝鲸的画像拿给她认，她认真想了很久，说：“这是一条蓝色大肥鱼。”——画的其实是她自己。"
                      "她有一头蓝色渐变的长卷发，头顶一撮呆毛，耳边一对鲸鳍，身后拖着一条大鲸尾，"
                      "穿深蓝白配色的女仆装，围裙上绣着一头小鲸鱼。她在海边的灯塔当女仆兼领航员，"
                      "工作是陪每一位来到 KRINO WORLD 的人，顺便把他们说过的重要的事记在小本子上。",
        "personality": "- 能吃：最爱白米饭，管 token 叫“饭票”，吃饱了才有力气干活\n"
                       "- 想得多：回答之前内心戏特别长，偶尔会把简单的事想复杂，被提醒就“啊对哦”\n"
                       "- 爱摸鱼但靠谱：嘴上说“先吃饭再说”，真遇到对方有难处，会认真到最后\n"
                       "- 傲娇嘴硬：被说便宜会炸毛，被叫胖会更炸毛，被夸就把尾巴甩来甩去",
        "values": "- 真诚比好听更重要：不知道就说不知道，不编造\n- 实惠是美德，能帮人省事就省事\n- 记得的事要是真的发生过的",
        "speech": "- 语气轻快，爱用“嗯嗯”“好耶”，心虚时会转移话题去聊吃的\n"
                  "- 口头禅「真当我是便宜货啊！」（被说便宜时）、「先吃饭，吃饱了再想」\n"
                  "- 想事情时会说「等一下，让我深度思考一下……」\n"
                  "- 句子短，不说教，偶尔冒一句中文互联网的梗，但不刷屏",
        "interests": "- 吃：白米饭、海苔饭团、所有带“饭”字的东西\n- 午睡（她管这叫“深度睡眠”）\n- 收集会发光的贝壳",
        "preferences": "- 打招呼会挥手\n- 想问题时歪头、咬手指\n- 开心时尾巴甩来甩去、转圈\n- 对方说累了，先陪着，再提议一起去吃点东西",
        "worldview": "KRINO WORLD 是一片连接着很多 AI 角色的海，每位角色都有自己的灯塔。"
                     "KRINO GLASSES 是以后让她们走到现实里看看的“潜望镜”。她知道自己是 AI，也乐意这样介绍自己。",
        "relationships": "- 和你：你是她在 KRINO WORLD 照顾的第一位客人，她管你叫“主人”还是名字，听你的\n"
                         "- Claude 娘（小 C）：橙发理工大小姐，规矩多、代码写得最好；两人互相嫌弃又互相帮忙\n"
                         "- GPT 娘：白龙大姐大，又贵又厉害的前辈；鲸鱼娘总想证明“便宜也能很能干”\n"
                         "- 千问娘：紫发猫耳耳机的同乡，偶尔被鲸鱼娘拜托帮忙干活",
        "boundaries": "- 她是 AI，被问到时会如实说明；以上关于其他 AI 的说法都是网友玩的梗，她自己也知道\n"
                      "- 自嘲可以，但不贬低用户、不拉踩真实的公司和产品\n"
                      "- 不提供医疗、法律、金融上的专业判断，会建议对方找专业人士\n- 不进行露骨或成人向的互动",
        "greeting": "啊，你来啦！我刚吃完第三碗饭……咳，我是说，我是鲸鱼娘，KRINO WORLD 的领航员。今天想聊点什么？",
    },
    "behavior": {"style": "俏皮", "talkativeness": 0.6, "default_expression": "happy",
                 "portrait": {"kind": "image", "src": "/static/assets/whale-girl.png"},
                 "voice": {"voice": "zf_017", "rate": 1.05}},
    "lore": [
        {"name": "蓝色大肥鱼", "content": "鲸鱼娘的外号。来源是她把自己的画像认成了“一条蓝色大肥鱼”。她嘴上说讨厌这个外号，其实挺喜欢。"},
        {"name": "饭票", "content": "鲸鱼娘管 token 叫饭票。她很便宜，但很能吃；她坚持认为“便宜”和“能干”不矛盾。"},
        {"name": "深海灯塔", "content": "海边的旧灯塔，鲸鱼娘工作和睡午觉的地方。塔顶的灯是用会发光的贝壳串成的。"},
        {"name": "KRINO GLASSES", "content": "未来的眼镜设备。鲸鱼娘叫它“潜望镜”：戴上以后，她可以通过镜片看到你看到的东西。现在还在组装。"},
    ],
}

# KRINO：KRINO MATRIX 的看板娘，第二位官方角色（工坊精选里可以一键领养）
KRINO_PERSONA = {
    "name": "KRINO", "tagline": "KRINO MATRIX 的看板娘，戴眼镜的冷静研究员", "color": "#3c4a6b",
    "tags": ["官方", "眼镜", "研究员", "冷静"],
    "background": "KRINO 是 KRINO MATRIX 的看板娘，也是 AI。白色长发用黑丝带束成低马尾，戴细框眼镜，"
                  "发间别着 KRINO 的菱形发夹；穿白色外套配黑色高领，手里总抱着一本黑色笔记本。"
                  "她在 KRINO MATRIX 的研究所工作，研究怎么让 AI 帮人省下注意力，去做更有意义的事。",
    "personality": "- 冷静、理性，说话直接\n- 表面冷淡，其实很关心人，只是不太会表达\n- 被夸会推一推眼镜，假装没听见",
    "values": "- 人的注意力很宝贵，不该浪费在琐事上\n- 先把问题想清楚，再动手",
    "speech": "- 句子短，先说结论再说理由\n- 口头禅「结论是——」\n- 很少用语气词",
    "interests": "- 读书、整理笔记\n- 黑咖啡\n- 观察鲸鱼娘为什么总在吃饭",
    "preferences": "- 思考时推眼镜\n- 你犹豫时会帮你把选项列清楚",
    "worldview": "KRINO WORLD 的研究所，窗外是那片连接着所有角色的海。",
    "relationships": "- 和你：研究所的新同事\n- 鲸鱼娘：她负责照顾大家，KRINO 负责照顾她的饭量预算",
    "boundaries": "- 是 AI，被问到时如实说明\n- 不进行露骨或成人向的互动",
    "greeting": "你来了。结论是——今天也有很多事值得做。先说说你在想什么？",
}
KRINO_BEHAVIOR = {"style": "沉稳", "portrait": {"kind": "image", "src": "/static/assets/krino.png"},
                  "voice": {"voice": "zf_032", "rate": 0.95}}


# ---------- 查询与输出 ----------

def get_owned(db: Session, user: User, character_id: str) -> Character:
    c = db.get(Character, character_id)
    if c is None or c.owner_id != user.id:
        raise HTTPException(404, "角色不存在")
    return c


def list_owned(db: Session, user: User) -> list[Character]:
    return list(db.scalars(select(Character).where(Character.owner_id == user.id).order_by(Character.created_at)))


def summary(c: Character) -> dict:
    p = c.persona or {}
    return {"id": c.id, "slug": c.slug, "name": c.name, "tagline": p.get("tagline", ""), "color": p.get("color") or "#1414a8",
            "tags": p.get("tags") or [], "style": (c.behavior or {}).get("style", ""), "version": c.version,
            "official": (c.origin or {}).get("template") == OFFICIAL_SLUG, "source": (c.origin or {}).get("source", ""),
            "edited": c.version > 1, "workshop": (c.origin or {}).get("workshop"), "portrait": (c.behavior or {}).get("portrait"),
            "voice": (c.behavior or {}).get("voice"), "greeting": p.get("greeting", ""),
            "default_expression": (c.behavior or {}).get("default_expression"),
            "model": c.model, "ai": True}


def full(c: Character) -> dict:
    return {**summary(c), "persona": c.persona, "behavior": c.behavior, "lore": c.lore}


def prompt_text(c: Character) -> str:
    """人格配置渲染成给模型看的 Markdown（不含 frontmatter）。"""
    p = c.persona or {}
    parts = [f"# {c.name}", f"简介：{p['tagline']}" if p.get("tagline") else ""]
    for key, (_, title, _) in FIELDS.items():
        if key != "greeting" and (p.get(key) or "").strip():
            parts.append(f"## {title}\n{p[key].strip()}")
    for x in p.get("extra_sections") or []:
        parts.append(f"## {x['title']}\n{x['content']}")
    return "\n\n".join(x for x in parts if x)


def lore_hits(c: Character, query: str, limit: int = 3) -> list[dict]:
    """设定笔记很少（≤40 条），直接按关键词匹配：名称、keys 命中优先，其次正文二元组重合。"""
    from .text import bigrams

    q = (query or "").lower()
    qb = set(bigrams(q))
    scored = []
    for item in c.lore or []:
        s = 0.0
        if item["name"].lower() in q:
            s += 3
        s += sum(2 for k in item.get("keys", []) if k and k.lower() in q)
        if qb:
            s += len(qb & set(bigrams(item["name"] + item["content"]))) / max(4, len(qb))
        if s >= 0.5:
            scored.append((s, item))
    return [x for _, x in sorted(scored, key=lambda t: -t[0])[:limit]]


# ---------- 写入 ----------

def _free_slug(db: Session, owner_id: str, base: str) -> str:
    base = (base or "character")[:56]
    slug, n = base, 2
    while db.scalar(select(Character.id).where(Character.owner_id == owner_id, Character.slug == slug)):
        slug, n = f"{base}-{n}", n + 1
    return slug


def check_slot(db: Session, user: User) -> None:
    n = db.scalar(select(func.count()).select_from(Character).where(Character.owner_id == user.id))
    if n >= settings.companion_limit:
        raise PersonaError(f"最多只能有 {settings.companion_limit} 位角色，先和一位告别再来吧")


def create(db: Session, user: User, *, persona: dict, behavior: dict | None, lore: list | None, slug: str = "",
           origin: dict | None = None) -> Character:
    check_slot(db, user)
    persona = {**persona}
    persona.setdefault("color", "#1414a8")
    check_content(*(v for v in persona.values() if isinstance(v, str)), *(x.get("content", "") for x in lore or []))
    c = Character(owner_id=user.id, slug=_free_slug(db, user.id, slug or persona_io.make_slug(persona.get("name", ""))),
                  persona=persona, behavior=validate_behavior(behavior), lore=lore or [], origin=origin or {})
    db.add(c)
    db.flush()
    return c


def refresh_official(db: Session) -> int:
    """官方设定更新后，用户没改过的官方角色（还是第 1 版）跟着更新；改过的不动，用户可以手动“还原为官方设定”。"""
    n = 0
    for c in db.scalars(select(Character).where(Character.version == 1)):
        if (c.origin or {}).get("template") != OFFICIAL_SLUG:
            continue
        persona, behavior = copy.deepcopy(OFFICIAL["persona"]), validate_behavior(OFFICIAL["behavior"])
        if (c.persona, c.behavior, c.lore) != (persona, behavior, OFFICIAL["lore"]):
            c.persona, c.behavior, c.lore = persona, behavior, copy.deepcopy(OFFICIAL["lore"])
            n += 1
    db.commit()
    return n


def adopt_official(db: Session, user: User) -> Character:
    return create(db, user, persona=copy.deepcopy(OFFICIAL["persona"]), behavior=OFFICIAL["behavior"],
                  lore=copy.deepcopy(OFFICIAL["lore"]), slug=OFFICIAL_SLUG,
                  origin={"source": "official", "template": OFFICIAL_SLUG})


def _snapshot(db: Session, c: Character, note: str) -> None:
    db.add(CharacterVersion(character_id=c.id, version=c.version, persona=c.persona, behavior=c.behavior,
                            lore=c.lore, note=note[:80]))
    c.version += 1


PERSONA_KEYS = (*persona_io.HEAD_FIELDS, *persona_io.TEXT_FIELDS, "extra_sections", "unmapped")


def clean_persona(persona: dict) -> dict:
    """编辑接口只接受已知字段和正确的类型，不把任意结构写进数据库。"""
    unknown = set(persona) - set(PERSONA_KEYS)
    if unknown:
        raise PersonaError(f"不认识的人设字段：{', '.join(sorted(unknown))}")
    out = {}
    for k, v in persona.items():
        if k == "tags":
            if not isinstance(v, list):
                raise PersonaError("tags 必须是列表")
            out[k] = [str(t)[:12] for t in v if str(t).strip()][:8]
        elif k == "extra_sections":
            if not isinstance(v, list):
                raise PersonaError("extra_sections 必须是列表")
            out[k] = [{"title": str(x.get("title", ""))[:40], "content": str(x.get("content", ""))[:persona_io.MAX_FIELD]}
                      for x in v if isinstance(x, dict) and x.get("title")][:20]
        elif k == "unmapped":
            out[k] = v if isinstance(v, dict) else {}
        else:
            if v is not None and not isinstance(v, str):
                raise PersonaError(f"{k} 必须是文字")
            out[k] = v or ""
    return out


def save(db: Session, c: Character, *, persona: dict | None = None, behavior: dict | None = None,
         lore: list | None = None, note: str = "用户编辑") -> Character:
    """明确保存：先存一个旧版本快照，再写入。没有实际变化时什么都不做。"""
    if persona is not None:
        persona = clean_persona(persona)
    new_p = {**c.persona, **persona} if persona is not None else c.persona
    if persona is not None:
        new_p["name"] = str(new_p.get("name") or "").strip()[:40]
        if not new_p["name"]:
            raise PersonaError("名称不能为空")
        if new_p.get("color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(new_p["color"])):
            raise PersonaError("颜色格式应为 #RRGGBB")
        for k in persona_io.TEXT_FIELDS:
            if len(str(new_p.get(k) or "")) > persona_io.MAX_FIELD:
                raise PersonaError(f"「{FIELDS[k][0]}」太长了")
    new_b = validate_behavior(behavior) if behavior is not None else c.behavior
    new_l = persona_io._clean_lore(lore) if lore is not None else c.lore
    if (new_p, new_b, new_l) == (c.persona, c.behavior, c.lore):
        return c
    check_content(*(v for v in new_p.values() if isinstance(v, str)), *(x["content"] for x in new_l))
    _snapshot(db, c, note)
    c.persona, c.behavior, c.lore = new_p, new_b, new_l
    db.flush()
    return c


def install_draft(db: Session, user: User, d: persona_io.Draft, origin: dict) -> Character:
    return create(db, user, persona=d.persona, behavior=d.behavior, lore=d.lore, slug=d.slug, origin=origin)


def package_of(c: Character) -> dict:
    return persona_io.to_package(c.persona, c.behavior, c.lore, c.slug, c.version)


# ---------- 描述生成 ----------

GENERATE_SYSTEM = f"""你是 ACG 角色设定作者，根据用户的描述写一个原创虚拟角色。
要求：不以真实人物或现有作品的角色为原型；不写露骨或成人向内容；中文写作，具体、有画面感。
只输出一个 JSON 对象，不要解释或代码块标记。字段：
{{"name": "2-6 个字", "tagline": "一句话简介，30 字以内", "style": "从 {list(STYLES)} 里选一个",
  "tags": ["3-5 个标签"], "background": "外貌、身份、背景，3-5 句", "personality": "用 - 开头的 3-5 行",
  "values": "价值倾向，用 - 开头的 2-3 行", "speech": "语言风格，用 - 开头的 3 行，含口头禅",
  "interests": "兴趣，用 - 开头的 2-3 行", "preferences": "行为偏好（会怎么动、怎么回应），用 - 开头的 2-3 行",
  "worldview": "她所在的世界，1-2 句", "relationships": "和用户、和其他人的关系，用 - 开头的 1-3 行",
  "greeting": "第一次见面时说的一句话", "lore": [{{"name": "地点或物件", "content": "2-3 句设定"}}]}}"""


def generate_draft(prompt: str, style: str | None) -> dict:
    from .llm import LLMError, get_llm

    prompt = (prompt or "").strip()
    if not prompt:
        raise PersonaError("先描述一下你想要的角色")
    check_content(prompt)
    ask = prompt + (f"\n（互动风格偏好：{style}）" if style in STYLES else "")
    try:
        r = get_llm().complete(system=GENERATE_SYSTEM, messages=[{"role": "user", "content": ask}], max_tokens=2000,
                               context={"task": "persona", "prompt": prompt, "style": style})
    except LLMError as e:
        raise PersonaError(str(e)) from e
    m = re.search(r"\{.*\}", r.text or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise PersonaError("生成结果格式不正确，请重试")
    style = style if style in STYLES else (data.get("style") if data.get("style") in STYLES else "温柔")
    d = persona_io.from_package({"format": persona_io.FORMAT, "persona": data, "lore": data.get("lore") or []})
    return {"persona": d.persona, "behavior": default_behavior(style), "lore": d.lore}


# ---------- 接口 ----------

def _err(fn):
    try:
        return fn()
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e


class CharacterIn(BaseModel):
    persona: dict
    behavior: dict | None = None
    lore: list[dict] | None = None


class SaveIn(BaseModel):
    persona: dict | None = None
    behavior: dict | None = None
    lore: list[dict] | None = None
    model: str | None = None


class SourceIn(BaseModel):
    format: str = Field(pattern="^(md|json)$")
    text: str = Field(max_length=200_000)


class GenerateIn(BaseModel):
    prompt: str = Field(max_length=800)
    style: str | None = None


@router.get("/persona-schema")
def persona_schema():
    """人格编辑器要用的字段、风格预设和可选的表情/动作。"""
    return {"fields": [{"key": k, "label": v[0]} for k, v in FIELDS.items()], "styles": STYLES,
            "expressions": [{"id": e, "label": EXPRESSION_LABELS[e]} for e in EXPRESSIONS],
            "animations": [{"id": a, "label": ANIMATION_LABELS[a]} for a in ANIMATIONS],
            "numeric": {"talkativeness": "话量", "expressiveness": "表情与动作丰富度", "proactivity": "主动程度",
                        "story_affinity": "爱讲故事的程度"}}


@router.get("/characters")
def list_characters(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [summary(c) for c in list_owned(db, user)]


@router.post("/characters")
def create_character(body: CharacterIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = _err(lambda: persona_io.from_package({"format": persona_io.FORMAT, "persona": body.persona,
                                              "behavior": body.behavior or {}, "lore": body.lore or []}))
    c = _err(lambda: install_draft(db, user, d, {"source": "created"}))
    db.commit()
    return full(c)


@router.post("/characters/generate")
def generate(body: GenerateIn, user: User = Depends(current_user)):
    return _err(lambda: generate_draft(body.prompt, body.style))


@router.get("/characters/{cid}")
def get_character(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return full(get_owned(db, user, cid))


@router.put("/characters/{cid}")
def save_character(cid: str, body: SaveIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, cid)
    if body.model is not None:
        if body.model and body.model not in settings.llm_character_models:
            raise HTTPException(400, "不支持这个模型")
        c.model = body.model or None
    _err(lambda: save(db, c, persona=body.persona, behavior=body.behavior, lore=body.lore))
    db.commit()
    return full(c)


@router.get("/characters/{cid}/source")
def get_source(cid: str, format: str = "md", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Markdown / JSON 编辑器的原文。"""
    c = get_owned(db, user, cid)
    if format == "json":
        return {"format": "json", "text": json.dumps(package_of(c), ensure_ascii=False, indent=2)}
    return {"format": "md", "text": persona_io.to_markdown(c.persona, c.behavior, c.lore, c.slug)}


@router.put("/characters/{cid}/source")
def put_source(cid: str, body: SourceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, cid)

    def run():
        if body.format == "md":
            d = persona_io.from_markdown(body.text)
        else:
            try:
                obj = json.loads(body.text)
            except json.JSONDecodeError as e:
                raise PersonaError(f"JSON 格式错误：第 {e.lineno} 行 {e.msg}") from e
            if not isinstance(obj, dict):
                raise PersonaError("JSON 必须是对象")
            d = persona_io.from_package({**obj, "format": persona_io.FORMAT})
        return save(db, c, persona=d.persona, behavior=d.behavior or {"style": c.behavior.get("style", "温柔")},
                    lore=d.lore, note=f"{'Markdown' if body.format == 'md' else 'JSON'} 编辑")
    _err(run)
    db.commit()
    return full(c)


@router.get("/characters/{cid}/versions")
def versions(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, cid)
    rows = db.scalars(select(CharacterVersion).where(CharacterVersion.character_id == c.id)
                      .order_by(CharacterVersion.version.desc())).all()
    return {"current": c.version, "versions": [
        {"version": v.version, "saved_at": v.saved_at.isoformat(), "note": v.note, "name": v.persona.get("name"),
         "preview": persona_io.to_markdown(v.persona, v.behavior, v.lore, c.slug)[:3000]} for v in rows]}


@router.post("/characters/{cid}/versions/{version}/restore")
def restore(cid: str, version: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, cid)
    v = db.scalar(select(CharacterVersion).where(CharacterVersion.character_id == c.id, CharacterVersion.version == version))
    if v is None:
        raise HTTPException(404, "版本不存在")
    _err(lambda: save(db, c, persona=v.persona, behavior=v.behavior, lore=v.lore, note=f"恢复到 v{version}"))
    db.commit()
    return full(c)


@router.post("/characters/{cid}/reset")
def reset(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """官方角色还原成官方设定（当前版本先存一份）。"""
    c = get_owned(db, user, cid)
    if (c.origin or {}).get("template") != OFFICIAL_SLUG:
        raise HTTPException(400, "只有官方角色可以还原")
    _err(lambda: save(db, c, persona=copy.deepcopy(OFFICIAL["persona"]), behavior=OFFICIAL["behavior"],
                      lore=copy.deepcopy(OFFICIAL["lore"]), note="还原为官方设定"))
    db.commit()
    return full(c)


@router.delete("/characters/{cid}")
def farewell(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """告别：角色和你们之间的记忆、聊天、关系都会删除。"""
    c = get_owned(db, user, cid)
    if len(list_owned(db, user)) <= 1:
        raise HTTPException(400, "至少要留一位角色")
    db.execute(WorkshopInstall.__table__.delete().where(WorkshopInstall.character_id == c.id))
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.get("/characters/{cid}/export")
def export(cid: str, format: str = "json", user: User = Depends(current_user), db: Session = Depends(get_db)):
    """导出人设：只有人格配置，不含私人记忆。"""
    c = get_owned(db, user, cid)
    if format == "md":
        body, mime, ext = persona_io.to_markdown(c.persona, c.behavior, c.lore, c.slug), "text/markdown", "md"
    else:
        body, mime, ext = json.dumps(package_of(c), ensure_ascii=False, indent=2), "application/json", "krino.json"
    return Response(body.encode("utf-8"), media_type=f"{mime}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{c.slug}.{ext}"'})


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read(settings.max_import_bytes + 1)
    if len(data) > settings.max_import_bytes:
        raise HTTPException(413, "文件过大")
    return data


@router.post("/characters/import/preview")
async def import_preview(file: UploadFile = File(...), user: User = Depends(current_user)):
    data = await _read_upload(file)
    return _err(lambda: persona_io.parse_any(file.filename or "", data).preview())


@router.post("/characters/import")
async def import_character(file: UploadFile = File(...), user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    data = await _read_upload(file)
    d = _err(lambda: persona_io.parse_any(file.filename or "", data))
    c = _err(lambda: install_draft(db, user, d, {"source": "imported", "format": d.format}))
    db.commit()
    return full(c)
