// 新角色的创建进度：页面右下角一张卡片，关掉“新角色”窗口、切到别的页面都一直在。
//   写灵魂（十几秒到半分钟）→ 建角色 → 画形象、设计声音（后台，大约一分钟）→ 全部做好才通知，点一下去和她聊天。
// 创建中的角色在侧边栏里显示“创建中”，点不进去；刷新页面也会接着等（后端在角色上记着 pending 和做到哪一步）。
import { $, S, api, bus, esc, t } from "./core.js";

const jobs = new Map();  // key → { kind: "soul" | "char" | "motion", name, started, steps, done, ok, id, motion: {done, total} }
let timer = null;

const dock = document.createElement("div");
dock.id = "create-dock";
dock.setAttribute("aria-live", "polite");
document.body.appendChild(dock);

const secs = (j) => Math.max(0, Math.round((Date.now() - j.started) / 1000));
const clock = (n) => `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;  // 已用时间：分:秒
const STEP_LABELS = { soul: "灵魂", portrait: "立绘", voice: "声音", motion: "动图" };

// 卡片的内容（不含已用时间）。只有它变了（步骤打勾、动图做到第几段、做完）才重画这张卡片；
// 已用时间每秒只改那一小段文字。整张重画会让卡片的出现动画、像素动画、转圈都从头来，看起来一直在闪
function cardHTML(key, j) {
  if (j.done) {
    const msg = j.kind === "soul" ? t("{name} 的灵魂写好了", { name: j.name }) : j.kind === "motion"
      ? (j.ok ? t("{name} 的动图做好了", { name: j.name }) : t("{name} 的动图没做成", { name: j.name })) : t("{name} 创建好了", { name: j.name });
    const go = j.kind === "soul" ? t("接着看") : t("去聊天");
    return `<span class="cd-ok">✓</span>
      <div class="cd-body"><b>${esc(msg)}</b>${j.kind === "char" && !j.ok ? `<span class="muted small">${esc(t("形象没画出来，可以在工作台里再画一次"))}</span>` : ""}${j.kind === "motion" && !j.ok ? `<span class="muted small">${esc(t("没扣积分，可以在工作台里再试一次"))}</span>` : ""}</div>
      <button class="small" data-cd-go="${esc(key)}">${esc(go)}</button><button class="link small cd-x" data-cd-x="${esc(key)}" aria-label="${esc(t("关闭"))}">✕</button>`;
  }
  const steps = Object.entries(j.steps).map(([k, ok]) => `<li class="${ok ? "ok" : "run"}">${ok ? "✓" : "<i></i>"} ${esc(t(STEP_LABELS[k]))}${
    k === "motion" && !ok && j.motion?.total ? ` ${j.motion.done}/${j.motion.total}` : ""}</li>`).join("");
  const title = j.kind === "soul" ? t("正在写灵魂") : j.kind === "motion" ? t("正在给 {name} 做动图", { name: j.name }) : t("正在创建 {name}", { name: j.name });
  const hint = j.kind === "soul" ? t("十几秒到半分钟") : "motion" in j.steps ? t("大约 10 分钟") : t("大约一分钟");
  return `<div class="cd-anim" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
    <div class="cd-body"><b>${esc(title)}</b><ul class="cd-steps">${steps}</ul>
    <span class="muted small"><span class="cd-time"></span> · ${esc(t("{hint} · 可以先做别的，好了会通知你", { hint }))}</span></div>`;
}

function render() {
  for (const el of [...dock.children]) if (!jobs.has(el.dataset.key)) el.remove();  // 关掉的、做完被点走的
  for (const [key, j] of jobs) {
    let el = [...dock.children].find((x) => x.dataset.key === key);
    if (!el) {  // 新的任务：新建一张卡片（只有这时播放出现动画）
      el = document.createElement("div");
      el.dataset.key = key;
      dock.appendChild(el);
    }
    const html = cardHTML(key, j);
    if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html; el.className = "cd-card" + (j.done ? " done" : ""); }
    const time = el.querySelector(".cd-time");
    if (time) time.textContent = t("已用 {t}", { t: clock(secs(j)) });
  }
  dock.classList.toggle("hidden", !jobs.size);
  const ready = [...jobs.values()].filter((j) => j.done).length;
  const title = (ready ? `(${ready}) ` : "") + document.title.replace(/^\(\d+\) /, "");
  if (document.title !== title) document.title = title;
}

dock.addEventListener("click", (e) => {
  const go = e.target.closest("[data-cd-go]"), x = e.target.closest("[data-cd-x]");
  const key = (go || x)?.dataset[go ? "cdGo" : "cdX"];
  if (!key) return;
  const j = jobs.get(key);
  jobs.delete(key); render();
  if (go && j?.kind === "soul") bus.emit("newchar:open");
  if (go && j?.kind === "char") bus.emit("select", { id: j.id, view: "chat" });
  if (go && j?.kind === "motion") bus.emit("select", { id: j.id, view: "persona" });
});

function tick() {  // 每秒更新计时；每 3 秒问一次后台做到哪了
  const live = [...jobs.values()].some((j) => !j.done);
  if (!live) { clearInterval(timer); timer = null; return; }
  render();
  if ((tick.n = (tick.n || 0) + 1) % 3 === 0) poll();
}
const run = () => { render(); timer ||= setInterval(tick, 1000); };

async function poll() {
  for (const [key, j] of jobs) {
    if (j.kind === "soul" || j.done) continue;
    const c = await api("/api/characters/" + j.id).catch((e) => (e.status === 404 ? { gone: true } : null));
    if (!c) continue;
    if (c.gone) { jobs.delete(key); continue; }
    if (j.kind === "char" && c.pending) { j.steps = steps(c.progress); j.motion = c.progress?.motion; continue; }
    if (j.kind === "motion" && c.motion_job) { j.motion = c.motion_job; j.started = startedAt(c.motion_job); continue; }
    j.done = true;
    j.ok = j.kind === "motion" ? c.behavior?.portrait?.kind === "chibi" : !!c.behavior?.portrait;
    S.chars = await api("/api/characters").catch(() => S.chars);
    bus.emit("chars"); bus.emit("creating:done", c.id);
    notify(j.kind === "motion" ? t("{name} 的动图做好了", { name: c.name }) : t("{name} 创建好了", { name: c.name }));
  }
  render();
}

function notify(msg) {  // 页面在后台时，用系统通知提醒一声（用户允许过才发）
  if (!document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  try { new Notification("KRINO WORLD", { body: msg, icon: "/static/assets/krino-mark.svg" }); } catch { /* 有的浏览器只允许在 Service Worker 里发 */ }
}
export function askNotify() {  // 开始创建时问一次能不能发通知（用户点了按钮才问，浏览器才允许）
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
}

// 写灵魂：开始、结束（done=false 表示失败了，直接去掉）
export function soulStarted() { jobs.set("soul", { kind: "soul", name: "", started: Date.now(), steps: { soul: false } }); run(); }
export function soulFinished(name, { show = true, ok = true } = {}) {
  if (!ok || !show) { jobs.delete("soul"); render(); return; }
  jobs.set("soul", { kind: "soul", name, started: Date.now(), steps: { soul: true }, done: true });
  notify(t("{name} 的灵魂写好了", { name })); render();
}

const steps = (p = {}) => ({ soul: true, portrait: !!p.portrait, voice: !!p.voice, ...(p.motion ? { motion: false } : {}) });

// 角色建好、开始在后台做形象和声音（勾了动图的还有动图）
export function charStarted(c, { motion = false } = {}) {
  const p = c.progress || {};
  const st = steps(p);
  if (motion) st.motion = false;
  jobs.set(c.id, { kind: "char", id: c.id, name: c.name, started: p.started ? p.started * 1000 : Date.now(), steps: st, motion: p.motion });
  run();
}

// 服务器记着什么时候开始的（秒）：刷新页面、换设备打开，已用时间都接着算
const startedAt = (j) => (j?.started ? j.started * 1000 : Date.now());

// 已有的角色补做动图（工作台里点的）：做的时候照常能聊
export function motionStarted(c) {
  jobs.set("m:" + c.id, { kind: "motion", id: c.id, name: c.name, started: startedAt(c.motion_job), steps: { motion: false }, motion: c.motion_job });
  run();
}

// 刷新页面、换设备登录：把还在做的接着显示出来
function resume() {
  for (const c of S.chars || []) {
    if (c.pending && !jobs.has(c.id)) charStarted(c);
    if (c.motion_job && !jobs.has("m:" + c.id)) jobs.set("m:" + c.id, { kind: "motion", id: c.id, name: c.name, started: startedAt(c.motion_job), steps: { motion: false }, motion: c.motion_job });
  }
  if (jobs.size) run();
}
bus.on("chars:loaded", resume);
bus.on("chars", resume);
bus.on("logout", () => { jobs.clear(); render(); });
render();
