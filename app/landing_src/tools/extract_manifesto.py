"""把宣言 docx 逐段抽成官网用的 JSON（一字不改，只去掉 Word 的格式）。需要 pandoc。
    python app/landing_src/tools/extract_manifesto.py "docs/哲学/官网版V3.6.1.docx" V3.6.1

官网用的是“官网版”（给用户看）；“使命宣言英文版”是给投资人看的完整版，留在 docs/哲学/，不上官网。
docx 的结构：第一行粗体是拉丁文标题，第二行是英文标题，第三行斜体是题记，之后每个整行粗体是章节标题，其余是正文段落。
输出到 data/manifesto/en.json，vision.py 读它。换版本：重跑本脚本即可（build 会检查摘要里的引文仍逐字出自原文）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "manifesto" / "en.json"


def main(src, version):
    md = subprocess.run(["pandoc", src, "-t", "markdown", "--wrap=none"], capture_output=True, text=True, check=True).stdout
    paras = [p.strip() for p in re.split(r"\n\s*\n", md) if p.strip()]
    clean = lambda s: re.sub(r"\\(.)", r"\1", s).replace(" ", " ").strip()
    bold = lambda p: re.fullmatch(r"\*\*(.+?)\*\*", p)
    latin, title, epigraph, rest = clean(bold(paras[0]).group(1)), clean(paras[1]), clean(paras[2].strip("*")), paras[3:]
    sections = []
    for p in rest:
        m = bold(p)
        if m:
            sections.append({"title": clean(m.group(1)), "paragraphs": []})
        else:
            sections[-1]["paragraphs"].append(clean(re.sub(r"(?<!\\)[*_]", "", p)))
    data = {"_note": f"原文逐段抽取自 {Path(src).as_posix()}（{version}，官网版），一字未改。要换版本：用 tools/extract_manifesto.py 重新抽取覆盖本文件。",
            "version": version, "lang": "en", "latin": latin, "title": title, "epigraph": epigraph, "sections": sections}
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    words = sum(len(q.split()) for s in sections for q in s["paragraphs"])
    print(f"{OUT}: {len(sections)} sections, {words} words: " + " / ".join(s["title"] for s in sections))


if __name__ == "__main__":
    main(*sys.argv[1:3])
