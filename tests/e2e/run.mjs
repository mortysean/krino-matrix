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

await step("注册并进入，默认角色 WHALE GIRL", async () => {
  await page.goto(URL_);
  await page.waitForSelector("#auth:not(.hidden)", { timeout: 15000 });
  await shot("01-auth");
  await page.fill("[name=username]", user);
  await page.fill("[name=password]", "secret123");
  await page.click("[data-action=register]");
  await page.waitForSelector("#app:not(.hidden)", { timeout: 15000 });
  const name = await page.textContent("#chat-name");
  expect(name === "鲸鱼娘", "默认角色名是 " + name);
  expect(await page.isVisible(".ai-badge"), "缺少 AI 标识");
});

await step("3D 角色加载并可见", async () => {
  await page.waitForFunction(() => /LIVE/.test(document.querySelector("#stage-status")?.textContent || ""), null, { timeout: 90000 });
  const st = await page.textContent("#stage-status");
  expect(await page.locator("#avatar-host canvas").count() === 1, "没有 3D 画布");
  await page.waitForTimeout(1500);
  await shot("02-home-3d");
  console.log("      状态：" + st);
});

await step("文字聊天（流式）+ 角色动作", async () => {
  await page.fill("#chat-input", "你好呀，叫我小林吧");
  await page.press("#chat-input", "Enter");
  await page.waitForSelector(".msg.assistant .bubble", { timeout: 30000 });
  await page.waitForFunction(() => !document.querySelector(".typing") && document.querySelectorAll(".msg.assistant").length >= 1, null, { timeout: 30000 });
  const reply = await page.textContent(".msg.assistant:last-of-type .bubble");
  expect(reply && !reply.includes("<state>"), "回复为空或带着 state 标签：" + reply);
  await page.waitForTimeout(800);
  await shot("03-chat");
});

await step("用户触发的预设互动（摸摸头）", async () => {
  const before = await page.locator(".msg").count();
  await page.click('#gestures [data-g="pat_head"]');
  await page.waitForFunction((n) => document.querySelectorAll(".msg").length > n, before, { timeout: 20000 });
  expect(await page.locator(".msg.event").count() >= 1, "没有互动事件记录");
  await page.waitForTimeout(600);
  await shot("04-gesture");
});

await step("语音模式切换（假麦克风）", async () => {
  await page.click('#input-mode [data-input="voice"]');
  await page.waitForTimeout(400);
  // 浏览器可能不支持语音识别：两种结果都可以，只要界面给出明确反馈
  const micVisible = await page.isVisible("#mic-btn");
  const toast = await page.textContent("#toast").catch(() => "");
  expect(micVisible || /语音识别|麦克风/.test(toast), "语音模式没有任何反馈");
  await page.click('#input-mode [data-input="text"]');
});

await step("记忆侧栏：记下了称呼", async () => {
  await page.waitForTimeout(1500);
  await page.click("#drawer-toggle");
  await page.waitForSelector("#drawer:not(.hidden) .mem-card", { timeout: 15000 });
  const txt = await page.textContent("#drawer .mem-list");
  expect(txt.includes("小林"), "侧栏里没有“小林”：" + txt);
  await shot("05-drawer");
  await page.click("#drawer-close");
});

await step("人格编辑器：修改后表达变化", async () => {
  await page.click('.nav [data-view="persona"]');
  await page.waitForSelector("[data-p=speech]");
  await shot("06-persona-form");
  await page.fill("[data-p=speech]", "- 说话很干脆\n- 口头禅「收到，领航员出发」");
  await page.selectOption("[data-b=style]", "活泼");
  await page.click("#p-save");
  await page.waitForFunction(() => /v2/.test(document.querySelector("#persona-ver")?.textContent || ""), null, { timeout: 10000 });
  await page.click('#persona-tabs [data-ptab="md"]');
  await page.waitForSelector("#src");
  expect((await page.inputValue("#src")).includes("收到，领航员出发"), "Markdown 里没有新的口头禅");
  await shot("07-persona-md");
  await page.click('.nav [data-view="chat"]');
  await page.click("#new-session");
  await page.waitForTimeout(500);
  await page.fill("#chat-input", "在做什么呢");
  await page.press("#chat-input", "Enter");
  await page.waitForFunction(() => /领航员出发/.test(document.querySelector(".msg.assistant:last-of-type .bubble")?.textContent || ""), null, { timeout: 20000 });
});

