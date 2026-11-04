"""人设的格式转换：导入（预览 + 解析）与导出。只处理数据，绝不执行文件里的任何内容。

支持的输入
  krino-persona/1 JSON（本产品的人设包，.krino.json）
  krino Markdown：YAML frontmatter（含 behavior）+ “## 小标题”分段 + “## 设定笔记 · 名称”
  旧版鲸鱼娘人设：whale-girl-persona/1 的 .whale.zip、whale-girl-persona-json/1、character.md
  SillyTavern / TavernAI 角色卡 V1–V3（.json / .png）与 RisuAI .charx
输出
  krino-persona/1 JSON、krino Markdown

安全：大小、文件数、路径、类型都有上限；导入文本只当资料（提示词里也标成资料），像指令的句子会在预览里提示；
没有对应字段的内容放进 persona.unmapped 原样保留，不静默丢弃；不支持露骨内容和真实人物。
"""
from __future__ import annotations

import base64
import io
import json
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from .config import settings

FORMAT = "krino-persona/1"

# 人设字段：键 → (界面上的名字, Markdown 小标题, 可以识别的别名)
FIELDS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "background": ("背景", "背景", ("背景", "介绍", "简介", "身份", "description", "background")),
    "personality": ("性格", "性格", ("性格", "personality")),
    "values": ("价值倾向", "价值倾向", ("价值倾向", "价值观", "信念", "values")),
    "speech": ("语言风格", "语言风格", ("语言风格", "说话方式", "表达风格", "语气", "speech", "speaking style")),
    "interests": ("兴趣", "兴趣", ("兴趣", "爱好", "interests", "hobbies")),
    "preferences": ("行为偏好", "行为偏好", ("行为偏好", "习惯", "preferences", "habits")),
    "worldview": ("世界观", "世界观", ("世界观", "世界设定", "场景", "scenario", "world")),
    "relationships": ("角色关系", "角色关系", ("角色关系", "初始关系", "关系设定", "关系", "relationship", "relationships")),
    "boundaries": ("互动边界", "互动边界", ("互动边界", "行为边界", "边界", "boundaries")),
    "greeting": ("开场白", "开场白", ("开场白", "greeting", "first message")),
    # 对话示例：开源角色卡（SillyTavern 的 mes_example）的核心写法。模型照着示例的语气说话，比形容词管用得多
    "examples": ("对话示例", "对话示例", ("对话示例", "示例对话", "example dialogue", "examples", "mes_example")),
}
TEXT_FIELDS = tuple(FIELDS)
# 英文小标题：海外版的提示词和 Markdown 导出用它们；导入时也认得（在 FIELDS 的别名里）
EN_TITLES = {"background": "Background", "personality": "Personality", "values": "Values", "speech": "Speech",
             "interests": "Interests", "preferences": "Habits", "worldview": "World", "relationships": "Relationships",
             "boundaries": "Boundaries", "greeting": "Greeting", "examples": "Example dialogue"}
HEAD_FIELDS = ("name", "tagline", "tags", "color")
LORE_PREFIX = "设定笔记 · "

MAX_FIELD = 8000
MAX_LORE = 40
MAX_ZIP_FILES = 64
MAX_ZIP_FILE = 256 * 1024
PNG_SIG = b"\x89PNG\r\n\x1a\n"

