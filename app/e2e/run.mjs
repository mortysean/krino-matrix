// KRINO WORLD 浏览器端到端测试。对着一个已经启动的服务（建议 LLM_PROVIDER=mock）跑一遍主要流程，截图存到 shots/。
//   WORLD_URL=http://127.0.0.1:8630 node run.mjs
// 浏览器：CHROME=/path/to/chrome（默认 Playwright 缓存里的 Chromium）。没有 GPU 时用 SwiftShader 软件渲染 WebGL。
import { chromium } from "playwright-core";
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";

const URL_ = process.env.WORLD_URL || "http://127.0.0.1:8630";
const SHOTS = new URL("./shots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

function findChrome() {
  if (process.env.CHROME) return process.env.CHROME;
  const base = homedir() + "/.cache/ms-playwright";
  for (const d of existsSync(base) ? readdirSync(base).filter((x) => x.startsWith("chromium-")).sort().reverse() : []) {
    const p = `${base}/${d}/chrome-linux64/chrome`;
    if (existsSync(p)) return p;
  }
  throw new Error("找不到 Chromium：设置 CHROME=/path/to/chrome");
}

const results = [];
const errors = [];
async function step(name, fn) {
  const t0 = Date.now();
  try { await fn(); results.push({ name, ok: true, ms: Date.now() - t0 }); console.log(`  ✓ ${name} (${Date.now() - t0}ms)`); }
  catch (e) { results.push({ name, ok: false, error: e.message }); console.log(`  ✗ ${name}\n      ${e.message.split("\n")[0]}`); }
}
const expect = (cond, msg) => { if (!cond) throw new Error(msg); };

const browser = await chromium.launch({
  executablePath: findChrome(),
  args: ["--no-proxy-server", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
    "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
});
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["camera", "microphone"] });
const page = await ctx.newPage();
page.on("dialog", (d) => { console.log("      [对话框] " + d.message()); d.dismiss(); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error" && !/favicon|ERR_ABORTED|ERR_INTERNET_DISCONNECTED/.test(m.text())) errors.push("console: " + m.text()); });
// 截图前等所有一次性的 CSS 动画（页面切换、卡片入场）播完；颗粒、呼吸这类无限循环的不等
const shot = async (name) => {
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity),
    null, { timeout: 5000 }).catch(() => {});
  await page.screenshot({ path: SHOTS + name + ".png" });
};
const user = "e2e" + Date.now().toString(36);

console.log(`KRINO WORLD e2e → ${URL_}`);

await step("注册并进入：KRINO 第一位、默认打开，大肥鱼第二位", async () => {
  await page.goto(URL_);
  await page.waitForSelector("#auth:not(.hidden)", { timeout: 15000 });
  await shot("01-auth");
  await page.fill("[name=username]", user);
  await page.fill("[name=password]", "secret123");
  await page.click("[data-action=register]");
  await page.waitForSelector("#app:not(.hidden)", { timeout: 15000 });
  await page.waitForFunction(() => document.querySelector("#chat-name")?.textContent === "KRINO", null, { timeout: 10000 })
    .catch(async () => { throw new Error("默认角色名不对：" + await page.textContent("#chat-name")); });
  const names = await page.$$eval(".char-list .char-item .name", (xs) => xs.map((x) => x.textContent.trim()));
  expect(names[0] === "KRINO" && names[1] === "大肥鱼", "角色顺序不对：" + names.join(","));
  expect(await page.locator(".nav button").count() === 4, "导航应该只有 4 项");
});

