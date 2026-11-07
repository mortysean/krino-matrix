// 入口：登录、侧边栏的角色列表、页面切换。每个页面的逻辑在各自的模块里。
import { $, $$, S, api, avaHTML, bus, esc, fail, storeGet, storeSet, t, toast, tr } from "./core.js";
import { applyDom, setLocale } from "./i18n.js";
import { initChat } from "./chat.js";
import { initMemory, refreshAsks } from "./memory.js";
import { initPersona, personaDirty, personaPage } from "./persona.js";
import { initWorkshop, workshopPage } from "./workshop.js";
import { initGlasses, leaveGlasses } from "./glasses.js";
import { settingsPage } from "./settings.js";

const PAGES = { chat: null, persona: personaPage, workshop: workshopPage, settings: settingsPage };

// ---------- 开场 ----------
const bootAt = Date.now();
function hideBoot() {
  const b = $("#boot");
  if (!b || b.classList.contains("done")) return;
  setTimeout(() => { b.classList.add("done"); setTimeout(() => b.remove(), 700); }, Math.max(0, 1600 - (Date.now() - bootAt)));
}

// ---------- 登录 ----------
$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const action = e.submitter?.dataset.action || "login";
  const f = new FormData(e.target);
  try {
    const r = await api("/api/auth/" + action, { body: { username: f.get("username"), password: f.get("password") } });
    S.token = r.token; storeSet("krino_token", r.token);
    await boot();
  } catch (err) { $("#auth-error").textContent = tr(err.message); }
});

function logout() {
  api("/api/auth/logout", { method: "POST" }).catch(() => {});
  S.token = null; S.me = null; S.chars = []; storeSet("krino_token", null);
  leaveGlasses();
  $("#modal").classList.add("hidden");
  $("#auth-form").password.value = "";
  $("#auth-error").textContent = "";
  $("#app").classList.add("hidden"); $("#auth").classList.remove("hidden");
}
$("#logout").onclick = () => bus.emit("logout");
bus.on("logout", logout);


// ---------- 角色 ----------
function renderChars() {
  $("#char-list").innerHTML = S.chars.map((c) => `
    <div class="char-item ${c.id === S.charId ? "active" : ""}" data-id="${c.id}" style="--c:${esc(c.color)}">
      ${avaHTML(c)}
      <div class="char-text"><div class="name">${esc(c.name)}</div><div class="muted small tagline" title="${esc(c.tagline)}">${esc(c.tagline)}</div></div>
    </div>`).join("");
  $$(".char-item").forEach((el) => (el.onclick = () => select(el.dataset.id)));
}

async function select(id, view) {
  if (!S.chars.find((c) => c.id === id)) id = S.chars[0]?.id;
  if (!id) return;
  const changed = id !== S.charId;
  S.charId = id; storeSet("krino_char", id);
  const c = S.chars.find((x) => x.id === id);
  document.documentElement.style.setProperty("--char", c.color);
  $$(".char-label").forEach((el) => (el.textContent = c.name));
  renderChars();
  if (changed || !select.done) { select.done = true; bus.emit("character"); }
  show(view || (["chat", "persona"].includes(S.view) ? S.view : "chat"));
}

bus.on("chars", (selectId) => { renderChars(); if (selectId) select(selectId); });
bus.on("select", ({ id, view }) => select(id, view));
bus.on("goto", (view) => show(view));

// ---------- 页面 ----------
async function show(view) {
  if (S.view === "persona" && view !== "persona" && personaDirty() && !confirm(t("工作台里的修改还没保存，要离开吗？"))) return;
  if (S.view === "settings" && view !== "settings") leaveGlasses();
  S.view = view;
  $$(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach((v) => {
    const on = v.id === "view-" + view;
    v.classList.toggle("hidden", !on);
    if (on) { v.classList.remove("view-enter"); void v.offsetWidth; v.classList.add("view-enter"); }
  });
  bus.emit("view", view);
  try { await PAGES[view]?.(); } catch (e) { fail(e); }
}
$$(".nav button").forEach((b) => (b.onclick = () => show(b.dataset.view)));

// ---------- 启动 ----------
async function boot() {
  if (!S.token) { $("#auth").classList.remove("hidden"); hideBoot(); return; }
  try { S.me = await api("/api/me"); }
  catch (e) {
    if (e.status === 0) { $("#auth-error").textContent = t("连不上服务器，请稍后刷新"); }
    $("#auth").classList.remove("hidden"); hideBoot(); return;
  }
  S.me.dev = storeGet("krino_dev") === "1";
  $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#me-name").textContent = S.me.display_name;
  api("/api/health").then((h) => $("#demo-badge").classList.toggle("hidden", !h.mock)).catch(() => {});
  S.chars = await api("/api/characters");
  select.done = false;
  // 从外面带着 #workbench 进来（比如 DSH 桌宠插件里的“捏一个自己的伙伴”）：登录后直接打开工作台
  const fromPet = location.hash === "#workbench";
  if (fromPet) history.replaceState(null, "", location.pathname + location.search);
  await select(S.chars.find((c) => c.id === S.charId)?.id || S.chars[0]?.id, fromPet ? "persona" : "chat");
  refreshAsks();
  hideBoot();
}

// 站点版本：决定商标（国内版中文商标，海外版英文）、界面语言、页脚备案号
async function loadSite() {
  S.site = await fetch("/api/site").then((r) => r.json()).catch(() => S.site);
  document.documentElement.dataset.edition = S.site.edition;
  await setLocale(S.site.locale);
  applyDom();
  const foot = [S.site.company, S.site.icp && `<a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener">${esc(S.site.icp)}</a>`,
    S.site.police && esc(S.site.police),
    S.site.switch?.url && `<a href="${esc(S.site.switch.url)}">${esc(S.site.switch.label)}</a>`].filter(Boolean).join(" · ");
  $("#site-foot").innerHTML = foot;
}

await loadSite();
initChat();
initMemory();
initPersona();
initWorkshop();
initGlasses();
window.addEventListener("unhandledrejection", (e) => { if (e.reason?.message) console.warn(e.reason); });
boot().catch((e) => { hideBoot(); fail(e); toast(t("启动失败：{msg}", { msg: tr(e.message) }), 6000); });
