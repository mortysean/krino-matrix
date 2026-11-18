"""宣言与 Krino Tree：读数据、校验、算状态，生成 /<地区>/vision/（科技树 + 当前进度）、
/<地区>/manifesto/（宣言全文）、/<地区>/apocalypse/（启示与应验：预言与更新通报）和 /<地区>/vision/tree.json（节点详情，页面加载）。build.py 调用。

数据全在 data/ 下，和界面分开：
  manifesto/en.json          宣言原文（官网版，逐段；tools/extract_manifesto.py 从 docx 抽取）
  manifesto/zh.json          国内站的中文稿（仍是 V3.6.1）。英文 V3.6.3 不要求中文段数对齐，也不把这份旧稿标成新版本
  apocalypse/entries.json    “启示与应验”栏目的条目（宣言是第一条）
  tree/nodes.zh.json         科技树母版（现为 V5，原样抽取） tree/nodes.en.json     英文译文
  tree/structure.json        四个阶段 → 母版的分段/枝干/顺序，逐条依赖
  tree/status.json           实际进度（只写核实过的）    tree/labels.json        界面文字
官网只放给用户看的“官网版”宣言；给投资人的完整英文版留在 docs/哲学/，不上官网。母版里出自投资人版的说法
（公理四“垄断”、护城河）在官网上显示时去掉（_public），母版数据不动。
节点的两个维度分开：性质（产品/研究/外部突破/阶段终点）来自母版；进度（已完成/研发中/已规划/远期）只来自 status.json，
阶段终点和汇合门由前置自动算。
"""
import html
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
esc = html.escape
STATUSES = ("completed", "in_progress", "planned", "vision")
NATURES = ("product", "research", "external", "milestone")


def _load(p):
    return json.loads((DATA / p).read_text(encoding="utf-8"))


TREE = _load("tree/nodes.zh.json")
EN = _load("tree/nodes.en.json")
ST = _load("tree/structure.json")
STATUS = _load("tree/status.json")
LABELS = _load("tree/labels.json")
MANIFESTO = {"en": _load("manifesto/en.json"), "zh": _load("manifesto/zh.json")}


def _manifesto_locale_errors():
    """英文 V3.6.3 自己核对。中文稿是另一份稿，段数不必跟着英文走，也不能把旧中文标成这个新版本。"""
    en, zh = MANIFESTO["en"], MANIFESTO["zh"]
    errs = []
    if en.get("version") != "V3.6.3":
        errs.append(f"英文官网宣言版本是 {en.get('version')!r}，这一版要核的是 V3.6.3")
    flow_bodies = [i["text"] for i in en.get("flow") or [] if i.get("role") == "body"]
    section_bodies = [p for s in en["sections"] for p in s["paragraphs"]]
    flow_heads = [i["text"] for i in en.get("flow") or [] if i.get("role") == "heading"]
    section_heads = [s["title"] for s in en["sections"]]
    if not flow_bodies or flow_bodies != section_bodies or flow_heads != section_heads:
        errs.append("英文 V3.6.3 的 flow 和 sections 必须逐段、逐标题相同")
    if zh.get("version") == "V3.6.3":
        errs.append("中文稿被标成 V3.6.3。没有授权的中文 V3.6.3 原稿，不能把旧中文或一份新译稿标成这个版本")
    return errs


_locale_errs = _manifesto_locale_errors()
if _locale_errs:
    raise SystemExit("宣言稿有误：\n  " + "\n  ".join(_locale_errs))
APOCALYPSE = _load("apocalypse/entries.json")

PHASE_OF, COL_OF = {}, {}
for ph in ST["phases"]:
    for ci, col in enumerate(ph["columns"]):
        for nid in col["nodes"]:
            PHASE_OF[nid], COL_OF[nid] = ph["id"], ci
    for nid in ph.get("root", []) + ph.get("gates", []) + [ph["end"]]:
        PHASE_OF[nid] = ph["id"]
REQ = ST["requires"]
ANY = ST.get("anyOf", {})
MILESTONES = set(ST["milestones"])


def strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def _manifesto_plain():
    flow = MANIFESTO["en"].get("flow") or []
    bodies = [item["text"] for item in flow if item.get("role") == "body"]
    return "\n".join(bodies)


