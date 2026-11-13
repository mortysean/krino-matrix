// 官网 krinomatrix.com 的浏览器测试：全球入口、地区推荐与记忆、两个地区站的全部链接、旧地址、SEO 元数据、
// 宣言与 Krino Tree（阶段、画布、依赖追踪、节点状态、详情、键盘、深链接、窄屏清单、减少动效）、窄屏。截图存到 shots/site-*.png。
//   SITE_URL=https://krinomatrix.com node site.mjs                 线上（只读，不登录、不改任何东西）
//   SITE_URL=https://krinomatrix.com:9443 SITE_IP=127.0.0.1 node site.mjs   本地 Caddy（域名解析到 SITE_IP，忽略自签证书）
// 不经过 Caddy（比如后端的 /landing/）测不了服务器端跳转，所以这里只支持 Caddy。
// 页面里的请求用 page.evaluate(fetch)：page.request 不走浏览器的域名映射。
import { chromium } from "playwright-core";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";

const SITE = (process.env.SITE_URL || "https://krinomatrix.com").replace(/\/$/, "");
const CANON = "https://krinomatrix.com";
const SHOTS = new URL("./shots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });
const APPS = { cn: "/cn/products/world/", global: "/global/products/world/" };  // 应用挂在官网下

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const base = homedir() + "/.cache/ms-playwright";
  for (const d of existsSync(base) ? readdirSync(base).filter((x) => x.startsWith("chromium-")).sort().reverse() : []) {
    const p = `${base}/${d}/chrome-linux64/chrome`;
    if (existsSync(p)) return p;
  }
  throw new Error("找不到 Chromium：设置 CHROME=/path/to/chrome");
}

let failed = 0;
async function step(name, fn) {
  try { await fn(); console.log(`  ✓ ${name}`); } catch (e) { failed++; console.log(`  ✗ ${name}\n      ${e.message.split("\n").join("\n      ")}`); }
}
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };
const host = new URL(SITE).hostname;
const args = ["--no-proxy-server"];
if (process.env.SITE_IP) args.push(`--host-resolver-rules=MAP ${host} ${process.env.SITE_IP}`);
const browser = await chromium.launch({ executablePath: findChrome(), args });
const newCtx = (o = {}) => browser.newContext({ ignoreHTTPSErrors: !!process.env.SITE_IP, viewport: { width: 1440, height: 900 }, ...o });
const path = (u) => new URL(u).pathname + new URL(u).search;
const cookieOf = async (ctx) => (await ctx.cookies(SITE)).find((c) => c.name === "km_region")?.value;