await step("不串台：网慢时连点切换再说话，话只进最后选中的角色", async () => {
  const cdp = await ctx.newCDPSession(page);
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 900, downloadThroughput: -1, uploadThroughput: -1 });
  await page.click(".char-list .char-item:has(.name:text-is(\"大肥鱼\"))");
  await page.click(".char-list .char-item:has(.name:text-is(\"KRINO\"))");  // 马上又切回 KRINO
  await page.fill("#chat-input", "串台测试一二三");
  await page.press("#chat-input", "Enter");
  await page.waitForFunction(() => document.querySelector("#chat-name")?.textContent === "KRINO"
    && [...document.querySelectorAll(".msg.user")].some((m) => m.textContent.includes("串台测试一二三"))
    && document.querySelectorAll(".msg.assistant").length >= 1 && !document.querySelector(".typing"), null, { timeout: 30000 })
    .catch(async () => { throw new Error("话没出现在 KRINO 的对话里：" + await page.textContent("#messages")); });
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  // 大肥鱼的对话里不能有这句（后面的步骤从她干净的对话开始）
  await page.click(".char-list .char-item:has(.name:text-is(\"大肥鱼\"))");
  await page.waitForFunction(() => document.querySelector("#chat-name")?.textContent === "大肥鱼", null, { timeout: 10000 });
  await page.waitForTimeout(1500);
  expect(!(await page.textContent("#messages")).includes("串台测试一二三"), "大肥鱼的对话里出现了发给 KRINO 的话");
});

await step("Q 版小人：默认是大肥鱼，在动，聊天能触发动作", async () => {
  await page.waitForFunction(() => { const v = document.querySelector(".chibi video.front"); return v && v.readyState >= 2 && !v.paused; }, null, { timeout: 20000 })
    .catch(() => { throw new Error("Q 版小人没有动起来"); });
  expect(!!(await page.$eval(".chibi", (e) => e.dataset.clip)), "不是 Q 版小人");  // 片段下载完后地址是 blob:，看片段名
  const t0 = await page.$eval(".chibi video.front", (v) => v.currentTime);
  await page.waitForTimeout(600);
  expect((await page.$eval(".chibi video.front", (v) => v.currentTime)) !== t0, "视频没在播放");
  expect(!!(await page.$('.char-list img[src*="whale-girl-head"]')), "左边角色列表没有头像");
  await shot("02-home");
});

