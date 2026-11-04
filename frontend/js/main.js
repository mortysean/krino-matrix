// 入口：登录、侧边栏的角色列表、页面切换。每个页面的逻辑在各自的模块里。
import { $, $$, S, api, avaHTML, bus, esc, fail, storeGet, storeSet, toast } from "./core.js";
import { initChat } from "./chat.js";
import { initMemory, memoryPage, refreshAsks } from "./memory.js";
import { initPersona, personaDirty, personaPage } from "./persona.js";
import { initWorkshop, workshopPage } from "./workshop.js";
import { glassesPage, initGlasses, leaveGlasses } from "./glasses.js";
import { settingsPage } from "./settings.js";

const PAGES = { chat: null, persona: personaPage, memory: memoryPage, workshop: workshopPage, glasses: glassesPage, settings: settingsPage };

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
  } catch (err) { $("#auth-error").textContent = err.message; }
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
      <div><div class="name">${esc(c.name)} ${c.official ? '<span class="badge">官方</span>' : c.workshop && !c.workshop.own ? '<span class="badge">工坊</span>' : ""}</div>
      <div class="muted small mono">AI · ${esc(c.style)}</div></div>
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
  show(view || (["chat", "persona", "memory", "glasses"].includes(S.view) ? S.view : "chat"));
}

bus.on("chars", (selectId) => { renderChars(); if (selectId) select(selectId); });
bus.on("select", ({ id, view }) => select(id, view));

// ---------- 页面 ----------
async function show(view) {
  if (S.view === "persona" && view !== "persona" && personaDirty() && !confirm("人格编辑还没保存，要离开吗？")) return;
  if (S.view === "glasses" && view !== "glasses") leaveGlasses();
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
    if (e.status === 0) { $("#auth-error").textContent = "连不上服务器，请稍后刷新"; }
    $("#auth").classList.remove("hidden"); hideBoot(); return;
  }
  S.me.dev = storeGet("krino_dev") === "1";
  $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden");
  $("#me-name").textContent = S.me.display_name;
  api("/api/health").then((h) => $("#demo-badge").classList.toggle("hidden", !h.mock)).catch(() => {});
  S.chars = await api("/api/characters");
  select.done = false;
  await select(S.chars.find((c) => c.id === S.charId)?.id || S.chars[0]?.id, "chat");
  refreshAsks();
  hideBoot();
}

initChat();
initMemory();
initPersona();
initWorkshop();
initGlasses();
window.addEventListener("unhandledrejection", (e) => { if (e.reason?.message) console.warn(e.reason); });
boot().catch((e) => { hideBoot(); fail(e); toast("启动失败：" + e.message, 6000); });