// ---------- 入口、推荐、记忆、切换 ----------
const ctx = await newCtx();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`${page.url()} pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") errors.push(`${page.url()} console: ${m.text()}`); });
page.on("response", (r) => { if (r.status() >= 400 && r.url().startsWith(SITE)) errors.push(`${r.status()} ${r.url()}`); });

await step("根域名：不让人选地区，服务器直接 302 进门户首页（第一屏就是 Enter Krino）", async () => {
  const r = await page.goto(SITE + "/");
  expect(/^\/(cn|global)\/$/.test(path(page.url())), `到了 ${page.url()}`);
  expect(r.request().redirectedFrom(), "应由服务器跳转，不是页面脚本");
  expect(await page.locator(".regions, .door[data-region]").count() === 0, "不该再有选地区的大卡片");
  expect(await page.locator(".hero-home a.btn.enter").isVisible(), "首页第一屏应有 Enter Krino");
  expect(!(await cookieOf(ctx)), "没切换之前不该有 km_region");
  const hl = await page.$$eval('link[rel=alternate][hreflang]', (ls) => ls.map((l) => l.hreflang + " " + l.href));
  expect(hl.includes(`zh-CN ${CANON}/cn/`) && hl.includes(`en ${CANON}/global/`) && hl.includes(`x-default ${CANON}/global/`), "hreflang 不全：" + hl);
});
await step("页脚：产品一栏只有 KRINO WORLD，没有“全部产品”", async () => {
  for (const r of ["cn", "global"]) {
    await page.goto(`${SITE}/${r}/about/`);
    const col = await page.$$eval(".site-foot > div:nth-child(2) a", (as) => as.map((a) => a.textContent.trim()));
    expect(JSON.stringify(col) === '["KRINO WORLD"]', `${r} 产品栏：${col}`);
  }
});
await step("页脚“切换地区”：直接到另一个地区的同名页面并记住；再开根域名进记住的地区", async () => {
  await page.goto(SITE + "/cn/about/");
  await page.click(".region-line a");
  await page.waitForURL(/\/global\/about\/$/);
  expect(await cookieOf(ctx) === "global", "Cookie 应为 global");
  const c = (await ctx.cookies(SITE)).find((c) => c.name === "km_region");
  expect(c.path === "/" && c.sameSite === "Lax" && c.expires > Date.now() / 1000 + 300 * 86400, "Cookie 属性不对：" + JSON.stringify(c));
  await page.goto(SITE + "/");
  expect(path(page.url()) === "/global/", `到了 ${page.url()}`);
  await page.click(".region-line a");
  await page.waitForURL(/\/cn\/$/);
  expect(await cookieOf(ctx) === "cn", "Cookie 应为 cn");
  await page.goto(SITE + "/");
  expect(path(page.url()) === "/cn/", `到了 ${page.url()}`);
  await page.waitForTimeout(800);
  await page.screenshot({ path: SHOTS + "site-01-cn-home.png" });
});
await step("顶栏地区切换：同名页面互跳并改记忆", async () => {
  await page.goto(SITE + "/cn/about/");
  await page.click("a.region-sw");
  await page.waitForURL(/\/global\/about\/$/);
  expect(await cookieOf(ctx) === "global", "Cookie 应变为 global");
  await page.click("a.region-sw");
  await page.waitForURL(/\/cn\/about\/$/);
  expect(await cookieOf(ctx) === "cn", "Cookie 应变回 cn");
});
await step("不带地区的地址、别名和旧门户地址都能打开（跟着记住的地区走）", async () => {
  const cases = [["/privacy/", "/cn/privacy/"], ["/terms", "/cn/terms/"], ["/cookies/", "/cn/cookies/"], ["/about/", "/cn/about/"], ["/about", "/cn/about/"],
    ["/contact/", "/cn/contact/"], ["/developers/", "/cn/developers/"], ["/products/world/", "/cn/products/world/"], ["/vision/", "/cn/vision/"],
    ["/manifesto/", "/cn/manifesto/"], ["/tree/", "/cn/vision/#tree"], ["/strategy", "/cn/vision/#tree"], ["/global/tree/", "/global/vision/#tree"],
    ["/zh/", "/cn/"], ["/en", "/global/"], ["/landing/", "/cn/"], ["/static/assets/krino.png", "/static/assets/krino.png"], ["/favicon.ico", "/favicon.ico"]];
  const bad = [];
  for (const [from, to] of cases) {
    const r = await page.goto(SITE + from);
    const got = path(page.url()) + (new URL(page.url()).hash || "");
    if (got !== to || r.status() !== 200) bad.push(`${from} → ${got} (${r.status()})，应为 ${to}`);
  }
  expect(!bad.length, bad.join("\n"));
});
await step("深层链接刷新、无斜杠地址", async () => {
  await page.goto(SITE + "/global/vision/");
  const r = await page.reload();
  expect(r.status() === 200, "刷新后 " + r.status());
  await page.goto(SITE + "/global/about");
  expect(path(page.url()) === "/global/about/", "无斜杠没补上：" + page.url());
  const nf = await page.goto(SITE + "/cn/no-such-page/");
  expect(nf.status() === 404 && (await page.title()).includes("404"), "404 页不对");
  errors.splice(0, errors.length, ...errors.filter((e) => !e.includes("no-such-page")));
});

// ---------- 爬两个地区站的全部链接 ----------
const seen = new Map();  // 路径 -> {region, appLinks}
await step("两个地区站：所有站内链接 200、资源无 404、SEO 元数据齐全、应用入口都指向本地区", async () => {
  const queue = ["/cn/", "/global/"];
  const problems = [];
  while (queue.length) {
    const p = queue.shift();
    if (seen.has(p)) continue;
    const r = await page.goto(SITE + p);
    if (r.status() !== 200) { problems.push(`${p} → ${r.status()}`); seen.set(p, {}); continue; }
    const info = await page.evaluate(() => ({
      links: [...document.querySelectorAll("a[href]")].map((a) => a.href),
      canonical: document.querySelector("link[rel=canonical]")?.href,
      desc: document.querySelector("meta[name=description]")?.content,
      og: ["og:title", "og:description", "og:url", "og:image"].every((k) => document.querySelector(`meta[property="${k}"]`)?.content),
      lang: document.documentElement.lang, title: document.title,
      imgs: [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src),
    }));
    const region = p.split("/")[1];
    if (info.canonical !== CANON + p) problems.push(`${p} canonical=${info.canonical}`);
    if (!info.desc || !info.og || !info.title) problems.push(`${p} 缺 description/og/title`);
    if (info.lang !== (region === "cn" ? "zh-CN" : "en")) problems.push(`${p} lang=${info.lang}`);
    if (info.imgs.length) problems.push(`${p} 图片坏了：${info.imgs}`);
    const appLinks = info.links.filter((h) => h.startsWith(SITE + "/") && Object.values(APPS).some((a) => new URL(h).pathname.startsWith(a)));
    if (!appLinks.length) problems.push(`${p} 顶栏缺登录入口`);
    if (appLinks.some((h) => !new URL(h).pathname.startsWith(APPS[region]))) problems.push(`${p} 应用入口地区不对：${appLinks}`);
    seen.set(p, { region, appLinks });
    for (const h of info.links) {
      if (!h.startsWith(SITE + "/")) continue;
      const u = new URL(h);
      if (u.search || !/^\/(cn|global)\//.test(u.pathname) || /\/products\/world\//.test(u.pathname)) continue;  // 应用单独测
      if (!seen.has(u.pathname) && !queue.includes(u.pathname)) queue.push(u.pathname);
    }
  }
  console.log(`      爬了 ${seen.size} 个页面：${[...seen.keys()].join(" ")}`);
  expect(!problems.length, problems.join("\n"));
});
await step("sitemap.xml、robots.txt 与实际页面一致", async () => {
  const xml = await page.evaluate(() => fetch("/sitemap.xml").then((r) => r.text()));
  const locs = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].replace(CANON, ""));
  const missing = [...seen.keys()].filter((p) => !locs.includes(p));
  expect(!missing.length, "sitemap 缺：" + missing);
  const robots = await page.evaluate(() => fetch("/robots.txt").then((r) => r.text()));
  expect(robots.includes(`Sitemap: ${CANON}/sitemap.xml`), "robots.txt 没写 sitemap");
});
await step("没有脚本错误和 4xx/5xx 资源", async () => { expect(!errors.length, errors.join("\n")); });

// ---------- 产品应用：/<地区>/products/world/ ----------
await step("应用：两个地区各自打开、接口走对应地区的后端、图片资源能加载、登录凭证按地区分开存", async () => {
  for (const [r, edition] of [["cn", "cn"], ["global", "global"]]) {
    const res = await page.goto(`${SITE}/${r}/products/world/`);
    expect(res.status() === 200, `${r} 应用 ${res.status()}`);
    await page.waitForFunction(() => document.querySelector("#app, body")?.innerText.length > 20, null, { timeout: 15000 });
    const info = await page.evaluate(async (r) => {
      const site = await fetch(`/${r}/products/world/api/site`).then((x) => x.json());
      const health = (await fetch(`/${r}/products/world/api/health`)).status;
      const broken = [...document.images].filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.src);
      const css = [...document.styleSheets].length;
      return { site, health, broken, css };
    }, r);
    expect(info.site.edition === edition, `${r} 应用连到了 ${info.site.edition} 的后端`);
    expect(info.health === 200 && info.css > 0 && !info.broken.length, `${r} 应用资源：${JSON.stringify(info)}`);
    const bare = await page.goto(`${SITE}/${r}/products/world`);
    expect(path(page.url()) === `/${r}/products/world/` && bare.status() === 200, "无斜杠没补上");
  }
  await page.goto(`${SITE}/cn/products/`);
  expect(path(page.url()) === "/cn/products/world/", "产品目录应直接进应用：" + page.url());
  errors.splice(0, errors.length, ...errors.filter((e) => !/products\/world\/api\//.test(e)));  // 未登录时应用自己会请求 401 的接口
});

// ---------- 首页、启示与应验、Krino Tree ----------
for (const region of ["cn", "global"]) {
  await step(`[${region}] 首页：第一屏就有 Enter Krino（进应用），导航为 产品 / 启示与应验 / 战略 / 开发者 / 关于，右上角是登录，首屏底部没有导航`, async () => {
    await page.goto(`${SITE}/${region}/`);
    const enter = page.locator(".hero-home a.btn.enter");
    expect(await enter.isVisible(), "首屏看不到 Enter Krino");
    const box = await enter.boundingBox();
    expect(box.y + box.height <= 900, "Enter Krino 不在第一屏");
    expect((await enter.getAttribute("href")) === APPS[region], "Enter Krino 没指向本地区应用");
    const nav = await page.$$eval(".bar nav a.hide-sm", (as) => as.map((a) => a.getAttribute("href")));
    expect(nav.length === 5 && nav[0].endsWith("products/") && nav[1].endsWith("apocalypse/") && nav[2].includes("vision/#tree") && nav[3].endsWith("developers/") && nav[4].includes("about/"), "导航不对：" + nav);
    const cta = page.locator(".bar nav a.cta");
    expect((await cta.textContent()).trim() === (region === "cn" ? "登录" : "Log in") && (await cta.getAttribute("href")) === APPS[region], "右上角应是登录，指向本地区应用");
    expect(await page.locator(".hero-home nav, .hero-nav").count() === 0, "首屏底部不该再有导航");
    const names = await page.$$eval(".bar nav a.hide-sm", (as) => as.map((a) => a.textContent.trim()));
    expect(names[0] === (region === "cn" ? "产品" : "Products") && names[2] === (region === "cn" ? "战略" : "Krino Tree"), "导航名称不对：" + names);
    expect(await page.locator('a[href$="#manifesto"]').count() === 0, "不该再有指向旧宣言板块的链接");
  });
  await step(`[${region}] 开发者中心：三页共用目录，接口一节一节有参数表和示例，复制按钮、Python / cURL 切换能用`, async () => {
    await page.goto(`${SITE}/${region}/developers/`);
    expect(await page.locator(".dev-side .dev-nav a").count() > 40, "目录太短");
    expect((await page.locator(".tabs [role=tabpanel]:not([hidden]) pre").innerText()).includes(`region="${region}"`), "Python 快速开始的 region 不对");
    await page.click('.tab-h [data-tab="curl"]');
    expect((await page.locator(".tabs [role=tabpanel]:not([hidden]) pre").innerText()).startsWith(`API=${CANON}/${region}/products/world/api`), "cURL 快速开始的接口地址不对");
    await page.goto(`${SITE}/${region}/developers/api/`);
    const eps = await page.locator(".ep").count();
    expect(eps >= 30 && await page.locator(".ep table.params").count() >= eps - 8, `接口节数 ${eps}`);
    await page.goto(`${SITE}/${region}/developers/sdk/`);
    expect(await page.locator(".fn .sig").count() >= 20, "SDK 方法太少");
    const r = await page.evaluate(() => fetch(document.querySelector('a[download]').href).then((x) => x.json()).then((j) => j.openapi));
    expect(r && r.startsWith("3."), "openapi.json 下载不了");
  });
  await step(`[${region}] 启示与应验：宣言是第一则，点进去是全文 11 节、与原文一致；战略页不再有宣言板块`, async () => {
    await page.goto(`${SITE}/${region}/vision/`);
    expect(await page.locator("#manifesto").count() === 0, "战略页不该再有宣言板块");
    await page.goto(`${SITE}/${region}/apocalypse/`);
    const first = page.locator(".apo-list li.apo").last();
    expect(await first.locator(".first").count() === 1 && (await first.getAttribute("class")).includes("k-apocalypse"), "宣言应是第一则启示");
    await first.locator("a.btn").click();
    await page.waitForURL(/\/manifesto\/$/);
    expect(await page.locator("article h2").count() === 11, "全文章节数不对");
    const txt = await page.locator("article").innerText();
    expect(txt.includes("Our secret is this: superintelligence will not stay to rule us. It will leave us.") && txt.includes("we’ll certainly go"), "全文缺内容");
    expect(await page.getAttribute("article", "lang") === "en", "全文应标 lang=en");
  });
  await step(`[${region}] Krino Tree 第一层：默认只显示四个阶段，不铺开 56 个节点`, async () => {
    await page.goto(`${SITE}/${region}/vision/`);
    expect(await page.locator(".phase").count() === 4, "应有四个阶段卡");
    expect(await page.locator("#tree-x").isHidden(), "画布默认应收起");
    expect(await page.locator(".tphase[open]").count() === 0, "清单默认应收起");
    expect(await page.locator(".tnode").count() === 56, "页面里应有 56 个节点（供搜索引擎和窄屏）");
  });
  await step(`[${region}] 点阶段：展开该阶段的树；状态与数据一致：平台已完成、眼镜研发中、MVP 终点未点亮`, async () => {
    await page.click(".phase.ph-seed");
    await page.waitForSelector(".tx-stage .tn");
    const d = await page.evaluate(() => fetch("tree.json").then((r) => r.json()));
    expect(Object.keys(d.nodes).length === 56, "tree.json 节点数不对");
    const by = (s) => Object.values(d.nodes).filter((n) => n.status === s).map((n) => n.id).sort();
    expect(JSON.stringify(by("in_progress")) === '["glasses"]', "研发中应只有 glasses：" + by("in_progress"));
    expect(JSON.stringify(by("completed")) === '["seed"]', "已完成应只有 seed：" + by("completed"));
    expect(d.nodes.mvpEnd.status !== "completed", "MVP 阶段终点不该点亮");
    expect(d.nodes.glasses.status !== "completed", "眼镜不该标完成");
    for (const n of Object.values(d.nodes)) for (const r of [...n.requires, ...n.anyOf]) expect(d.nodes[r], `${n.id} 依赖不存在的 ${r}`);
    const ids = await page.$$eval(".tx-stage .tn", (ns) => ns.map((n) => n.dataset.node).sort());
    expect(JSON.stringify(ids) === '["glasses","mvpEnd","seed"]', "种子阶段节点不对：" + ids);
    expect(await page.locator('.tx-stage .tn[data-node="seed"].s-completed').count() === 1, "seed 应显示已完成");
    expect(await page.locator('.tx-stage .tn[data-node="glasses"].s-in_progress').count() === 1, "眼镜应显示研发中");
    await page.click('.tx-tabs [data-view="neural"]');
    const n3 = await page.locator(".tx-stage .tn").count();
    expect(n3 === 20, "神经连接阶段应画 19 个节点 + 上一段终点：" + n3);
    expect(await page.locator(".tx-stage .tn.s-vision").count() >= 19, "神经连接阶段应为远期探索");
    await page.click('.tx-tabs [data-view="all"]');
    expect(await page.locator(".tx-stage .tn").count() === 56, "整棵树应有 56 个节点");
  });
  await step(`[${region}] 悬停追踪依赖路径；跨枝干连线平时不显示`, async () => {
    await page.click('.tx-tabs [data-view="embodiment"]');
    const hiddenCross = await page.$$eval(".e-cross", (es) => es.every((e) => getComputedStyle(e).opacity === "0"));
    expect(hiddenCross, "跨枝干连线平时应隐藏");
    await page.hover('.tx-stage .tn[data-node="contextual"]');
    const hl = await page.$$eval(".tx-stage .tn.hl", (ns) => ns.map((n) => n.dataset.node).sort());
    for (const id of ["contextual", "silent", "neurodecode", "wearable", "extmem", "mvpEnd"].filter((x) => x !== "mvpEnd"))
      expect(hl.includes(id), `悬停 contextual 应点亮 ${id}，实际 ${hl}`);
    expect(!hl.includes("memstruct"), "不相关节点不该点亮");
    expect(await page.locator(".e.hl").count() >= 4, "依赖连线应点亮");
    await page.mouse.move(5, 5);
  });
  await step(`[${region}] 键盘：Tab 到节点会追踪，回车打开详情，Esc 关闭并回到原处`, async () => {
    await page.locator('.tx-stage .tn[data-node="wearable"]').focus();
    expect(await page.locator(".tree-x.tracing").count() === 1, "聚焦应触发追踪");
    await page.keyboard.press("Enter");
    await page.waitForSelector("#node-dialog[open]");
    expect((await page.locator("#nd-title").innerText()).length > 2, "详情没标题");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.getElementById("node-dialog").open);
    expect(await page.evaluate(() => document.activeElement?.dataset?.node) === "wearable", "关闭后焦点应回到节点");
  });
  await step(`[${region}] 详情：当前节点有真实功能、还差什么和产品入口；远期节点标明是假设、依赖外部突破`, async () => {
    await page.goto(`${SITE}/${region}/about/`);  // 先离开，确保下面是一次完整的页面加载（深链接）
    await page.goto(`${SITE}/${region}/vision/#node-seed`);
    await page.waitForSelector("#node-dialog[open] .nd-prog");
    expect(await page.locator(".nd-prog ul.ok li").count() >= 3, "seed 应列出已有功能");
    expect(await page.locator(".nd-prog ul.todo li").count() >= 1, "seed 应列出后续加强");
    expect(await page.locator(".nd-meta .st-completed").count() === 1, "seed 详情应显示已完成");
    const app = await page.getAttribute(".nd-rel a.btn", "href");
    expect(app.startsWith(APPS[region]), "seed 的产品入口不对：" + app);
    for (const sel of [".nd-body h3", ".nd-tech summary"]) expect(await page.locator(sel).count() > 0, "缺 " + sel);
    await page.click(".nd-tech summary");
    expect(await page.locator(".nd-tech dd").count() >= 5, "技术细节不全");
    await page.goto(`${SITE}/${region}/vision/#node-merge`);
    await page.waitForSelector("#node-dialog[open]");
    expect(await page.locator(".callout.c-ext").count() === 1, "远期节点应有“依赖外部突破”的提示");
    await page.click('.deps .dep[data-node="translate"]');
    await page.waitForFunction(() => location.hash === "#node-translate");
    await page.screenshot({ path: SHOTS + `site-${region}-node.png` });
    await page.keyboard.press("Escape");
  });
  await step(`[${region}] 当前进度：已上线列出平台，研发中列出眼镜`, async () => {
    const t = await page.locator("#progress").innerText();
    expect(await page.locator("#progress .c-building .tlink").count() === 1, "研发中应列 1 个节点（眼镜）");
    expect(await page.locator("#progress .c-live .tlink").count() === 1, "已上线应列 1 个节点（平台）");
    expect(t.length > 100, "进度区是空的");
  });
}
await step("减少动效：研发中的节点不闪", async () => {
  const c = await newCtx({ reducedMotion: "reduce" });
  const p = await c.newPage();
  await p.goto(SITE + "/global/vision/#phase-seed");
  await p.waitForSelector(".tx-stage .tn.s-in_progress");
  const anim = await p.$eval(".tx-stage .tn.s-in_progress", (n) => getComputedStyle(n).animationName);
  expect(anim === "none", "减少动效时仍在动画：" + anim);
  await c.close();
});
await step("窄屏：不画画布，用阶段清单；点节点出详情", async () => {
  const m = await newCtx({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const mp = await m.newPage();
  await mp.goto(SITE + "/cn/vision/");
  await mp.click(".phase.ph-embodiment");
  expect(await mp.locator("#tree-x").isHidden(), "窄屏不该显示画布");
  await mp.waitForSelector("#phase-embodiment[open]");
  await mp.click('#phase-embodiment .tnode[data-node="extmem"]');
  await mp.waitForSelector("#node-dialog[open]");
  const w = await mp.$eval("#node-dialog", (d) => d.getBoundingClientRect().width);
  expect(w <= 390, "详情超出屏幕：" + w);
  await mp.screenshot({ path: SHOTS + "site-m-node.png" });
  await m.close();
});

// ---------- 窄屏 ----------
await step("窄屏（390×844）：每页都没有横向滚动，顶栏放得下", async () => {
  const m = await newCtx({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const mp = await m.newPage();
  const bad = [];
  for (const p of seen.keys()) {
    await mp.goto(SITE + p);
    await mp.waitForTimeout(150);
    const o = await mp.evaluate(() => {
      const w = document.documentElement.clientWidth;
      const over = [...document.querySelectorAll("body *")].filter((e) => { const r = e.getBoundingClientRect(); return r.width && r.right > w + 1 && getComputedStyle(e).position !== "fixed" && !e.closest(".floor, .fx, .table-wrap"); }).map((e) => e.className || e.tagName).slice(0, 3);
      const bar = document.querySelector(".bar");
      return { sw: document.documentElement.scrollWidth, w, over, barH: bar ? bar.getBoundingClientRect().height : 0 };
    });
    if (o.sw > o.w || o.over.length) bad.push(`${p} 宽 ${o.sw}>${o.w} ${o.over}`);
    if (o.barH > 70) bad.push(`${p} 顶栏折行了（高 ${o.barH}）`);
  }
  for (const [p, n] of [["/global/", "global-home"], ["/cn/", "cn-home"], ["/cn/vision/", "cn-vision"], ["/global/vision/", "global-vision"], ["/global/about/", "global-about"]]) {
    await mp.goto(SITE + p); await mp.waitForTimeout(900);
    await mp.screenshot({ path: SHOTS + `site-m-${n}.png`, fullPage: n.includes("vision") });
  }
  await m.close();
  expect(!bad.length, bad.join("\n"));
});
for (const [p, n] of [["/cn/", "03-cn-home"], ["/global/vision/", "04-global-vision"], ["/global/manifesto/", "05-global-manifesto"], ["/cn/about/", "06-cn-about"]]) {
  await page.goto(SITE + p); await page.waitForTimeout(600);
  await page.screenshot({ path: SHOTS + `site-${n}.png`, fullPage: true });
}
await browser.close();
console.log(failed ? `\n${failed} 项失败` : "\n全部通过");
process.exit(failed ? 1 : 0);