await step("记忆页：现实 / 推断 / 虚构，修改与删除", async () => {
  await page.fill("#chat-input", "*我们一起潜入了沉船*");
  await page.press("#chat-input", "Enter");
  await page.waitForTimeout(2500);
  await page.click('.nav [data-view="memory"]');
  await page.waitForSelector("#m-list .mem-card", { timeout: 15000 });
  const badges = await page.locator("#m-list .badge").allTextContents();
  expect(badges.includes("现实事件") && badges.includes("虚构故事"), "缺少现实/虚构标注：" + badges.join(","));
  await shot("08-memory");
  const story = page.locator("#m-list .mem-card", { hasText: "沉船" });
  page.once("dialog", (d) => d.accept());
  await story.locator('[data-m="delete"]').click();
  await page.click("#modal-ok");
  await page.waitForFunction(() => !/沉船/.test(document.querySelector("#m-list").textContent), null, { timeout: 10000 });
});

await step("创意工坊：发布、浏览、导入", async () => {
  await page.click('.nav [data-view="workshop"]');
  await page.click('#ws-tabs [data-wtab="publish"]');
  await page.waitForSelector("#pub-go");
  await page.selectOption("#pub-cat", "healing");
  await page.fill("#pub-desc", "端到端测试发布的角色");
  await page.click("#pub-go");
  await page.waitForSelector("#ws-body .ws-card", { timeout: 10000 });
  await page.click('#ws-tabs [data-wtab="browse"]');
  await page.waitForSelector("#ws-grid .ws-card");
  await shot("09-workshop");
  await page.locator("#ws-grid .ws-card").first().click();
  await page.waitForSelector("#modal:not(.hidden) .ws-actions");
  await shot("10-workshop-detail");
  await page.click("#modal-ok");
});

await step("眼镜模拟器：输入 → AR 输出事件", async () => {
  await page.click('.nav [data-view="glasses"]');
  await page.waitForSelector("#g-connect");
  await page.click("#g-connect");
  await page.waitForFunction(() => /已连接/.test(document.querySelector("#g-state")?.textContent || ""), null, { timeout: 10000 });
  await page.fill("#g-text", "你好呀");
  await page.click("#g-say");
  await page.waitForSelector("#lens .ar-subtitle", { timeout: 20000 });
  await page.fill("[data-pose=yaw]", "30");
  await page.dispatchEvent("[data-pose=yaw]", "input");
  await page.click("#g-frame");
  await page.waitForFunction(() => /PERCEIVE/.test(document.querySelector("#ev-log")?.textContent || ""), null, { timeout: 20000 });
  await page.waitForTimeout(1200);
  await shot("11-glasses");
  const log = await page.textContent("#ev-log");
  expect(/ar ar\.avatar/.test(log), "事件日志里没有 AR 输出");
  await page.click("#g-connect");
});

await step("设置：服务状态、策略测试", async () => {
  await page.click('.nav [data-view="settings"]');
  await page.waitForSelector("#s-test");
  await page.click("#s-test");
  await page.waitForSelector("#s-test-out table", { timeout: 30000 });
  const t = await page.textContent("#s-test-out");
  expect(/规则策略/.test(t) && /STORY/.test(t), "策略测试结果不对");
  expect(!/sk-|api_key/i.test(await page.textContent("#settings-page")), "页面上出现了密钥");
  await shot("12-settings");
});

await step("断网提示", async () => {
  await page.click('.nav [data-view="chat"]');
  await ctx.setOffline(true);
  await page.fill("#chat-input", "断网了吗");
  await page.press("#chat-input", "Enter");
  await page.waitForSelector("#net-banner:not(.hidden)", { timeout: 10000 });
  // 提示条在请求失败时就出现，输入框的文字在随后的错误处理里还回去：等它，而不是立刻读
  await page.waitForFunction(() => document.querySelector("#chat-input").value === "断网了吗", null, { timeout: 5000 })
    .catch(() => { throw new Error("失败后没有把输入还给用户"); });
  await shot("13-offline");
  await ctx.setOffline(false);
  await page.waitForSelector("#net-banner.hidden", { state: "attached", timeout: 15000 });
});

await step("窄屏布局", async () => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(!overflow, "窄屏横向溢出");
  await shot("14-mobile");
});

await browser.close();
const failed = results.filter((r) => !r.ok);
if (errors.length) console.log("\n页面错误：\n" + [...new Set(errors)].map((e) => "  " + e).join("\n"));
console.log(`\n${results.length - failed.length}/${results.length} 通过 · 截图在 ${SHOTS}`);
process.exit(failed.length || errors.length ? 1 : 0);
