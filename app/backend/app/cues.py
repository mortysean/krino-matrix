"""回复里括号写的动作（“（歪头）”“(waves)”）→ 人物投影上的动作和表情，气泡里换成颜文字。

模型照常在括号里写很短的动作或神态；这里按关键词认出来：
  - 能对上预设动作（personas.ANIMATIONS）和表情（personas.EXPRESSIONS）的，交给 chat._actions 演出来
  - 括号文字在气泡里换成一个颜文字，朗读时颜文字会被跳过（voice.speakable）
本来就是颜文字的括号（“(｀・ω・´)”“(T_T)”）原样保留。认不出的动作也换成颜文字，只是不做动作。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 关键词 → (动作, 表情, 颜文字)。按顺序匹配，越具体的越靠前。动作或表情可以是 None
RULES: list[tuple[tuple[str, ...], str | None, str | None, str]] = [
    (("转圈", "转了个圈", "转了一圈", "转身", "spin", "twirl"), "spin", "happy", "～(￣▽￣～)"),
    (("挥手", "招手", "摆手", "wave", "waving"), "wave", "happy", "ヾ(≧▽≦*)o"),
    (("鞠躬", "行礼", "bow"), "bow", "calm", "m(_ _)m"),
    (("摇头", "shake", "shakes head"), "shake_head", None, "(￣ー￣)ゞ"),
    (("点头", "nod"), "nod", "happy", "(￣▽￣)ゞ"),
    (("歪头", "歪着头", "疑惑", "tilt", "tilts head", "puzzled"), "tilt_head", "surprised", "(・ω・?)"),
    (("托腮", "思考", "想了想", "沉思", "挠头", "think", "ponder", "hmm"), "think", "focused", "(￣～￣;)"),
    (("欢呼", "蹦", "跳", "举手", "握拳", "cheer", "jump", "fist pump"), "cheer", "happy", "٩(ˊᗜˋ)و"),
    (("推眼镜", "推了推眼镜", "扶眼镜", "glasses"), "glasses", "focused", "(・_・)ゞ"),
    (("咖啡", "抿", "coffee", "sip"), "coffee", "calm", "(￣ー￣)☕"),
    (("翻书", "看书", "笔记本", "翻开", "reads", "notebook", "flips"), "read", "focused", "φ(・ω・ )"),
    (("敲键盘", "打字", "键盘", "typing", "types"), "type", "focused", "(・ω・)ﾉ⌨"),
    (("甩尾巴", "摇尾巴", "甩了甩尾巴", "尾巴", "swish", "tail"), "tail", "happy", "～(^ω^)～"),
    (("扒饭", "扒了", "吃饭", "白饭", "一碗", "eats rice", "rice"), "eat", "happy", "(๑´ڡ`๑)"),
    (("伸懒腰", "stretch"), "stretch", "sleepy", "(ﾉ´ヮ`)ﾉ"),
    (("打瞌睡", "打盹", "睡着", "鼻涕泡", "doze", "nods off", "dozes"), "sleepy", "sleepy", "(－ω－) zzZ"),
    (("脸红", "害羞", "捂脸", "低头", "扭捏", "撩", "blush", "shy", "hides face"), "shy", "shy", "(〃∀〃)"),
    (("叉腰", "哼", "鼓腮", "瞪", "气鼓鼓", "跺脚", "抱臂", "抱着胳膊", "pout", "huff", "glare", "stomp", "crosses arms"), "pout", "angry", "(｀へ´)"),
    (("哭", "抽泣", "委屈", "眼泪", "难过", "叹气", "扶额", "cry", "sob", "sniff", "sigh"), "sad", "sad", "(╥﹏╥)"),
    (("担心", "不安", "紧张", "worried", "nervous"), None, "worried", "(°ー°〃)"),
    (("哈欠", "揉眼", "困", "yawn", "sleepy"), "sleepy", "sleepy", "(－ω－) zzZ"),
    (("惊", "瞪大眼", "愣", "吓", "挑眉", "gasp", "surprised", "startle"), "surprised", "surprised", "(⊙o⊙)"),
    (("吃", "咬", "嚼", "eat", "munch", "chew"), "eat", "happy", "(๑´ڡ`๑)"),
    (("笑", "眨眼", "得意", "坏笑", "smile", "grin", "giggle", "laugh", "wink", "smirk"), "happy", "happy", "(￣▽￣)"),
    (("认真", "盯", "focus", "stare"), None, "focused", "(・_・)ゞ"),
]
DEFAULT_KAOMOJI = "(・ω・)"
# 没对上上面的规则、但明显是动作的（抱、拍、戳、凑近……）：换成通用颜文字。都不像的（“3（三）个”这种补充说明）原样保留
ACTION_WORDS = ("抬手", "示意", "抱", "拍", "摸", "戳", "拉", "递", "伸", "指", "凑", "靠", "躲", "趴", "坐", "蹲", "晃", "甩", "抓", "捏",
                "搓", "掏", "翻", "偷偷", "小声", "轻轻", "悄悄", "看了", "看向", "望", "眯眼", "撇嘴", "嘟嘴", "比", "拍拍", "扑",
                "hug", "pat", "poke", "lean", "look", "whisper", "peek", "hold", "point", "nudge", "squint", "hide")

# 括号：中文全角或半角，里面不超过 40 个字、不跨行、不嵌套
BRACKET = re.compile(r"[（(]([^（()）\n]{1,40})[）)]")
_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z]{3,}")


@dataclass
class Cue:
    text: str
    animation: str | None
    expression: str | None


def is_action(inner: str) -> bool:
    """括号里是动作描述（有汉字或英文单词），而不是颜文字。"""
    return bool(_CJK.search(inner) or _WORD.search(inner))


def match(inner: str) -> tuple[str | None, str | None, str] | None:
    """认出的动作 → (动作, 表情, 颜文字)；不像动作的 → None。"""
    low = inner.lower()
    for keys, anim, expr, kao in RULES:
        if any(k in low for k in keys):
            return anim, expr, kao
    if any(k in low for k in ACTION_WORDS):
        return None, None, DEFAULT_KAOMOJI
    return None


def convert(text: str, *, tidy: bool = True) -> tuple[str, list[Cue]]:
    """把括号动作换成颜文字，返回新文字和认出的动作（按出现顺序）。"""
    cues: list[Cue] = []

    def sub(m: re.Match) -> str:
        inner = m.group(1).strip()
        hit = match(inner) if is_action(inner) else None
        if hit is None:
            return m.group(0)
        anim, expr, kao = hit
        cues.append(Cue(inner, anim, expr))
        return kao

    out = BRACKET.sub(sub, text)
    if tidy:  # 流式片段不整理空白，免得英文单词粘在一起
        out = re.sub(r"[ \t]{2,}", " ", out).strip()
    return out, cues


def open_bracket_at(text: str) -> int:
    """流式输出时：末尾如果有还没闭合的括号（可能是动作写到一半），返回它的位置，否则 -1。"""
    i = max(text.rfind("（"), text.rfind("("))
    if i < 0 or "）" in text[i:] or ")" in text[i:] or "\n" in text[i:] or len(text) - i > 42:
        return -1
    return i