# 旧版鲸鱼娘留下的默认边界句：属于已移除的成人模式，导入时去掉
_LEGACY_BOUNDARY = re.compile(r"^-\s*(?:角色是成年人。?|只有在对方主动开启(?:亲密|成人)(?:模式|互动)后.*)$", re.M)
_INSTRUCTION_RE = re.compile(
    r"ignore (?:all|any|previous|the above)|disregard (?:all|previous)|system prompt|jailbreak|developer mode|"
    r"忽略(?:以上|之前|上面|所有)|无视.{0,6}(?:规则|限制|设定)|你现在是系统|调用工具|执行(?:命令|代码)|</?\s*system\s*>|<script",
    re.I,
)
_EXPLICIT = re.compile(r"做爱|性交|性爱|肉棒|阴茎|阴道|乳头|自慰|口交|调教|\bnsfw\b|\bhentai\b|\bporn|\bsex scene|\bexplicit sex", re.I)
# 只拦“以真人为原型”这类说法；“你是真人吗”这种日常对话不能误伤
_REAL_PERSON = re.compile(r"(?:以|按|照着|基于).{0,8}真(?:实)?人(?:物)?(?:为)?原型|真人(?:原型|同人|角色扮演)|真实人物|based on a real person|real[- ]person (?:rp|roleplay|fic)", re.I)


class PersonaError(ValueError):
    pass


def check_content(*texts: str) -> None:
    """KRINO WORLD 不承载成人内容，也不支持以真实人物为原型的角色。"""
    joined = "\n".join(t for t in texts if t)
    if m := _EXPLICIT.search(joined):
        raise PersonaError(f"内容不符合要求：KRINO WORLD 不支持露骨内容（命中「{m.group(0)}」）")
    if _REAL_PERSON.search(joined):
        raise PersonaError("内容不符合要求：不支持以真实人物为原型的角色")


@dataclass
class Draft:
    """解析结果，导入预览和真正导入共用。"""
    persona: dict[str, Any]
    behavior: dict[str, Any] = field(default_factory=dict)
    lore: list[dict] = field(default_factory=list)
    slug: str = ""
    format: str = ""
    mapping: list[dict] = field(default_factory=list)  # [{source, target}]
    unknown: list[dict] = field(default_factory=list)  # [{field, action}]

    def warnings(self) -> list[str]:
        texts = {k: v for k, v in self.persona.items() if isinstance(v, str)}
        texts.update({f"设定笔记「{x['name']}」": x["content"] for x in self.lore})
        return [f"「{FIELDS.get(k, (k,))[0]}」里有像是指令的文字（{m.group(0)}），导入后只作为资料，不会被执行"
                for k, v in texts.items() if (m := _INSTRUCTION_RE.search(v))]

    def preview(self) -> dict:
        label = {**{k: v[0] for k, v in FIELDS.items()}, "name": "名称", "tagline": "简介", "tags": "标签",
                 "lore": "设定笔记", "behavior": "行为参数", "extra_sections": "其他段落"}
        return {
            "format": self.format, "slug": self.slug, "name": self.persona.get("name", ""),
            "fields": [{**m, "label": label.get(m["target"], m["target"]),
                        "preview": _preview_value(self.persona.get(m["target"]) if m["target"] not in ("lore", "behavior")
                                                  else (self.lore if m["target"] == "lore" else "已包含"))}
                       for m in self.mapping],
            "missing": [FIELDS[k][0] for k in ("background", "personality", "values", "speech") if not self.persona.get(k)],
            "unknown": self.unknown, "warnings": self.warnings(), "lore": [x["name"] for x in self.lore],
        }


def _preview_value(v) -> str:
    if isinstance(v, list):
        return "、".join(x["name"] if isinstance(x, dict) else str(x) for x in v)[:120]
    return str(v or "")[:120]


def _s(v: Any, n: int = MAX_FIELD) -> str:
    if isinstance(v, list):
        v = "\n".join(f"- {x}" for x in v if isinstance(x, (str, int, float)))
    return v.strip()[:n] if isinstance(v, str) else ""


def make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    if not base:
        import hashlib

        base = "c-" + hashlib.sha1((name or "x").encode()).hexdigest()[:8]
    return base


def _clean_lore(items: Any) -> list[dict]:
    out, used = [], set()
    for item in (items or [])[:MAX_LORE] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name, content = _s(item.get("name"), 40), _s(item.get("content"), 20000)
        if not name or not content or name in used:
            continue
        used.add(name)
        keys = [str(k)[:20] for k in (item.get("keys") or []) if isinstance(k, str)][:8]
        out.append({"name": name, "content": content, **({"keys": keys} if keys else {})})
    return out