def _verified_quotes(text, plain):
    """标了 V3.6.3 的引号必须是英文原文的连续子串。待核的括号不算引文。"""
    body = re.sub(r"<span class=\"cite-pending\">.*?</span>", "", text or "", flags=re.S)
    body = re.sub(r"\[Pending review:.*?\]", "", html.unescape(re.sub(r"<[^>]+>", "", body)), flags=re.S)
    idxs = [i for i, ch in enumerate(body) if ch == '"']
    i = 0
    bad = []
    while i < len(idxs):
        best = None
        for j in range(len(idxs) - 1, i, -1):
            inner = body[idxs[i] + 1:idxs[j]]
            if len(inner) >= 12 and inner in plain:
                best = j
                break
        if best is None:
            for j in range(i + 1, len(idxs)):
                inner = body[idxs[i] + 1:idxs[j]]
                if len(inner) >= 12 and '"' not in inner and inner not in plain:
                    bad.append(inner)
                break
            i += 1
            continue
        i = best + 1
    return bad


def validate():
    """数据一致性：每个节点各在且只在一个位置；依赖都指向存在的节点；多重前置和母版的 MULTI_EDGES 一致；
    英文译文齐全；写成已完成的必须有核实依据。出错直接停，别生成一个错的站。"""
    ids = set(TREE["NODES"])
    placed = [n for ph in ST["phases"] for c in ph["columns"] for n in c["nodes"]] + \
             [n for ph in ST["phases"] for n in ph.get("root", []) + ph.get("gates", []) + [ph["end"]]]
    errs = []
    if sorted(placed) != sorted(ids):
        errs.append(f"阶段里的节点和母版不一致：多 {set(placed) - ids}，少 {ids - set(placed)}，重复 {[n for n in placed if placed.count(n) > 1]}")
    if set(REQ) != ids:
        errs.append(f"requires 缺 {ids - set(REQ)}")
    for n, rs in list(REQ.items()) + list(ANY.items()):
        for r in rs:
            if r not in ids:
                errs.append(f"{n} 依赖了不存在的 {r}")
    for n, rs in (TREE.get("MULTI_EDGES") or {}).items():  # 母版（V3 起）不画跨节点连线，没有这个对象；有就逐条比对
        if set(rs) != set(REQ[n]):
            errs.append(f"{n} 的依赖 {REQ[n]} 和母版多重前置 {rs} 不一致")
    for n in ids:
        if n not in EN or not EN[n].get("summary") or not EN[n].get("body"):
            errs.append(f"{n} 缺英文译文")
    for n, s in STATUS["nodes"].items():
        if s["status"] not in STATUSES:
            errs.append(f"{n} 的进度 {s['status']} 不认识")
        if n in MILESTONES:
            errs.append(f"{n} 是阶段终点/汇合门，进度由前置自动算，别写在 status.json")
        if s["status"] == "completed" and not (s.get("evidence") and s.get("done")):
            errs.append(f"{n} 标成已完成却没有 evidence/done")
    errs.extend(_manifesto_locale_errors())
    plain = _manifesto_plain()
    for nid, node in EN.items():
        if not isinstance(node, dict):
            continue
        man = node.get("man") or ""
        if "V3.6.3" not in man:
            continue
        for q in _verified_quotes(man, plain):
            errs.append(f"{nid} 把不是 V3.6.3 原文的句子标成了引文：{q[:80]}")
    if errs:
        raise SystemExit("Krino Tree 数据有误：\n  " + "\n  ".join(errs))


def ancestors(nid):
    seen, stack = set(), list(REQ.get(nid, [])) + list(ANY.get(nid, []))
    while stack:
        r = stack.pop()
        if r not in seen:
            seen.add(r)
            stack += REQ.get(r, []) + ANY.get(r, [])
    return seen


def compute_status():
    """进度：status.json 里写了的照写；阶段终点和汇合门按前置算；其余按阶段默认值。"""
    st = {}
    for n in TREE["NODES"]:
        if n in STATUS["nodes"]:
            st[n] = STATUS["nodes"][n]["status"]
        elif n not in MILESTONES:
            st[n] = STATUS["defaults"][PHASE_OF[n]]

    def ms(n):
        if n in st:
            return st[n]
        if n in ANY:
            done = any(ms(r) == "completed" for r in ANY[n])
        else:
            done = all(ms(r) == "completed" for r in REQ[n])
        st[n] = "completed" if done else STATUS["defaults"][PHASE_OF[n]]
        return st[n]
    for n in MILESTONES:
        ms(n)
    return st


def nature(nid):
    if nid in MILESTONES:
        return "milestone"
    return TREE["NODES"][nid]["cls"]


