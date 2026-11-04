"""海外版的服务端翻译：和前端共用 app/frontend/i18n/en.json（中文原文 → 英文）。

只翻译返回给用户看的报错（HTTP 4xx/5xx 的 detail）。带变量的句子在表里用 {x} 占位写一条即可匹配。
国内版什么都不做。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import locale, settings


@lru_cache(maxsize=1)
def _table() -> tuple[dict, list]:
    path = settings.frontend_dir / "i18n" / "en.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    pats = []
    for k, v in d.items():
        if "{" in k:
            names = re.findall(r"\{(\w+)\}", k)
            pats.append((re.compile("^" + re.sub(r"\\\{\w+\\\}", "(.+?)", re.escape(k)) + "$", re.S), names, v))
    return d, pats


def tr(s: str) -> str:
    if locale() != "en" or not isinstance(s, str) or not s:
        return s
    d, pats = _table()
    if s in d:
        return d[s]
    for rx, names, out in pats:
        m = rx.match(s)
        if m:
            vals = dict(zip(names, m.groups()))
            return re.sub(r"\{(\w+)\}", lambda x: vals.get(x.group(1), x.group(0)), out)
    return s
