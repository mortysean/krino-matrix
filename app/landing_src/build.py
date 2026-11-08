"""生成三个法律页面（privacy/ terms/ cookies/ 下的 index.html）。正文在同目录的 *.html 片段里，外壳在这里，改了重跑一遍：
    python app/landing_src/build.py
联系邮箱只写在 CONTACT 一处。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "landing"
CONTACT = "support@krinomatrix.com"
UPDATED = "2026-11-09"
PAGES = {
    "privacy": ("隐私政策", "Privacy Policy"),
    "terms": ("服务条款", "Terms of Service"),
    "cookies": ("Cookie 政策", "Cookie Policy"),
}

SHELL = """<!doctype html>
<!-- 由 app/landing_src/build.py 生成，别直接改这个文件：改 app/landing_src/{key}.html 再重跑 -->
<html lang="zh-CN" data-lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{zh} · KRINO MATRIX</title>
  <meta name="title-zh" content="{zh} · 决策矩阵 KRINO MATRIX">
  <meta name="title-en" content="{en} · KRINO MATRIX">
  <meta name="theme-color" content="#06060b">
  <link rel="icon" href="/static/assets/krino-mark.svg" type="image/svg+xml">
  <link rel="stylesheet" href="../portal.css">
</head>
<body>
  <div class="fx fx-glow"></div><div class="fx fx-grid"></div><div class="fx fx-scan"></div>
  <header class="bar">
    <a class="brand" href="../"><img src="/static/assets/krino-mark.svg" alt=""><div><b>KRINO MATRIX</b><span lang="zh">决策矩阵</span><span lang="en">HANGZHOU</span></div></a>
    <nav>
      <a class="hide-sm" href="../privacy/"><span lang="zh">隐私</span><span lang="en">PRIVACY</span></a>
      <a class="hide-sm" href="../terms/"><span lang="zh">条款</span><span lang="en">TERMS</span></a>
      <a class="hide-sm" href="../cookies/">COOKIE</a>
      <button class="lang" type="button" aria-label="中文 / English"></button>
      <a class="cta" href="../#enter"><span lang="zh">进入产品</span><span lang="en">LAUNCH</span></a>
    </nav>
  </header>
  <main class="doc">
    <p class="tag">// LEGAL · {up}</p>
{body}
  </main>
  <footer class="doc-foot">
    <span>© 2026 <span lang="zh">杭州决策矩阵科技有限公司</span><span lang="en">Hangzhou Krino Matrix Tech Co., Ltd.</span></span>
    <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">浙ICP备2026093639号</a>
    <a href="../privacy/"><span lang="zh">隐私政策</span><span lang="en">Privacy</span></a>
    <a href="../terms/"><span lang="zh">服务条款</span><span lang="en">Terms</span></a>
    <a href="../cookies/"><span lang="zh">Cookie 政策</span><span lang="en">Cookies</span></a>
    <a href="mailto:{contact}">{contact}</a>
  </footer>
  <script src="../portal.js"></script>
</body>
</html>
"""

for key, (zh, en) in PAGES.items():
    body = (HERE / f"{key}.html").read_text(encoding="utf-8")
    body = body.replace("{contact}", CONTACT).replace("{updated}", UPDATED)
    html = SHELL.format(key=key, zh=zh, en=en, up=key.upper(), body=body, contact=CONTACT)
    (OUT / key).mkdir(exist_ok=True)
    (OUT / key / "index.html").write_text(html, encoding="utf-8")
    print("wrote", key)
