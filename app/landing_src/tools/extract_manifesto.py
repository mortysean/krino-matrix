"""把宣言 docx 逐段抽成官网用的 JSON。段落、顺序、强调和空行都保留，不把多段并成一段。

    python app/landing_src/tools/extract_manifesto.py "docs/哲学/官网版V3.6.3.docx" V3.6.3

只依赖 Python 标准库读 docx。正文没有段内加粗/斜体时，强调记在整段上（标题粗体、题记斜体），
由页面用原有的标题和题记样式呈现。空段保留在 flow 里，页面用一段空隙，不并进前后正文。
输出 data/manifesto/en.json。中文译文 zh.json 要逐段对齐 sections，英文段数变了要同步改。
"""
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
OUT = Path(__file__).resolve().parent.parent / "data" / "manifesto" / "en.json"


def _runs(p):
    chunks = []
    for r in p.findall(f"{W}r"):
        rpr = r.find(f"{W}rPr")
        bold = italic = False
        if rpr is not None:
            bold = rpr.find(f"{W}b") is not None and rpr.find(f"{W}b").get(f"{W}val") != "0"
            italic = rpr.find(f"{W}i") is not None and rpr.find(f"{W}i").get(f"{W}val") != "0"
        text = "".join((t.text or "") for t in r.findall(f"{W}t"))
        if text:
            chunks.append((text, bold, italic))
    return chunks


def _align(p):
    jc = p.find(f"{W}pPr/{W}jc")
    return jc.get(f"{W}val") if jc is not None else ""


def paragraphs(src):
    with zipfile.ZipFile(src) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(f"{W}p"):
        chunks = _runs(p)
        text = "".join(t for t, _, _ in chunks)
        marks = {(b, i) for _, b, i in chunks}
        emphasis = ""
        if marks == {(True, False)} or (marks and all(b and not i for b, i in marks)):
            emphasis = "bold"
        elif marks == {(False, True)}:
            emphasis = "italic"
        elif len(marks) > 1:
            emphasis = "mixed"
        out.append({"text": text, "emphasis": emphasis, "align": _align(p)})
    return out


def build(src, version):
    paras = paragraphs(src)
    if any(p["emphasis"] == "mixed" for p in paras):
        raise SystemExit("docx 里有段内混排强调，抽取脚本还不能把它拆成逐字标记")
    nonempty = [p for p in paras if p["text"] != ""]
    latin, title, epigraph = nonempty[0], nonempty[1], nonempty[2]
    if latin["emphasis"] != "bold" or epigraph["emphasis"] != "italic":
        raise SystemExit("docx 结构变了：第一段应是粗体拉丁标题，题记应是斜体")
    flow, sections, current = [], [], None
    seen_epigraph = False
    for p in paras:
        if p is latin:
            flow.append({"role": "latin", "text": p["text"], "emphasis": "bold"})
        elif p is title:
            flow.append({"role": "title", "text": p["text"]})
        elif p is epigraph:
            flow.append({"role": "epigraph", "text": p["text"], "emphasis": "italic"})
            seen_epigraph = True
        elif not seen_epigraph:
            flow.append({"role": "blank"})
        elif p["text"] == "":
            flow.append({"role": "blank"})
        elif p["emphasis"] == "bold" and p["align"] == "center":
            current = {"title": p["text"], "paragraphs": []}
            sections.append(current)
            flow.append({"role": "heading", "text": p["text"], "emphasis": "bold"})
        else:
            if current is None:
                raise SystemExit("正文出现在第一个章节标题之前")
            current["paragraphs"].append(p["text"])
            flow.append({"role": "body", "text": p["text"]})
    return {
        "_note": f"原文逐段抽取自 {Path(src).as_posix()}（{version}，官网版）。每个 Word 段落单独保留，含章节之间的空段（flow），没有并段，也没有改字。要换版本：重跑本脚本。",
        "version": version,
        "lang": "en",
        "latin": latin["text"],
        "title": title["text"],
        "epigraph": epigraph["text"],
        "flow": flow,
        "sections": sections,
    }


def main(src, version):
    data = build(src, version)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    nblank = sum(1 for x in data["flow"] if x["role"] == "blank")
    nbody = sum(len(s["paragraphs"]) for s in data["sections"])
    print(f"{OUT}: {len(data['sections'])} sections, {nbody} body paragraphs, {nblank} blank paragraphs, flow {len(data['flow'])}")
    print(" / ".join(s["title"] for s in data["sections"]))


if __name__ == "__main__":
    main(*sys.argv[1:3])