def _nover(x):
    """旧稿版本号不出现在页面上。现行官网宣言是 V3.6.3，这个版本号保留。"""
    if isinstance(x, list):
        return [_nover(i) for i in x]

    def repl(m):
        s = m.group(0)
        if "V3.6.3" in s:
            return s
        return " " if s[:1] == " " and s[-1:] == " " else ""

    return re.sub(r"\s?V3(?:\.\d+)*\s?", repl, x or "")


_PUBLIC_DROP = [  # 出自投资人版宣言、官网版已删去的说法：显示时去掉
    re.compile(r"\s*<b>(?:公理四（垄断）|Axiom 4 \(Monopoly\))</b>.*?(?=<b>(?:公理|Axiom)|$)", re.S),
    re.compile(r"[；;]\s*(?:是全树最硬的护城河叙事|the hardest moat story in the whole tree)"),
]
_PUBLIC_TAGS = {"核心护城河", "Core moat"}


def _public(x):
    if isinstance(x, list):
        return [i for i in x if i not in _PUBLIC_TAGS]
    for r in _PUBLIC_DROP:
        x = r.sub("", x or "")
    return x.strip()


def text(nid, lang):
    return {k: _public(_nover(v)) for k, v in _text(nid, lang).items()}


def _text(nid, lang):
    """节点文字：中文直接用母版原文，英文用译文。"""
    if lang == "zh":
        n = TREE["NODES"][nid]
        return {"name": n["name"], "summary": strip(n["cap"]), "body": n.get("body", ""), "cap": n.get("cap", ""),
                "val": n.get("val", ""), "pass": n.get("pass", ""), "pre": n.get("pre", ""), "mode": n.get("mode", ""),
                "when": n.get("when", ""), "man": n.get("man", ""), "tags": n.get("tags", []), "clsLabel": n.get("clsLabel", ""),
                "sci": TREE["SCI"].get(nid, ""), "open": TREE["OPEN"].get(nid, ""), "unlock": TREE["UNLOCK"].get(nid, ""),
                "dur": TREE["DUR"].get(nid, ""), "tag": TREE["TAGS"].get(nid, "")}
    e = EN[nid]
    return {k: e.get(k, [] if k == "tags" else "") for k in
            ("name", "summary", "body", "cap", "val", "pass", "pre", "mode", "when", "man", "tags", "clsLabel", "sci", "open", "unlock", "dur", "tag")}


def lang_of(region_lang):
    return "zh" if region_lang.startswith("zh") else "en"


def related(key, region_cfg, L):
    """节点相关的真实产品入口（只有确实存在的才给）。"""
    app = region_cfg["products"][0]["app"] if region_cfg["products"] else None
    if key == "world" and app:
        return {"name": "KRINO WORLD", "app": app, "app_label": f'{L["enter"]} KRINO WORLD', "host": "krinomatrix.com" + app,
                "showcase": L["world_showcase"]}
    if key == "glasses-sim" and app:
        note = {"zh": "眼镜模拟器在应用内：设置 → 高级", "en": "The glasses simulator is in the app under Settings → Advanced"}
        return {"name": "KRINO GLASSES (simulator)" if L is LABELS["en"] else "KRINO GLASSES 模拟器", "app": app,
                "app_label": f'{L["enter"]} KRINO WORLD', "host": "krinomatrix.com" + app,
                "note": note["zh" if L is LABELS["zh"] else "en"]}
    return None


def tree_data(region_cfg):
    """/<地区>/vision/tree.json：页面画树和弹详情要的全部数据（按需加载，首屏不带）。"""
    lang = lang_of(region_cfg["lang"])
    L = LABELS[lang]
    st = compute_status()
    nodes = {}
    for nid in TREE["NODES"]:
        t = text(nid, lang)
        s = STATUS["nodes"].get(nid, {})
        ext = sorted(a for a in ancestors(nid) if nature(a) == "external")
        nodes[nid] = {
            "id": nid, "phase": PHASE_OF[nid], "col": COL_OF.get(nid), "status": st[nid], "nature": nature(nid),
            "requires": REQ[nid], "anyOf": ANY.get(nid, []), "externals": ext, **t,
            "done": s.get("done", {}).get(lang, []), "remaining": s.get("remaining", {}).get(lang, []),
            "evidence": s.get("evidence", ""), "related": related(s.get("related"), region_cfg, L),
        }
    return {"lang": lang, "checked": STATUS["checked"], "labels": L, "phases": ST["phases"], "nodes": nodes,
            "milestones": sorted(MILESTONES)}


