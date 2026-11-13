"""生成官网 krinomatrix.com（输出到 app/landing/，提交进仓库，部署时原样拷到服务器）。改了内容或配置重跑一遍：
    python app/landing_src/build.py

结构：
  /                全球入口：选地区（记在 Cookie km_region 里，下次直接进）
  /cn/ …           中国大陆站，正文在 content/cn/
  /global/ …       国际站，正文在 content/global/
  /privacy/ 等      旧地址，按记住的地区跳到 /cn/ 或 /global/ 下的同名页面
  /<地区>/products/  产品介绍：软件（KRINO WORLD）、硬件（眼镜，以后更多）、开放平台；应用本身在 /<地区>/products/world/（后端提供）
  /<地区>/apocalypse/ 启示与应验：预言与产品、研究的更新通报，宣言是第一条；/<地区>/manifesto/ 宣言全文
                   （地区可以在 regions.py 的 hidden 里暂时下线某些栏目：国内站现在没有启示与应验和宣言）
  /<地区>/developers/ 开发者中心：概览和快速开始、api/（API 参考）、sdk/（Python SDK），由 devdocs.py 生成
  /<地区>/vision/    Krino Tree + 当前进度（宣言在“启示与应验”栏目下，是它的第一则）（这三个由 vision.py 按 data/ 下的数据生成）
地区、产品、外壳文字在 regions.py；样式和脚本 app/landing/portal.css、portal.js 是手写的，这里不碰。

正文片段开头用注释写标题和描述：
  <!-- title: 隐私政策
  description: …… -->
片段里可以用的占位符：{base}（本地区根目录的相对路径）、{root}（站点根目录）、{contact}、{updated}、{company}、
{app:<产品>}（该地区这个产品的应用地址）、{product_doors}、{catalog}、{footer}。
链接一律用相对路径，所以本地从后端的 /landing/ 预览也能点通；canonical、hreflang、站点地图用绝对地址。
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from regions import CONTACT, PRODUCTS, REGIONS, SITE, UPDATED  # noqa: E402
import vision  # noqa: E402  宣言与 Krino Tree（数据在 data/）
import devdocs  # noqa: E402  开发者中心（接口参数读 docs/api/openapi.json，SDK 签名读 sdk/python）

OUT = HERE.parent / "landing"
CONTENT = HERE / "content"
ASSETS = {"krino-mark.svg": HERE.parent / "frontend/assets/krino-mark.svg",
          "krino.png": HERE.parent / "frontend/assets/krino.png"}
GENERATED = ["cn", "global", "privacy", "terms", "cookies", "assets", "index.html", "404.html", "sitemap.xml", "robots.txt", "favicon.ico"]
LEGAL = ("privacy", "terms", "cookies")
# 顶栏：产品（介绍页）、启示与应验、战略（Krino Tree）、开发者、关于；最右边是登录（进应用，没登录时应用先显示登录页）；联系在页脚
NAV = (("products", "products/", "products/"), ("apocalypse", "apocalypse/", "apocalypse/"), ("tree", "vision/#tree", "vision/"),
       ("developers", "developers/", "developers/"), ("about", "about/", "about/"))
esc = html.escape
PORTRAIT = "krino.png"  # 页面上显示的立绘文件，main() 里按能否压缩决定


# ---------- 读片段 ----------
def read_fragment(path: Path):
    text = path.read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"\s*<!--(.*?)-->\s*", text, re.S)
    if m:
        for line in m.group(1).strip().splitlines():
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text


def region_pages(region: str):
    """这个地区有哪些页面：{相对路径: (片段文件, 类型)}。片段存在页面才存在；产品页还要在地区的产品列表里。"""
    d = CONTENT / region
    pages = {}
    for key, rel, kind in [("home", "", "home"), ("products", "products/", "page"),
                           ("about", "about/", "page"), ("contact", "contact/", "page"),
                           ("privacy", "privacy/", "doc"), ("terms", "terms/", "doc"), ("cookies", "cookies/", "doc")]:
        if (d / f"{key}.html").exists():
            pages[rel] = (d / f"{key}.html", kind)
    for rel in devdocs.PAGES:              # 由 devdocs.py 生成
        pages[rel] = (None, "devdoc")
    pages["vision/"] = (None, "page")      # 由 vision.py 按数据生成
    pages["apocalypse/"] = (None, "page")
    pages["manifesto/"] = (None, "doc")
    for rel in REGIONS[region].get("hidden", ()):  # 这个地区暂时下线的栏目
        pages.pop(rel, None)
    return pages


def up(rel: str) -> str:
    """从 rel 这一层回到它的根目录要几个 ../"""
    return "../" * rel.count("/")


# ---------- 外壳 ----------
def head(*, lang, title, desc, url, alternates, image, locale, site_name, root, extra=""):
    alt = "".join(f'\n  <link rel="alternate" hreflang="{h}" href="{u}">' for h, u in alternates)
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <link rel="canonical" href="{url}">{alt}
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="{esc(site_name)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{SITE}/{image}">
  <meta property="og:locale" content="{locale}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="theme-color" content="#06060b">
  <link rel="icon" href="{root}assets/krino-mark.svg" type="image/svg+xml">
  <link rel="stylesheet" href="{root}portal.css">{extra}
</head>"""