await step("一键开场白 → 流式回复 → 自动朗读", async () => {
  await page.click(".starters button >> nth=0");
  await page.waitForFunction(() => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant .bubble").length >= 1, null, { timeout: 30000 });
  const reply = await page.textContent(".msg.assistant:last-of-type .bubble");
  expect(reply && !reply.includes("<state>"), "回复为空或带标签");
  await page.waitForSelector(".msg.assistant .speak-btn", { timeout: 10000 }).catch(() => { throw new Error("回复旁没有朗读按钮"); });
  await shot("03-chat");
});

await step("点喇叭朗读（服务端语音）", async () => {
  const resp = page.waitForResponse((r) => r.url().endsWith("/api/voice/tts"), { timeout: 20000 });
  await page.click("#voice-toggle"); await page.click("#voice-toggle");  // 关再开：确认开关可用
  await page.click(".msg.assistant:last-of-type .speak-btn");
  const r = await resp;
  expect(r.status() === 200 && (r.headers()["content-type"] || "").includes("audio"), "朗读接口失败：" + r.status());
});

await step("Q 版小人：点“挥手”她就挥手", async () => {
  await page.click('#gestures button >> nth=0');
  await page.waitForFunction(() => document.querySelector(".chibi")?.dataset.clip === "wave", null, { timeout: 15000 })
    .catch(async () => { throw new Error("点“挥手”后她没有挥手：" + await page.$eval(".chibi", (e) => e.dataset.clip)); });
  await page.waitForTimeout(3000);  // 等她回应完，下一步的互动才不会被当成连点忽略
});

await step("预设互动（摸摸头）", async () => {
  const before = await page.locator(".msg").count();
  await page.click('#gestures [data-g="pat_head"]');
  await page.waitForFunction((n) => document.querySelectorAll(".msg").length > n, before, { timeout: 20000 });
  await shot("04-gesture");
});

await step("她记得的：说过的称呼被记下", async () => {
  await page.fill("#chat-input", "以后叫我小林吧");
  await page.press("#chat-input", "Enter");
  await page.waitForFunction(() => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant").length >= 3, null, { timeout: 30000 });
  await page.waitForTimeout(2500);
  await page.click("#drawer-toggle");
  await page.waitForSelector("#drawer:not(.hidden) .mem-card", { timeout: 15000 });
  expect((await page.textContent("#drawer .mem-list")).includes("小林"), "没记下称呼");
  await shot("05-drawer");
  await page.click("#drawer-close");
});

await step("角色页：改说话方式 → 表达变化；换 Live2D 形象", async () => {
  await page.click('.nav [data-view="persona"]');
  await page.waitForSelector("[data-p=speech]");
  await shot("06-persona");
  await page.fill("[data-p=speech]", "- 口头禅「收到，开饭开饭」");
  await page.click('.portrait-opt[data-portrait*="live2d"]');
  await page.click("#p-save");
  await page.waitForFunction(() => !document.querySelector("#toast").classList.contains("hidden"), null, { timeout: 10000 });
  await page.click('.nav [data-view="chat"]');
  await page.waitForSelector(".portrait canvas", { timeout: 30000 });
  await page.waitForTimeout(2500);
  await shot("07-live2d");
  await page.fill("#chat-input", "在做什么呢");
  await page.press("#chat-input", "Enter");
  await page.waitForFunction(() => /开饭开饭/.test(document.querySelector(".msg.assistant:last-of-type .bubble")?.textContent || ""), null, { timeout: 30000 });
  // 换回立绘
  await page.click('.nav [data-view="persona"]');
  await page.waitForSelector('.portrait-opt[data-portrait*="whale-girl.png"]');
  await page.click('.portrait-opt[data-portrait*="whale-girl.png"]');
  await page.click("#p-save");
  await page.waitForTimeout(800);
});

await step("联网：问天气 → 她查了一下，来源在气泡下面，正文没有网址", async () => {
  await page.click('.nav [data-view="chat"]');
  await page.fill("#chat-input", "帮我查一下今天杭州天气");
  await page.press("#chat-input", "Enter");
  await page.waitForSelector(".msg.assistant:last-of-type .sources a", { timeout: 30000 })
    .catch(() => { throw new Error("没有显示来源"); });
  const text = await page.textContent(".msg.assistant:last-of-type .bubble");
  expect(/模拟联网/.test(text) && !/http|example\.com/.test(text), "回复不对：" + text);
  expect((await page.textContent(".msg.assistant:last-of-type .sources")).includes("example.com"), "来源不对");
  await shot("07-web");
});

await step("工作台：一句话生成角色（性格 + 一张形象 + 声音）→ 整套表情 → 聊天里换上", async () => {
  await page.click('.nav [data-view="persona"]');
  await page.waitForSelector("#wb-prompt");
  const greetBefore = await page.inputValue("[data-p=greeting]");
  await page.fill("#wb-prompt", "一只戴围巾、爱读诗的小水獭");
  await page.click("#wb-new");
  // 在官方角色（大肥鱼）上点：新建一个角色，打开她的工作台
  await page.waitForFunction(() => { const a = document.querySelector(".cast-card.active b")?.textContent; return a && a !== "大肥鱼" && a !== "KRINO"
    && document.querySelector(".wb-stage img")?.src.includes("/media/"); }, null, { timeout: 60000 })
    .catch(async () => { throw new Error("没有新建出角色：" + await page.textContent("#toast").catch(() => "")); });
  const name = await page.textContent(".cast-card.active b");
  expect((await page.inputValue("[data-p=greeting]")) !== greetBefore, "灵魂还是原来的");
  expect(await page.locator(".pick-portrait .portrait-opt img[src*='/media/']").count() === 1, "应该只生成一张形象");
  expect((await page.inputValue("[data-v=voice]")) === "longanlingxin_v3.1", "声音没换：" + await page.inputValue("[data-v=voice]"));
  expect(!(await page.$eval("#p-save", (b) => b.classList.contains("dirty"))), "生成的角色应该已经存好");
  await page.click("#wb-faces");
  await page.waitForFunction(() => document.querySelectorAll(".wb-face img").length >= 10, null, { timeout: 60000 })
    .catch(() => { throw new Error("整套表情没生成出来"); });
  await shot("07-workbench");
  await page.waitForFunction(() => !document.querySelector("#p-save").classList.contains("dirty"), null, { timeout: 10000 })
    .catch(() => { throw new Error("表情生成后没有自动保存"); });
  await page.reload();
  await page.waitForSelector("#app:not(.hidden)");
  await page.click(`.char-list .char-item:has(.name:text-is("${name}"))`);
  await page.click('.nav [data-view="persona"]');
  await page.waitForFunction(() => document.querySelectorAll(".wb-face img").length >= 10, null, { timeout: 15000 })
    .catch(() => { throw new Error("刷新后表情没了"); });
  await page.click('.nav [data-view="chat"]');
  await page.waitForFunction(() => document.querySelector(".portrait > img:not([hidden])")?.getAttribute("src")?.includes("/media/"), null, { timeout: 15000 })
    .catch(() => { throw new Error("聊天页没有换上新形象"); });
  expect(await page.$eval(".portrait", (b) => b.classList.contains("has-faces")), "聊天页没有拿到整套表情");
  // 大肥鱼没被改动；后面的步骤回到她
  await page.click(".char-list .char-item:has(.name:text-is(\"大肥鱼\"))");
  await page.waitForFunction(() => document.querySelector("#chat-name")?.textContent === "大肥鱼", null, { timeout: 10000 });
  await page.waitForTimeout(1500);
  expect(!((await page.$eval(".portrait > img", (i) => i.hidden ? "" : i.getAttribute("src")).catch(() => "")) || "").includes("/media/"), "大肥鱼的形象被改成了新生成的");
});

await step("工坊：没有重复，一键领养后直接去聊天", async () => {
  await page.click('.nav [data-view="workshop"]');
  await page.waitForSelector("#ws-grid .ws-card");
  const titles = await page.locator("#ws-grid .ws-card h3").allTextContents();
  expect(titles.includes("KRINO") && titles.includes("大肥鱼") && new Set(titles).size === titles.length, "工坊不对：" + titles.join(","));
  await shot("08-workshop");
  await page.locator("#ws-grid .ws-card").filter({ has: page.locator("h3", { hasText: /^KRINO$/ }) }).locator("[data-adopt]").click();
  await page.waitForSelector("#view-chat:not(.hidden)", { timeout: 15000 });
  expect((await page.textContent("#chat-name")) === "KRINO", "领养后没切到 KRINO");
  await shot("09-adopted");
});

await step("设置：开关即时保存，高级里有眼镜模拟器", async () => {
  await page.click('.nav [data-view="settings"]');
  await page.waitForSelector(".settings-simple");
  await page.click("#adv summary");
  await page.waitForSelector("#g-connect", { timeout: 15000 });
  await page.click("#g-connect");
  await page.waitForFunction(() => /已连接/.test(document.querySelector("#g-state")?.textContent || ""), null, { timeout: 10000 });
  await page.fill("#g-text", "你好呀");
  await page.click("#g-say");
  await page.waitForSelector("#lens .ar-subtitle", { timeout: 30000 });
  await shot("10-settings-glasses");
  await page.click("#g-connect");
  expect(!/sk-|api_key/i.test(await page.textContent("#settings-page")), "页面上出现了密钥");
});

await step("断网提示", async () => {
  await page.click('.nav [data-view="chat"]');
  await ctx.setOffline(true);
  await page.fill("#chat-input", "断网了吗");
  await page.press("#chat-input", "Enter");
  await page.waitForSelector("#net-banner:not(.hidden)", { timeout: 10000 });
  await page.waitForFunction(() => document.querySelector("#chat-input").value === "断网了吗", null, { timeout: 5000 })
    .catch(() => { throw new Error("失败后没有把输入还给用户"); });
  await ctx.setOffline(false);
  await page.waitForSelector("#net-banner.hidden", { state: "attached", timeout: 15000 });
});

await step("窄屏布局", async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  expect(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)), "窄屏横向溢出");
  await shot("11-mobile");
});

await browser.close();
const failed = results.filter((r) => !r.ok);
if (errors.length) console.log("\n页面错误：\n" + [...new Set(errors)].map((e) => "  " + e).join("\n"));
console.log(`\n${results.length - failed.length}/${results.length} 通过 · 截图在 ${SHOTS}`);
process.exit(failed.length || errors.length ? 1 : 0);