# ---------- 页面 ----------
def _badge(kind, value, L):
    return f'<span class="st st-{value}">{L[kind][value]}</span>'


def tree_module(region_cfg):
    lang = lang_of(region_cfg["lang"])
    L = LABELS[lang]
    st = compute_status()
    legend = ('<div class="legend" aria-label="legend"><div><b>' + L["status_h"] + "</b>" +
              "".join(f'<span class="lg"><i class="sw sw-{s}"></i>{L["status"][s]}</span>' for s in STATUSES) +
              "</div><div><b>" + L["nature_h"] + "</b>" +
              "".join(f'<span class="lg"><i class="nt nt-{n}"></i>{L["nature"][n]}</span>' for n in NATURES) +
              "</div></div>")
    cards, lists = [], []
    for ph in ST["phases"]:
        P = L["phases"][ph["id"]]
        # 阶段卡：点了跳到整棵树里这一段（宽屏）；窄屏展开下面这一段的清单
        cards.append(f"""<a class="phase ph-{ph["id"]}" href="#phase-{ph["id"]}" data-phase="{ph["id"]}">
        <span class="pn">0{ph["n"]} · {ph["key"]}</span><span class="pt">{esc(P["sub"])}</span>
        <span class="pb">{esc(P["blurb"])}</span>
        <span class="url">{L["explore"]}</span></a>""")
        # 每个阶段的节点清单：窄屏和没有脚本时就看这个；宽屏由脚本画成一整棵树
        colhtml = []
        groups = [("", ph["root"])] if ph.get("root") else []
        groups += [(c["v3"], c["nodes"]) for c in ph["columns"]]
        if ph.get("gates"):
            groups.append((L["gates_row"] if lang == "en" else "汇合门", ph["gates"]))
        groups.append(("", [ph["end"]]))
        for title, nodes in groups:
            ctitle = (L["columns"].get(title, title) if lang == "en" else title)
            items = "".join(
                f'<li><button class="tnode s-{st[n]} n-{nature(n)}" type="button" data-node="{n}">'
                f'<span class="tb">{_badge("status", st[n], L)}<span class="nt-l">{L["nature"][nature(n)]}</span></span>'
                f'<b>{esc(text(n, lang)["name"])}</b><span class="ts">{esc(text(n, lang)["summary"])}</span></button></li>'
                for n in nodes)
            head = f"<h4>{esc(ctitle)}</h4>" if ctitle else ""
            colhtml.append(f'<div class="tcolumn">{head}<ol>{items}</ol></div>')
        lists.append(f"""<details class="tphase" id="phase-{ph["id"]}" data-phase="{ph["id"]}">
        <summary><span class="pn">0{ph["n"]} · {ph["key"]}</span> {esc(P["sub"])}</summary>
        <p class="pblurb">{esc(P["blurb"])}</p>
        <div class="tcols">{"".join(colhtml)}</div></details>""")
    # 整棵树：宽屏由 tree.js 画在页面里（跟着页面一起滚动，不是一个单独拖动的画布）
    return f"""<section class="sec vsec" id="tree" aria-labelledby="t-h">
      <p class="tag">// {L["tree_tag"]}</p>
      <h2 class="title" id="t-h">{L["tree_title"]} <span class="sub">— {esc(L["tree_sub"])}</span></h2>
      <p class="lead">{esc(L["tree_lead"])}</p>
      {f'<p class="note honesty">{esc(L["tree_honesty"])}</p>' if L["tree_honesty"] else ""}
      <div class="phases">{"".join(cards)}</div>
      {legend}
      <div class="tree-x" id="tree-x" hidden>
        <div class="tx-bar">
          <p class="tx-hint">{esc(L["canvas_hint"])}</p>
          <div class="tx-zoom"><button type="button" data-zoom="-1" aria-label="{L["zoom_out"]}" title="{L["zoom_out"]}">−</button><button type="button" data-zoom="0" aria-label="{L["fit"]}" title="{L["fit"]}">⤢</button><button type="button" data-zoom="1" aria-label="{L["zoom_in"]}" title="{L["zoom_in"]}">+</button></div>
        </div>
        <div class="tx-scroll"><div class="tx-size"><div class="tx-stage" role="group" aria-label="{L["tree_title"]}"><svg class="tx-links" aria-hidden="true"></svg></div></div></div>
      </div>
      <div class="tlists">{"".join(lists)}</div>
    </section>"""