FX = '<div class="fx fx-glow"></div><div class="fx fx-grid"></div><div class="fx fx-scan"></div>'


def brand(href, sub):
    s = f"<span>{esc(sub)}</span>" if sub else ""
    return f'<a class="brand" href="{href}"><img src="{{root}}assets/krino-mark.svg" alt=""><div><b>KRINO MATRIX</b>{s}</div></a>'


def other_region(region):
    return "global" if region == "cn" else "cn"


def region_switch(region, rel, pages_by_region):
    """切到另一个地区：有同名页面就去同名页面，没有就去那边的首页。点了会记住新地区。"""
    o = other_region(region)
    target = rel if rel in pages_by_region[o] else ""
    full, short = ("International", "EN") if o == "global" else ("中国大陆", "中文")
    return (f'<a class="region-sw" href="{{root}}{o}/{target}" data-region="{o}" hreflang="{REGIONS[o]["lang"]}" lang="{REGIONS[o]["lang"]}">'
            f'<span class="hide-sm">{full} · </span>{short}</a>')


def header(region, rel, pages):
    R, t = REGIONS[region], REGIONS[region]["t"]
    links = []
    for key, href, page in NAV:
        if page in pages[region]:
            here = rel == page or rel == "manifesto/" and key == "apocalypse" or key == "developers" and rel.startswith(page)
            cur = ' aria-current="page"' if here and key != "tree" else ""
            links.append(f'<a class="hide-sm" href="{{base}}{href}"{cur}>{t[key]}</a>')
    cta = f'<a class="cta" href="{{enter}}">{t["login"]}</a>' if R["products"] else ""
    return (f'<header class="bar">\n    {brand("{base}", R["brand_sub"])}\n    <nav>\n      ' + "\n      ".join(links)
            + f"\n      {region_switch(region, rel, pages)}\n      {cta}\n    </nav>\n  </header>")


def footer(region, pages, rel=""):
    R, t = REGIONS[region], REGIONS[region]["t"]
    have = pages[region]
    icp = f'<br><a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">{R["icp"]}</a>' if R["icp"] else ""
    prods = "".join(f'<a href="{p["app"]}">{esc(PRODUCTS[p["slug"]]["name"])}</a>' for p in R["products"])
    comp = "".join(f'<a href="{{base}}{href}">{t[k]}</a>' for k, href, page in
                   (("apocalypse", "apocalypse/", "apocalypse/"), ("tree", "vision/#tree", "vision/"), ("about", "about/", "about/"),
                    ("developers", "developers/", "developers/"), ("contact", "contact/", "contact/")) if page in have)
    legal = "".join(f'<a href="{{base}}{k}/">{t[k]}</a>' for k in LEGAL if f"{k}/" in have)
    return f"""<footer class="foot site-foot">
        <div><h4>KRINO MATRIX</h4><p class="legal">© 2026 {esc(R["company"])}{icp}<br><a href="mailto:{R["contact"]}">{R["contact"]}</a></p></div>
        <div><h4>{t["products"]}</h4>{prods}</div>
        <div><h4>{t["company_h"]}</h4>{comp}</div>
        <div><h4>{t["legal"]}</h4>{legal}</div>
        <p class="region-line">{t["region"]}: <b>{R["label"]}</b> · {region_switch(region, rel, pages).replace('class="region-sw"', 'class="region-to"')}</p>
      </footer>"""