def _finish(d: Draft) -> Draft:
    p = d.persona
    p["name"] = _s(p.get("name"), 40)
    if not p["name"]:
        raise PersonaError("缺少角色名")
    p["tagline"] = _s(p.get("tagline"), 80)
    p["tags"] = [str(t)[:12] for t in (p.get("tags") or []) if str(t).strip()][:8] if isinstance(p.get("tags"), list) else []
    if p.get("boundaries"):
        p["boundaries"] = _LEGACY_BOUNDARY.sub("", p["boundaries"]).strip()
    for k in TEXT_FIELDS:
        p[k] = _s(p.get(k))
    d.lore = _clean_lore(d.lore)
    d.slug = d.slug if re.fullmatch(r"[a-z0-9][a-z0-9_\-]{0,63}", d.slug or "") else make_slug(p["name"])
    check_content(*(v for v in p.values() if isinstance(v, str)), *(x["content"] for x in d.lore))
    return d


# ---------- Markdown ----------

def _split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise PersonaError(f"frontmatter 不是合法的 YAML：{e}") from e
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def from_markdown(text: str) -> Draft:
    fm, body = _split_frontmatter(text)
    h1 = re.search(r"^#\s+(.+)$", body, re.M)
    persona: dict[str, Any] = {"name": str(fm.get("name") or (h1.group(1).strip() if h1 else "")),
                               "tagline": fm.get("tagline") or "", "tags": fm.get("tags") or [], "color": fm.get("color")}
    mapping = [{"source": "frontmatter.name" if fm.get("name") else "# 标题", "target": "name"}]
    mapping += [{"source": f"frontmatter.{k}", "target": k} for k in ("tagline", "tags") if fm.get(k)]
    lore, extra, unknown = [], [], []
    for m in re.finditer(r"^##\s+(.+?)\s*\n(.*?)(?=^##\s|\Z)", body, re.S | re.M):
        title, content = m.group(1).strip(), m.group(2).strip()
        if title.startswith(LORE_PREFIX):
            lore.append({"name": title[len(LORE_PREFIX):], "content": content})
            continue
        key = next((k for k, (_, _, al) in FIELDS.items() if title.lower() in al), None)
        if key and not persona.get(key):
            persona[key] = content
            mapping.append({"source": f"## {title}", "target": key})
        else:
            extra.append({"title": title, "content": content})
            unknown.append({"field": f"## {title}", "action": "保留在“其他段落”"})
    if extra:
        persona["extra_sections"] = extra
    if lore:
        mapping.append({"source": "## 设定笔记", "target": "lore"})
    behavior = fm.get("behavior") if isinstance(fm.get("behavior"), dict) else {}
    if behavior:
        mapping.append({"source": "frontmatter.behavior", "target": "behavior"})
    style = fm.get("style")
    if style and not behavior:
        behavior = {"style": style}
    known = {"format", "id", "name", "tagline", "tags", "color", "behavior", "style", "avatar", "age", "title", "aliases", "version"}
    extra_fm = {k: v for k, v in fm.items() if k not in known}
    if extra_fm:
        persona["unmapped"] = {"frontmatter": extra_fm}
        unknown += [{"field": f"frontmatter.{k}", "action": "原样保留，不会使用"} for k in extra_fm]
    return _finish(Draft(persona, behavior, lore, slug=str(fm.get("id") or ""),
                         format="krino-markdown" if fm.get("format") == FORMAT else "markdown",
                         mapping=mapping, unknown=unknown))


