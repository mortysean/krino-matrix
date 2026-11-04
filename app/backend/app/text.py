"""中文分词与文本小工具。PostgreSQL 自带的全文检索不会切中文：先用 jieba 切好，再交给 'simple' 词典。"""
from __future__ import annotations

import hashlib
import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)

_STOPWORDS = set(
    "的 了 和 是 在 我 你 他 她 它 们 这 那 就 也 都 而 及 与 着 或 一个 没有 不 吗 呢 吧 啊 呀 哦 嗯 么 什么 怎么 用户 "
    "the a an of to and or is are was were be in on at for with it this that".split()
)
_TOKEN_OK = re.compile(r"[\w一-鿿]")
_CJK_RUN = re.compile(r"[一-鿿]{2,}")


def tokenize(text: str) -> list[str]:
    out = []
    for tok in jieba.cut_for_search((text or "").lower()):
        tok = tok.strip()
        if tok and tok not in _STOPWORDS and _TOKEN_OK.search(tok):
            out.append(tok)
    return out


def bigrams(text: str) -> list[str]:
    out = []
    for run in _CJK_RUN.findall((text or "").lower()):
        out += [run[i:i + 2] for i in range(len(run) - 1)]
    return [b for b in out if b not in _STOPWORDS]


def search_text(*parts: str | None) -> str:
    """文档侧：jieba 词 + 中文二元组，未登录词也能被检索到。"""
    text = " ".join(p for p in parts if p)
    return " ".join(tokenize(text) + bigrams(text))


def query_terms(text: str, limit: int = 24) -> list[str]:
    """查询侧：和文档侧对齐（jieba 会把未登录词切成单字，二元组补上），只保留 tsquery 里安全的字符。"""
    seen: dict[str, None] = {}
    for tok in tokenize(text) + bigrams(text):
        safe = re.sub(r"[^\w一-鿿]", "", tok)
        if safe:
            seen.setdefault(safe, None)
        if len(seen) >= limit:
            break
    return list(seen)


def norm(s: str) -> str:
    return re.sub(r"[\s，。！？、,.!?~～…“”\"'「」]+", "", (s or "").lower())


def digest(s: str) -> str:
    return hashlib.sha256(norm(s).encode()).hexdigest()


def similarity(a: str, b: str) -> float:
    """两句话的二元组重合度（0-1），用来判断是不是同一件事。"""
    def grams(s: str) -> set[str]:
        s = norm(s).replace("用户", "")
        return {s[i:i + 2] for i in range(len(s) - 1)} or {s}

    x, y = grams(a), grams(b)
    return len(x & y) / max(1, len(x | y))


def compact(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n] + "…"