def product_doors(region):
    R, t = REGIONS[region], REGIONS[region]["t"]
    doors = [f'<a class="door" href="{{base}}products/{p["slug"]}/"><span class="k">{esc(p["status"])}</span>'
             f'<h3>{esc(PRODUCTS[p["slug"]]["name"])}</h3><p>{esc(p["tagline"])}</p><span class="url">{t["learn"]}</span></a>'
             for p in R["products"]]
    doors.append(f'<a class="door alt" href="{{base}}products/"><span class="k">CATALOG</span>'
                 f'<h3>{t["all_products"]}</h3><span class="url">{t["learn"]}</span></a>')
    return '<div class="doors in">' + "".join(doors) + "</div>"


def catalog(region):
    R, t = REGIONS[region], REGIONS[region]["t"]
    cards = []
    for p in R["products"]:
        P = PRODUCTS[p["slug"]]
        cards.append(f"""<a class="pcard" href="{{base}}products/{p["slug"]}/">
      <div class="pimg"><img src="{{root}}{P["image"]}" alt="{esc(P["name"])}" loading="lazy"></div>
      <div class="pbody"><span class="k">{esc(p["status"])}</span><h3>{esc(P["name"])}</h3><p>{esc(p["tagline"])}</p><span class="url">{t["learn"]}</span></div>
    </a>""")
    return '<div class="pgrid">' + "\n    ".join(cards) + "</div>"


def cookie_banner(region):
    t = REGIONS[region]["t"]
    return (f'<div class="cookie" hidden role="region" aria-label="Cookie">\n    <p>{t["cookie_note"]}</p>\n'
            f'    <button type="button">{t["got_it"]}</button>\n  </div>')


def fill(text, region, rel, pages):
    R = REGIONS[region]
    rel_full = f"{region}/{rel}"
    apps = {p["slug"]: p["app"] for p in R["products"]}
    if "{product_doors}" in text:
        text = text.replace("{product_doors}", product_doors(region))
    if "{catalog}" in text:
        text = text.replace("{catalog}", catalog(region))
    if "{footer}" in text:
        text = text.replace("{footer}", footer(region, pages, rel))
    text = re.sub(r"\{app:(\w+)\}", lambda m: apps[m.group(1)], text)
    text = text.replace("{enter}", R["products"][0]["app"] if R["products"] else "")
    for k, v in {"{contact}": R["contact"], "{updated}": R.get("updated", UPDATED), "{company}": R["company"], "{site}": SITE}.items():
        text = text.replace(k, v)
    return text.replace("{base}", up(rel)).replace("{root}", up(rel_full))


def alternates_for(rel, pages):
    """两个地区都有这页时互相标注 hreflang，x-default 指向全球入口。"""
    if all(rel in pages[r] for r in REGIONS):
        return [(REGIONS[r]["lang"], f"{SITE}/{r}/{rel}") for r in REGIONS] + [("x-default", f"{SITE}/global/{rel}")]
    return []