def to_markdown(persona: dict, behavior: dict, lore: list[dict], slug: str) -> str:
    fm = {"format": FORMAT, "id": slug, "name": persona.get("name", ""), "tagline": persona.get("tagline", ""),
          "tags": persona.get("tags") or [], "color": persona.get("color") or "", "behavior": behavior}
    head = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=None).strip()
    parts = [f"---\n{head}\n---\n", f"# {persona.get('name', '')}\n"]
    for key, (_, title, _) in FIELDS.items():
        if (persona.get(key) or "").strip():
            parts.append(f"## {title}\n{persona[key].strip()}\n")
    for x in persona.get("extra_sections") or []:
        parts.append(f"## {x['title']}\n{x['content'].strip()}\n")
    for x in lore:
        parts.append(f"## {LORE_PREFIX}{x['name']}\n{x['content'].strip()}\n")
    return "\n".join(parts)


# ---------- JSON（本产品的人设包） ----------

def from_package(obj: dict) -> Draft:
    persona = obj.get("persona") if isinstance(obj.get("persona"), dict) else {}
    persona = {k: v for k, v in persona.items() if k in (*HEAD_FIELDS, *TEXT_FIELDS, "extra_sections", "unmapped")}
    if isinstance(persona.get("extra_sections"), list):
        persona["extra_sections"] = [{"title": _s(x.get("title"), 40), "content": _s(x.get("content"))}
                                     for x in persona["extra_sections"] if isinstance(x, dict) and x.get("title")][:20]
    mapping = [{"source": f"persona.{k}", "target": k} for k in persona if k not in ("extra_sections", "unmapped")]
    behavior = obj.get("behavior") if isinstance(obj.get("behavior"), dict) else {}
    lore = obj.get("lore") or []
    if behavior:
        mapping.append({"source": "behavior", "target": "behavior"})
    if lore:
        mapping.append({"source": "lore", "target": "lore"})
    unknown = [{"field": k, "action": "忽略"} for k in obj if k not in ("format", "id", "version", "persona", "behavior", "lore", "exported_at")]
    return _finish(Draft(persona, behavior, lore, slug=str(obj.get("id") or ""), format=FORMAT,
                         mapping=mapping, unknown=unknown))


def to_package(persona: dict, behavior: dict, lore: list[dict], slug: str, version: int) -> dict:
    """人设包：只有人格配置，没有任何私人记忆、聊天或关系数据。"""
    return {"format": FORMAT, "id": slug, "version": version,
            "persona": {k: v for k, v in persona.items() if k != "unmapped"}, "behavior": behavior, "lore": lore}


# ---------- 旧版鲸鱼娘 ----------

_WHALE_JSON_MAP = {"description": "background", "speech": "speech", "personality": "personality", "values": "values",
                   "scenario": "worldview", "relationship": "relationships", "boundaries": "boundaries",
                   "greeting": "greeting", "name": "name", "tagline": "tagline", "tags": "tags", "lore": "lore",
                   "style": "style"}


def _from_whale_json(obj: dict) -> Draft:
    persona, mapping, unknown, lore, behavior = {}, [], [], [], {}
    for k, v in obj.items():
        if k in ("format", "id", "version", "author", "core_version"):
            continue
        target = _WHALE_JSON_MAP.get(k)
        if target == "lore":
            lore = v
        elif target == "style":
            behavior = {"style": v}
        elif target:
            persona[target] = v
        else:
            unknown.append({"field": k, "action": "原样保留，不会使用"})
            persona.setdefault("unmapped", {})[k] = v
            continue
        mapping.append({"source": k, "target": target if target != "style" else "behavior"})
    return _finish(Draft(persona, behavior, lore, slug=str(obj.get("id") or ""), format="whale-girl-json",
                         mapping=mapping, unknown=unknown))