def progress_module(region_cfg):
    lang = lang_of(region_cfg["lang"])
    L = LABELS[lang]
    st = compute_status()
    done = [n for n in st if st[n] == "completed"]
    building = [n for n in st if st[n] == "in_progress"]
    nxt = [n for n in st if PHASE_OF[n] == "embodiment" and n not in MILESTONES]
    far = [n for n in st if PHASE_OF[n] in ("neural", "ascension")]
    ext = [n for n in far if nature(n) == "external"]
    link = lambda n: f'<li><button class="tlink" type="button" data-node="{n}">{esc(text(n, lang)["name"])}</button></li>'
    live = "".join(f"<li>{esc(x)}</li>" for x in STATUS["nodes"]["seed"]["done"][lang][:3])
    live_extra = "<ul>" + "".join(link(n) for n in done) + "</ul>" if done else f'<p class="note">{L["prog_none_done"]}</p>'
    app = region_cfg["products"][0]["app"]
    return f"""<section class="sec vsec" id="progress" aria-labelledby="p-h">
      <p class="tag">// STATUS · {STATUS["checked"]}</p>
      <h2 class="title" id="p-h">{L["prog_title"]}</h2>
      {f'<p class="lead">{esc(L["prog_lead"])}</p>' if L["prog_lead"] else ""}
      <div class="pgrid4">
        <div class="pcol c-live"><h3>{L["prog_live"]}</h3><ul>{live}</ul>{live_extra}<a class="btn" href="{app}">{region_cfg["t"]["enter"]}</a></div>
        <div class="pcol c-building"><h3>{L["prog_building"]}</h3><ul>{"".join(link(n) for n in building)}</ul></div>
        <div class="pcol c-next"><h3>{L["prog_next"]}</h3><p>{L["prog_next_text"]}</p></div>
        <div class="pcol c-long"><h3>{L["prog_long"]}</h3><p>{L["prog_long_text"]}</p></div>
      </div>
    </section>"""


def vision_page(region_cfg):
    lang = lang_of(region_cfg["lang"])
    L = LABELS[lang]
    body = f"""    <nav class="vtabs" aria-label="{L["page_title"]}"><a href="#tree">{L["tab_tree"]}</a><a href="#progress">{L["tab_progress"]}</a></nav>
    {tree_module(region_cfg)}
    {progress_module(region_cfg)}
    <dialog class="ndlg" id="node-dialog" aria-labelledby="nd-title"><div class="nd-in"></div></dialog>"""
    return {"title": L["page_title"], "description": L["page_desc"]}, body


def _flow_parts(M):
    """英文页按 Word 的段落流排：空段留下，不把相邻段落并成一段。目录是页面结构，插在第一处标题之前。"""
    head, rest, n, started = [], [], 0, False
    for item in M["flow"]:
        role, text = item["role"], item.get("text", "")
        if role == "heading":
            started = True
        buf = rest if started else head
        if role == "latin":
            buf.append(f'<p class="latin">{esc(text)}</p>')
        elif role == "title":
            buf.append(f"<h1>{esc(text)}</h1>")
        elif role == "epigraph":
            buf.append(f'<blockquote class="epigraph">{esc(text)}</blockquote>')
        elif role == "blank":
            buf.append('<p class="docx-blank" aria-hidden="true"></p>')
        elif role == "heading":
            n += 1
            buf.append(f'<h2 id="s{n}"><i>{n:02d}</i>{esc(text)}</h2>')
        else:
            buf.append(f"<p>{esc(text)}</p>")
    return "".join(head), "".join(rest)


def manifesto_page(region_cfg):
    lang = lang_of(region_cfg["lang"])
    L = LABELS[lang]
    M = MANIFESTO[lang]
    toc = "".join(f'<a href="#s{i + 1}">{esc(s["title"])}</a>' for i, s in enumerate(M["sections"]))
    if M.get("flow"):
        head, rest = _flow_parts(M)
        article = f"{head}\n    <nav class=\"toc\" aria-label=\"{L['toc']}\">{toc}</nav>\n    {rest}"
    else:
        secs = "".join(f'<h2 id="s{i + 1}"><i>{i + 1:02d}</i>{esc(s["title"])}</h2>' + "".join(f"<p>{esc(p)}</p>" for p in s["paragraphs"])
                       for i, s in enumerate(M["sections"]))
        article = f"""<p class="latin">{esc(M.get("latin", ""))}</p>
    <h1>{esc(M["title"])}</h1>
    <blockquote class="epigraph">{esc(M["epigraph"])}</blockquote>
    <nav class="toc" aria-label="{L["toc"]}">{toc}</nav>
    {secs}"""
    body = f"""<p class="tag">// APOCALYPSE &amp; FULFILLMENT · MANIFESTO</p>
    <p class="meta">{esc(L["full_note"])} · <a href="{{base}}apocalypse/">{L["back"]}</a></p>
    <article lang="{M["lang"]}">
    {article}
    </article>
    <p class="meta"><a href="{{base}}vision/#tree">{L["tab_tree"]} →</a></p>"""
    desc = {"zh": '决策矩阵宣言全文：我们为什么存在、相信什么、要去哪里。',
            "en": 'The full Krino Matrix Manifesto: why we exist, what we believe and where we are going.'}[lang]
    return {"title": M["title"], "description": desc}, body