def build_region(region, pages):
    R = REGIONS[region]
    for rel, (src, kind) in pages[region].items():
        if rel == "vision/":
            meta, body = vision.vision_page(R)
        elif rel == "manifesto/":
            meta, body = vision.manifesto_page(R)
        elif rel == "apocalypse/":
            meta, body = vision.apocalypse_page(R)
        elif rel in devdocs.PAGES:
            meta, body = devdocs.PAGES[rel](region, R)
        else:
            meta, body = read_fragment(src)
        title = meta.get("title", R["site_name"])
        if rel:
            title = f"{title} · {R['site_name']}"
        url = f"{SITE}/{region}/{rel}"
        slug = rel.split("/")[1] if rel.startswith("products/") and rel.count("/") == 2 else None
        image = PRODUCTS[slug]["image"] if slug else "assets/krino.png"
        h = head(lang=R["lang"], title=title, desc=meta.get("description", R["description"]), url=url,
                 alternates=alternates_for(rel, pages), image=image, locale=R["og_locale"], site_name=R["site_name"],
                 root="{root}")
        if kind == "deck":
            main = f'<nav class="pager" aria-label="pages"></nav>\n  <div class="count"></div>\n  <main class="deck">\n{body}\n  </main>'
        else:
            main = f'<main class="{kind}">\n{body}\n  </main>\n  <div class="foot-wrap">\n      {{footer}}\n  </div>'
        data_lang = "zh" if R["lang"].startswith("zh") else "en"
        tree_js = '\n  <script src="{root}tree.js" defer></script>' if rel == "vision/" else ""
        page = f"""<!doctype html>
<!-- 由 app/landing_src/build.py 生成，别直接改：改 {src.relative_to(HERE) if src else ("devdocs.py" if kind == "devdoc" else "data/ 下的数据")} 或 regions.py 再重跑 -->
<html lang="{R["lang"]}" data-lang="{data_lang}" data-region="{region}">
{h}
<body>
  {FX}
  {header(region, rel, pages)}
  {main}
  {cookie_banner(region)}
  <script src="{{root}}portal.js"></script>{tree_js}
</body>
</html>
"""
        out = OUT / region / rel / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fill(page, region, rel, pages).replace('assets/krino.png" alt=', f'assets/{PORTRAIT}" alt='), encoding="utf-8")
        if rel == "vision/":  # 节点详情：页面需要时再加载，不拖慢首屏
            data = json.dumps(vision.tree_data(R), ensure_ascii=False, separators=(",", ":"))
            (out.parent / "tree.json").write_text(fill(data, region, rel, pages), encoding="utf-8")


# ---------- 全球入口、旧地址、404 ----------
def build_entry(pages):
    """根目录 / ：不让人选地区，直接进门户首页。服务器上 Caddy 已经 302 了（记住的地区，没记住就按到了哪台服务器）；
    这一页只在没经过 Caddy 时用（本地预览、别的托管）：按 Cookie，再按时区跳。"""
    page = """<!doctype html>
<!-- 由 app/landing_src/build.py 生成：根目录兜底，直接跳到地区首页 -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KRINO MATRIX · 决策矩阵</title>
  <link rel="canonical" href="{site}/global/">
  <link rel="alternate" hreflang="zh-CN" href="{site}/cn/">
  <link rel="alternate" hreflang="en" href="{site}/global/">
  <link rel="alternate" hreflang="x-default" href="{site}/global/">
  <link rel="stylesheet" href="portal.css">
  <script>(function(){var m=null;try{m=document.cookie.match(/(?:^|;\\s*)km_region=(cn|global)(?:;|$)/);}catch(e){}
var r=m?m[1]:(/^Asia\\/(Shanghai|Urumqi|Chongqing|Harbin)$/.test((Intl.DateTimeFormat().resolvedOptions().timeZone)||"")?"cn":"global");
location.replace(r+"/"+location.hash);})();</script>
</head>
<body>
  <main class="doc"><p><a href="cn/" lang="zh-CN">决策矩阵 · 中国大陆</a></p><p><a href="global/">KRINO MATRIX · International</a></p></main>
</body>
</html>
""".replace("{site}", SITE)
    (OUT / "index.html").write_text(page, encoding="utf-8")