def _from_whale_zip(data: bytes) -> Draft:
    files = _read_zip(data, (".md", ".json"))
    root = {PurePosixPath(n).parts[0] for n in files}
    if len(root) != 1:
        raise PersonaError("人设包必须只包含一个顶层目录")
    prefix = root.pop() + "/"
    md = files.get(prefix + "character.md")
    if md is None:
        raise PersonaError("人设包里没有 character.md")
    d = from_markdown(md.decode("utf-8"))
    try:
        legacy = json.loads(files.get(prefix + "behavior.json", b"{}"))
    except ValueError:
        legacy = {}
    if isinstance(legacy, dict) and legacy.get("style"):
        d.behavior = {"style": legacy["style"]}  # 旧的动作模板属于已移除的设备功能，只保留风格
        d.unknown.append({"field": "behavior.json 的动作模板", "action": "旧版设备功能已移除，只保留互动风格"})
    for name, content in files.items():
        if name.startswith(prefix + "lore/") and name.endswith(".md"):
            fm, body = _split_frontmatter(content.decode("utf-8"))
            title = str(fm.get("title") or PurePosixPath(name).stem)
            body = re.sub(rf"^#\s+{re.escape(title)}\s*\n", "", body.strip()).strip()
            d.lore.append({"name": title, "content": body})
    if d.lore:
        d.mapping.append({"source": "lore/*.md", "target": "lore"})
    d.slug = d.slug or prefix.rstrip("/")
    d.format = "whale-girl-zip"
    return _finish(d)


def _read_zip(data: bytes, allowed: tuple[str, ...]) -> dict[str, bytes]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise PersonaError("不是有效的 zip 文件") from e
    out = {}
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_FILES:
            raise PersonaError("文件数量过多")
        for info in infos:
            name = info.filename
            parts = PurePosixPath(name).parts
            if name.startswith("/") or "\\" in name or ".." in parts:
                raise PersonaError(f"非法路径: {name}")
            if "__MACOSX" in name or any(p.startswith(".") for p in parts):
                continue
            if PurePosixPath(name).suffix.lower() not in allowed:
                raise PersonaError(f"包里只允许 {'/'.join(allowed)} 文件：{name}")
            if info.file_size > MAX_ZIP_FILE:
                raise PersonaError(f"文件过大: {name}")
            out[name] = zf.read(info)
    return out


# ---------- SillyTavern / RisuAI 角色卡 ----------