APO_TEXT = {
    "en": {"title": "Apocalypse <em>&amp;</em> Fulfillment",
           "lead": "Apokalypsis is the Greek word behind the Book of Revelation: an unveiling. In biblical literature, fulfillment is a prophecy coming true. "
                   "This is where we publish what we see coming, and report what has come true: our products, research and updates.",
           "kinds": {"apocalypse": ("APOCALYPSE", "What we foresee: manifestos, judgments and visions."),
                     "fulfillment": ("FULFILLMENT", "What has come true: products, research and updates.")},
           "first": "First entry", "empty_ful": "Fulfillments will be reported here as they come true.",
           "desc": "Apocalypse & Fulfillment: Krino Matrix's prophecies, and reports on our products and research as they come true. The Manifesto is the first entry."},
    "zh": {"title": "启示<em>与</em>应验",
           "lead": "Apocalypse 的希腊文词源 Apokalypsis，是《启示录》的书名，意思是“揭开”；在圣经文学里，Fulfillment 指预言的应验。"
                   "这里发布我们看见的未来，也逐条通报已经应验的事：我们的产品、研究和更新。",
           "kinds": {"apocalypse": ("启示 · APOCALYPSE", "我们看见并说出的事：宣言、判断与愿景。"),
                     "fulfillment": ("应验 · FULFILLMENT", "已经应验的事：产品、研究与更新。")},
           "first": "第一则", "empty_ful": "应验了的事，会在这里逐条通报。",
           "desc": "启示与应验：决策矩阵的预言，以及产品、研究应验时的更新通报。宣言是第一则。"},
}


def apocalypse_page(region_cfg):
    """/<地区>/apocalypse/：启示与应验。条目来自 data/apocalypse/entries.json。"""
    lang = lang_of(region_cfg["lang"])
    T, L = APO_TEXT[lang], LABELS[lang]
    entries = APOCALYPSE["entries"]
    rows = []
    for i, e in enumerate(entries):
        t = e[lang]
        href = e["href"] if re.match(r"https?://", e["href"]) else "{base}" + e["href"]
        node = f' · <a href="{{base}}vision/#node-{e["node"]}">{L["tab_tree"]}</a>' if e.get("node") else ""
        first = f'<span class="first">{T["first"]}</span>' if i == len(entries) - 1 else ""
        rows.append(f"""<li class="apo k-{e["kind"]}">
        <div class="apo-meta"><span class="kind">{T["kinds"][e["kind"]][0]}</span><time datetime="{e["date"]}">{e["date"]}</time>{first}</div>
        <h2><a href="{href}">{esc(t["title"])}</a></h2>
        <p>{esc(t["summary"])}</p>
        <p class="apo-go"><a class="btn" href="{href}">{esc(t["cta"])}<small>{esc(t.get("meta", ""))}</small></a>{node}</p>
      </li>""")
    has_ful = any(e["kind"] == "fulfillment" for e in entries)
    kinds = "".join(f'<div class="k-{k}"><b>{v[0]}</b><span>{esc(v[1])}</span></div>' for k, v in T["kinds"].items())
    body = f"""    <section class="sec">
      <p class="tag">// APOCALYPSE &amp; FULFILLMENT</p>
      <h1 class="title">{T["title"]}</h1>
      <p class="lead">{esc(T["lead"])}</p>
      <div class="apo-kinds">{kinds}</div>
      <ol class="apo-list">{"".join(rows)}</ol>
      {"" if has_ful else f'<p class="note">{esc(T["empty_ful"])}</p>'}
    </section>"""
    return {"title": "Apocalypse & Fulfillment" if lang == "en" else "启示与应验 Apocalypse & Fulfillment", "description": T["desc"]}, body