def build_legacy():
    """旧地址 /privacy/ 等：服务器上 Caddy 已经按 Cookie 直接 302 了；这里是没经过 Caddy 时的兜底页（本地预览、别的托管）。"""
    for key in LEGAL:
        cn, gl = REGIONS["cn"]["t"][key], REGIONS["global"]["t"][key]
        page = f"""<!doctype html>
<!-- 由 app/landing_src/build.py 生成：旧地址，跳到地区站的同名页面 -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>{gl} · KRINO MATRIX</title>
  <link rel="stylesheet" href="../portal.css">
  <script>(function(){{var m=null;try{{m=document.cookie.match(/(?:^|;\\s*)km_region=(cn|global)(?:;|$)/);}}catch(e){{}}
var r=m?m[1]:(/^Asia\\/(Shanghai|Urumqi|Chongqing|Harbin)$/.test((Intl.DateTimeFormat().resolvedOptions().timeZone)||"")?"cn":"global");
location.replace("../"+r+"/{key}/"+location.hash);}})();</script>
</head>
<body>
  <main class="doc"><p><a lang="zh-CN" href="../cn/{key}/">{cn}（中国大陆）</a></p><p><a href="../global/{key}/">{gl} (International)</a></p></main>
</body>
</html>
"""
        (OUT / key).mkdir(exist_ok=True)
        (OUT / key / "index.html").write_text(page, encoding="utf-8")
    (OUT / "404.html").write_text("""<!doctype html>
<!-- 由 app/landing_src/build.py 生成：Caddy 找不到页面时用。只在服务器上用，所以用绝对路径 -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>404 · KRINO MATRIX</title>
  <link rel="icon" href="/assets/krino-mark.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/portal.css">
</head>
<body>
  <div class="fx fx-glow"></div><div class="fx fx-grid"></div><div class="fx fx-scan"></div>
  <main class="doc"><p class="tag">// 404</p><h1>页面不存在 · Page not found</h1>
    <p><a href="/cn/">中国大陆站</a> · <a href="/global/">International</a> · <a href="/">KRINO MATRIX</a></p></main>
</body>
</html>
""", encoding="utf-8")


def build_hidden():
    """下线栏目的旧地址：跳回本地区首页（不给 404，收藏过、分享过的链接也能进来）；不进站点地图，也不让搜索引擎收录。"""
    for region, R in REGIONS.items():
        for rel in R.get("hidden", ()):
            out = OUT / region / rel / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            back = up(f"{region}/{rel}") + f"{region}/"
            out.write_text(f"""<!doctype html>
<!-- 由 app/landing_src/build.py 生成：这个栏目在本地区暂时下线，跳回首页 -->
<html lang="{R["lang"]}">
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex">
  <meta http-equiv="refresh" content="0; url={back}">
  <link rel="canonical" href="{SITE}/{region}/">
  <title>{esc(R["site_name"])}</title>
  <script>location.replace("{back}");</script>
</head>
<body><p><a href="{back}">{esc(R["site_name"])}</a></p></body>
</html>
""", encoding="utf-8")


def build_sitemap(pages):
    rows = []
    for r in REGIONS:
        for rel in pages[r]:
            alts = "".join(f'<xhtml:link rel="alternate" hreflang="{h}" href="{u}"/>' for h, u in alternates_for(rel, pages))
            rows.append(f"  <url><loc>{SITE}/{r}/{rel}</loc>{alts}</url>")
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n", encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n", encoding="utf-8")


def main():
    for name in GENERATED:
        p = OUT / name
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    (OUT / "assets").mkdir()
    for name, src in ASSETS.items():
        shutil.copy2(src, OUT / "assets" / name)
    # 页面里显示的立绘用压缩过的 WebP（1 MB → 约 90 KB）；分享卡片（og:image）仍用 PNG，兼容更多平台
    global PORTRAIT
    try:
        from PIL import Image
        im = Image.open(ASSETS["krino.png"]); im.thumbnail((900, 1200))
        im.save(OUT / "assets" / "krino.webp", "WEBP", quality=82, method=6)
        PORTRAIT = "krino.webp"
    except ImportError:  # 没装 Pillow 就照旧用 PNG（页面能用，只是大一些）
        print("提示：没装 Pillow，立绘用原始 PNG（约 1 MB）。用 envs/krino_matrix 的 python 运行可压成 WebP。")
        PORTRAIT = "krino.png"
    shutil.copy2(HERE / "favicon.ico", OUT / "favicon.ico")  # 浏览器和收藏夹默认会要 /favicon.ico
    vision.validate()
    devdocs.validate()
    shutil.copy2(devdocs.OPENAPI, OUT / devdocs.OPENAPI_PUBLISHED)  # 开发者中心的下载链接
    pages = {r: region_pages(r) for r in REGIONS}
    for r in REGIONS:
        build_region(r, pages)
    build_entry(pages)
    build_legacy()
    build_hidden()
    build_sitemap(pages)
    n = sum(len(p) for p in pages.values())
    print(f"wrote {n} region pages ({', '.join(f'{r}: {len(p)}' for r, p in pages.items())}), entry, legacy redirects, sitemap")


if __name__ == "__main__":
    main()