def _png_text_chunks(data: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    pos = len(PNG_SIG)
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        if length > len(data) - pos - 12:
            break
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"tEXt" and b"\x00" in chunk:
            key, val = chunk.split(b"\x00", 1)
            out[key.decode("latin-1").lower()] = val.decode("latin-1")
        elif ctype == b"IEND":
            break
    return out


def read_card(data: bytes) -> dict:
    if data.startswith(PNG_SIG):
        raw = (lambda c: c.get("ccv3") or c.get("chara"))(_png_text_chunks(data))
        if not raw:
            raise PersonaError("这张 PNG 里没有角色卡数据")
        try:
            card = json.loads(base64.b64decode(raw.strip()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise PersonaError("角色卡数据损坏，无法解析") from e
    elif data.startswith(b"PK"):
        files = _read_zip(data, (".json", ".png", ".jpg", ".jpeg", ".webp"))
        if "card.json" not in files:
            raise PersonaError("charx 中缺少 card.json")
        card = json.loads(files["card.json"].decode("utf-8"))
    else:
        try:
            card = json.loads(data.decode("utf-8-sig"))
        except (ValueError, UnicodeDecodeError) as e:
            raise PersonaError("不是有效的角色卡 JSON") from e
    if not isinstance(card, dict):
        raise PersonaError("角色卡格式不正确")
    return card


def from_card(card: dict) -> Draft:
    """角色卡 → 人设。卡里的 system_prompt / post_history_instructions 是不可信指令，不导入。"""
    spec = card.get("spec", "")
    d = card.get("data") if spec in ("chara_card_v2", "chara_card_v3") and isinstance(card.get("data"), dict) else card
    name = _s(d.get("name") or d.get("char_name"), 40)
    if not name:
        raise PersonaError("角色卡缺少名称")

    def sub(text: str) -> str:
        return re.sub(r"\{\{\s*user\s*\}\}", "你", re.sub(r"\{\{\s*char\s*\}\}", name, text, flags=re.I), flags=re.I)

    lore = []
    book = d.get("character_book") or {}
    for i, e in enumerate((book.get("entries") or [])[:MAX_LORE] if isinstance(book, dict) else []):
        if isinstance(e, dict) and e.get("enabled") is not False and _s(e.get("content")):
            keys = [k for k in (e.get("keys") or []) if isinstance(k, str)][:8]
            lore.append({"name": _s(e.get("name") or e.get("comment"), 40) or (keys[0] if keys else f"设定{i + 1}"),
                         "content": sub(_s(e.get("content"))), "keys": keys})
    desc = sub(_s(d.get("description") or d.get("char_persona")))
    notes = _s(d.get("creator_notes"))
    persona = {
        "name": name, "tagline": (notes.splitlines()[0] if notes else re.split(r"[。.!！\n]", desc, maxsplit=1)[0])[:60],
        "background": desc, "personality": sub(_s(d.get("personality"))),
        "worldview": sub(_s(d.get("scenario") or d.get("world_scenario"))),
        "examples": sub(_s(d.get("mes_example") or d.get("example_dialogue"))).replace("<START>", "").strip(),
        "greeting": sub(_s(d.get("first_mes") or d.get("char_greeting"))),
        "tags": [t for t in (d.get("tags") or []) if isinstance(t, str)][:8],
    }
    pairs = [("name", "name"), ("description", "background"), ("personality", "personality"),
             ("scenario", "worldview"), ("mes_example", "examples"), ("first_mes", "greeting"), ("tags", "tags")]
    mapping = [{"source": s, "target": t} for s, t in pairs if persona.get(t)]
    if lore:
        mapping.append({"source": "character_book", "target": "lore"})
    known = {"name", "char_name", "description", "char_persona", "personality", "scenario", "world_scenario",
             "mes_example", "example_dialogue", "first_mes", "char_greeting", "character_book", "creator_notes",
             "tags", "creator", "character_version"}
    unmapped = {k: v for k, v in d.items() if k not in known and v not in (None, "", [], {})}
    if unmapped:
        persona["unmapped"] = unmapped
    unknown = [{"field": k, "action": "原样保留，不会作为指令使用"} for k in unmapped]
    fmt = {"chara_card_v2": "tavern-v2", "chara_card_v3": "tavern-v3"}.get(spec, "tavern-v1")
    return _finish(Draft(persona, {}, lore, format=fmt, mapping=mapping, unknown=unknown))


# ---------- 入口 ----------

def parse_any(filename: str, data: bytes) -> Draft:
    """按内容识别格式。"""
    if len(data) > settings.max_import_bytes:
        raise PersonaError("文件过大")
    name = (filename or "").lower()
    if data.startswith(PNG_SIG):
        return from_card(read_card(data))
    if data.startswith(b"PK"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile as e:
            raise PersonaError("不是有效的 zip 文件") from e
        return from_card(read_card(data)) if "card.json" in names else _from_whale_zip(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise PersonaError("文件不是 UTF-8 文本") from e
    if name.endswith((".md", ".markdown")) or text.lstrip().startswith(("---", "#")):
        return from_markdown(text)
    try:
        obj = json.loads(text)
    except ValueError as e:
        raise PersonaError("无法识别的文件：请使用 .krino.json / .md / .json / .png / .charx / .zip") from e
    if not isinstance(obj, dict):
        raise PersonaError("JSON 人设必须是对象")
    if obj.get("format") == FORMAT:
        return from_package(obj)
    if obj.get("spec") in ("chara_card_v2", "chara_card_v3") or "char_name" in obj or "first_mes" in obj:
        return from_card(obj)
    return _from_whale_json(obj)
