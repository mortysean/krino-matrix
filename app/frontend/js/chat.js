// 01 聊天：左边是她（2D 立绘 / Live2D），右边是对话。
// 一键原则：会话自动管理（打开就能说，不用“开始 / 结束”）；每条回复右边一个喇叭，点一下就读；
// 舞台右上角的喇叭开关决定是否自动朗读；麦克风点一下开始、再点一下发送。
// 角色做什么（说话 / 表情 / 动作 / 讲故事 / 提议记住）由后端互动策略决定，这里只执行后端给的 actions。
import { $, $$, S, api, avaHTML, bus, curChar, esc, fail, ripple, storeGet, storeSet, t, toast, tr } from "./core.js";
import { createStage } from "./stage.js";
import { ICON } from "./icons.js";
import { listen, speak, stopSpeaking, sttAvailable } from "./voice.js";
import { renderDrawer, refreshAsks } from "./memory.js";

const GESTURES = [["wave", "挥手"], ["pat_head", "摸摸头"], ["high_five", "击掌"], ["poke", "戳一下"], ["cheer_up", "加油"]];

const C = {
  session: null, pending: false, listening: null, image: null, stage: null, portraitFor: null,
  autoRead: storeGet("krino_autoread") !== "0", lastActivity: Date.now(), idleCount: 0, seen: new Set(), jobs: {},
};

// ---------- 形象 ----------
async function ensureStage() {
  const c = curChar();
  if (!c) return;
  C.stage ||= createStage($("#stage-host"), { onStatus: (s) => { if (s.state === "fallback") toast(s.message, 5000); } });
  const key = c.id + JSON.stringify(c.portrait || {});
  if (C.portraitFor === key) return;
  C.portraitFor = key;
  await C.stage.load(c.portrait, { name: c.name, color: c.color });
  C.stage.setExpression(c.default_expression || "calm");
}

function sayOnStage(text, story) {
  const el = $("#stage-say");
  if (!text) return el.classList.add("hidden");
  el.textContent = text.length > 110 ? text.slice(0, 108) + "…" : text;
  el.classList.toggle("story", !!story);
  el.classList.remove("hidden");
  clearTimeout(sayOnStage._t);
  sayOnStage._t = setTimeout(() => el.classList.add("hidden"), Math.min(14000, 3000 + text.length * 120));
}

// 朗读一句话，并让她的嘴跟着动
async function readAloud(text, btn) {
  if (!text) return;
  stopSpeaking();
  $$(".speak-btn.on").forEach((b) => b.classList.remove("on"));
  btn?.classList.add("on");
  try {
    const r = await speak(text, curChar()?.voice || {});
    if (r.audio) C.stage?.attachAudio(r.audio); else C.stage?.speaking(true);
    await r.done;
  } catch (e) { fail(e); }
  C.stage?.speaking(false);
  btn?.classList.remove("on");
}

// 执行后端给的行为
function perform(actions, { speakIt = false } = {}) {
  // Q 版小人用身体动作表达情绪：同一句里既有动作又有表情时，先做动作（表情片段在动作之后 0.4 秒内不会再抢）
  const ordered = [...(actions || [])].sort((x, y) => (y.type === "animate") - (x.type === "animate"));
  for (const a of ordered) {
    if (a.type === "emote") C.stage?.setExpression(a.expression);
    else if (a.type === "animate") C.stage?.play(a.name).catch(() => {});
    else if (a.type === "perceive_request") toast("她想看看：点输入框左边的图片按钮发一张图", 5000);
    else if (a.type === "remember_suggest") rememberChip(a);
  }
  const say = (actions || []).find((a) => a.type === "say");
  if (!say) return;
  sayOnStage(say.text, say.story);
  if (speakIt || C.autoRead) readAloud(say.text, $(".msg.assistant:last-of-type .speak-btn"));
  else { C.stage?.speaking(true); setTimeout(() => C.stage?.speaking(false), Math.min(6000, 600 + say.text.length * 90)); }
}

function rememberChip(a) {
  const div = document.createElement("div");
  div.className = "chip";
  div.innerHTML = `<b>${t("记下来？")}</b>${esc(a.content.slice(0, 40))} <button class="small" data-ok>${t("记住")}</button><button class="small ghost" data-no>${t("不用")}</button>`;
  $("#messages").appendChild(div);
  div.querySelector("[data-ok]").onclick = async () => {
    try { await api(`/api/memories/candidates/${a.candidate_id}/accept`, { body: {} }); toast("记住了"); div.remove(); refreshAsks(); } catch (e) { fail(e); }
  };
  div.querySelector("[data-no]").onclick = () => { api(`/api/memories/candidates/${a.candidate_id}`, { method: "DELETE" }).catch(() => {}); div.remove(); refreshAsks(); };
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

// ---------- 会话：自动管理 ----------
async function loadSession() {
  const list = await api("/api/sessions?character_id=" + S.charId);
  const open = list.find((s) => !s.ended);
  C.session = open ? await api("/api/sessions/" + open.id) : null;
  renderMessages();
}

async function ensureSession() {
  if (C.session && !C.session.ended) return;
  const s = await api("/api/sessions", { body: { character_id: S.charId } });
  C.session = { ...s, messages: [] };
}

async function newTopic() {
  if (C.pending) return;
  if (C.session && !C.session.ended && C.session.messages.length) {
    const r = await api(`/api/sessions/${C.session.id}/end`, { method: "POST" }).catch(fail);
    if (r?.summary?.title) toast("上一段已写成回忆");
  }
  C.session = null;
  renderMessages();
  greet();
}

function greet() {
  const g = curChar()?.greeting;
  if (!g) return;
  sayOnStage(g);
  C.stage?.play("wave").catch(() => {});
  C.stage?.setExpression("happy");
}

// ---------- 消息 ----------
function renderMessages() {
  const box = $("#messages"), c = curChar();
  if (!C.session?.messages?.length) {
    box.innerHTML = c ? `<div class="empty"><div class="em-title">${esc(c.greeting || t("和 {name} 打个招呼", { name: c.name }))}</div>
      <div class="em-greet">${esc(c.name)} · AI</div>
      <div class="starters">${starters(c).map((x) => `<button class="ghost small" data-starter="${esc(x)}">${esc(x)}</button>`).join("")}</div></div>` : "";
    $$("[data-starter]", box).forEach((b) => (b.onclick = () => send(b.dataset.starter)));
    return;
  }
  box.innerHTML = C.session.messages.map(msgHTML).join("") + (C.pending ? typingHTML() : "");
  C.session.messages.forEach((m) => C.seen.add(m.id));
  bindMsgTools(box);
  box.scrollTop = box.scrollHeight;
}

// 空会话里给三个一点就发的开场白，不用想第一句说什么
function starters(c) {
  return (c.official ? ["你好呀，介绍一下你自己", "今天吃了几碗饭？", "给我讲个深海的故事"] : ["你好呀", "介绍一下你自己", "给我讲个故事吧"]).map((x) => t(x));
}

const typingHTML = () => `<div class="typing">${avaHTML(curChar())}<div class="dots"><i></i><i></i><i></i></div></div>`;

function msgHTML(m) {
  const enter = C.seen.has(m.id) ? "" : " enter";
  if (m.role === "event") return `<div class="msg event${enter}">${esc(m.content)}</div>`;
  if (m.role === "user") {
    return `<div class="msg user${enter}" data-id="${m.id}"><div class="msg-col"><div class="bubble">${esc(m.content)}</div>
      <div class="msg-tools"><button class="link" data-act="remember" data-id="${m.id}">${t("记住这句")}</button></div></div></div>`;
  }
  const c = curChar(), story = (m.meta?.actions || []).some((a) => a.type === "say" && a.story);
  return `<div class="msg assistant${enter}" data-id="${m.id}" style="--c:${esc(c?.color || "")}">${avaHTML(c)}<div class="msg-col">
    <div class="bubble-row"><div class="bubble${story ? " story" : ""}">${esc(m.content)}</div>
      <button class="speak-btn" data-speak="${m.id}" title="${t("朗读")}">${ICON.speaker}</button></div>
    ${story ? `<div class="who">${t("虚构故事")}</div>` : ""}
    ${sourcesHTML(m.meta?.sources)}
    <div class="mem-pill-slot" data-for="${m.id}">${memPillHTML(C.jobs[m.id])}</div>
    ${S.me?.dev ? devTraceHTML(m) : ""}</div></div>`;
}

// 联网时她查过的网页：气泡下面一行小字，点了在新标签页打开
function sourcesHTML(list) {
  if (!list?.length) return "";
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
  return `<div class="sources">${t("查了")} ${list.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer" title="${esc(s.title || s.url)}">${esc(host(s.url))}</a>`).join("")}</div>`;
}

function memPillHTML(job) {
  const r = job?.status === "done" ? job.result : null;
  if (!r) return "";
  const bits = [];
  if (r.created?.length) bits.push(t("记下了 {items}", { items: r.created.map((x) => "「" + esc(x.title) + "」").join("") }));
  if (r.updated?.length) bits.push(t("更新了 {items}", { items: r.updated.map((x) => "「" + esc(x.title) + "」").join("") }));
  if (r.pending?.length) bits.push(t("有 {n} 件想问你", { n: r.pending.length }));
  return bits.length ? `<button class="mem-pill" data-act="open-drawer" data-tab="${r.pending?.length && !r.created?.length ? "ask" : "mem"}">◇ ${bits.join(" · ")}</button>` : "";
}

// 开发者视图（设置 → 高级）：这一轮策略的候选与打分、用到的记忆
function devTraceHTML(m) {
  const d = m.meta?.decision;
  if (!d) return "";
  const cands = d.candidates.map((c) => `<li>${c.blocked ? "✗" : (c.id === d.primary.id || d.extras.some((x) => x.id === c.id)) ? "●" : "○"} ${esc(c.action)} · ${c.score}${c.blocked ? " — " + esc(tr(c.blocked)) : c.reason ? " — " + esc(tr(c.reason)) : ""}</li>`).join("");
  return `<details class="trace"><summary>◇ ${esc(tr(d.label))} · ${d.latency_ms}ms${d.note ? " · " + esc(tr(d.note)) : ""}</summary><ul>${cands}</ul></details>`;
}

function bindMsgTools(root) {
  $$('[data-act="remember"]', root).forEach((b) => (b.onclick = () => {
    const m = C.session.messages.find((x) => x.id == b.dataset.id);
    bus.emit("memory:new", { content: m.content, source_message_id: m.id });
  }));
  $$('[data-act="open-drawer"]', root).forEach((b) => (b.onclick = () => openDrawer(b.dataset.tab)));
  $$("[data-speak]", root).forEach((b) => (b.onclick = () => {
    if (b.classList.contains("on")) { stopSpeaking(); C.stage?.speaking(false); b.classList.remove("on"); return; }
    readAloud(C.session.messages.find((x) => x.id == b.dataset.speak)?.content, b);
  }));
}

async function watchJob(jobId, replyId) {
  for (let i = 0; i < 4; i++) {
    const j = await api(`/api/memory-jobs/${jobId}?wait=8`).catch(() => null);
    if (!j) return;
    if (j.status === "done" || j.status === "failed") {
      C.jobs[replyId] = j;
      const slot = $(`.mem-pill-slot[data-for="${replyId}"]`);
      if (slot) { slot.innerHTML = memPillHTML(j); bindMsgTools(slot); }
      if (j.result?.pending?.length) refreshAsks();
      return;
    }
  }
}

// ---------- 发送（流式） ----------
async function send(text, { source = "app" } = {}) {
  if (C.pending) return;
  text = (text || "").trim();
  if (!text && !C.image) return;
  text ||= t("你看看这个");
  activity();
  stopSpeaking();
  C.pending = true;
  $("#send-btn").disabled = true;
  try {
    await ensureSession();
    const image = C.image; clearImage();
    C.session.messages.push({ id: "tmp", role: "user", content: text, meta: { image: !!image, source } });
    renderMessages();
    if ($("#chat-input").value.trim() === text) $("#chat-input").value = "";
    C.stage?.play("think").catch(() => {});
    const res = await api(`/api/sessions/${C.session.id}/stream`, { body: { text, image, source: source === "voice" ? "voice" : "app" }, raw: true });
    let live = null, done = null, error = null;
    for await (const [ev, data] of sse(res)) {
      if (ev === "delta") {
        if (!live) {
          C.pending = false; renderMessages();
          live = document.createElement("div");
          live.className = "msg assistant enter";
          live.innerHTML = `${avaHTML(curChar())}<div class="msg-col"><div class="bubble"></div></div>`;
          $("#messages").appendChild(live);
        }
        live.querySelector(".bubble").textContent += data.text;
        $("#messages").scrollTop = $("#messages").scrollHeight;
      }
      if (ev === "done") done = data;
      if (ev === "error") error = data.message;
    }
    if (error) throw new Error(error);
    C.session.messages.pop();
    C.pending = false;
    if (done.user) C.session.messages.push(done.user);
    if (done.reply) C.session.messages.push(done.reply);
    renderMessages();
    if (!done.reply) toast("她安静地陪在你身边", 2000);
    perform(done.actions, { speakIt: source === "voice" });
    if (done.memory_job && done.reply) watchJob(done.memory_job, done.reply.id);
  } catch (e) {
    C.pending = false;
    if (C.session?.messages?.at(-1)?.id === "tmp") C.session.messages.pop();
    renderMessages();
    $("#chat-input").value = text;
    C.stage?.setExpression("worried");
    fail(e);
  } finally {
    C.pending = false;
    $("#send-btn").disabled = false;
  }
}

async function* sse(res) {
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i); buf = buf.slice(i + 2);
      const ev = /^event: (.*)$/m.exec(block)?.[1], data = /^data: (.*)$/m.exec(block)?.[1];
      if (ev && data) yield [ev, JSON.parse(data)];
    }
  }
}

// ---------- 预设互动 / 安静事件 ----------
async function sendEvent(body) {
  if (C.pending || !S.charId) return;  // 她一次只回应一件事：上一句还没回来时，连点的互动和发送都忽略
  C.pending = true;
  $("#gestures")?.classList.add("busy");
  try {
    await ensureSession();
    const r = await api(`/api/sessions/${C.session.id}/events`, { body });
    if (r.user) C.session.messages.push(r.user);
    if (r.reply) C.session.messages.push(r.reply);
    if (r.user || r.reply) renderMessages();
    C.pending = false;
    perform(r.actions);
  } catch (e) { if (body.type !== "idle") fail(e); }
  finally { C.pending = false; $("#gestures")?.classList.remove("busy"); }
}

function activity() { C.lastActivity = Date.now(); C.idleCount = 0; }
setInterval(() => {
  const it = S.me?.settings?.interaction || {};
  if (S.view !== "chat" || document.hidden || C.pending || !C.session || C.session.ended || it.proactive === false) return;
  if (Date.now() - C.lastActivity < (it.idle_seconds || 45) * 1000) return;
  C.idleCount += 1; C.lastActivity = Date.now();
  sendEvent({ type: "idle", idle_count: C.idleCount });
}, 5000);

// ---------- 图片 ----------
function clearImage() { C.image = null; $("#img-chip").classList.add("hidden"); $("#img-chip").innerHTML = ""; }
async function pickImage(file) {
  if (!file) return;
  if (file.size > 4 * 1024 * 1024) return toast("图片不能超过 4MB");
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) return toast("只支持 PNG / JPEG / WebP");
  C.image = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(file); });
  $("#img-chip").innerHTML = `<img src="${C.image}" alt=""> ${t("会和下一句话一起发给她")} <button class="link small" id="img-x">${t("移除")}</button>`;
  $("#img-chip").classList.remove("hidden");
  $("#img-x").onclick = clearImage;
}

// ---------- 麦克风：点一下开始，再点一下发送 ----------
function micIdle() { $("#mic-btn").classList.remove("listening"); $("#mic-btn").innerHTML = ICON.mic; }
async function toggleMic() {
  if (C.listening) {
    const l = C.listening; C.listening = null; micIdle();
    try { const text = await l.stop(); if (text) send(text, { source: "voice" }); else toast("没听清，再说一次？"); } catch (e) { fail(e); }
    return;
  }
  const a = await sttAvailable();
  if (!a.ok) return toast(a.why, 5000);
  stopSpeaking();
  try {
    C.listening = await listen({ onPartial: (x) => ($("#chat-input").value = x) });
    $("#mic-btn").classList.add("listening"); $("#mic-btn").innerHTML = ICON.stop;
    C.stage?.setExpression("focused");
  } catch (e) { C.listening = null; micIdle(); fail(e.name === "NotAllowedError" ? new Error(t("没有麦克风权限：请在浏览器地址栏允许麦克风")) : e); }
}

function setAutoRead(on) {
  C.autoRead = on; storeSet("krino_autoread", on ? "1" : "0");
  $("#voice-toggle").classList.toggle("off", !on);
  $("#voice-toggle").innerHTML = on ? ICON.speaker : ICON.mute;
  $("#voice-toggle").title = on ? t("自动朗读：开（点一下关闭）") : t("自动朗读：关（点一下打开）");
  if (!on) { stopSpeaking(); C.stage?.speaking(false); }
}

// ---------- 侧栏 ----------
function openDrawer(tab) { $("#drawer").classList.remove("hidden"); renderDrawer($("#drawer-body"), tab); }
function closeDrawer() { $("#drawer").classList.add("hidden"); }

export function initChat() {
  $("#gestures").innerHTML = GESTURES.map(([id, label]) => `<button data-g="${id}">${t(label)}</button>`).join("");
  $$("#gestures button").forEach((b) => (b.onclick = () => { activity(); ripple(b); sendEvent({ type: "gesture", gesture: b.dataset.g }); }));
  $("#chat-input").addEventListener("keydown", (e) => {
    activity();
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
  });
  $("#chat-input").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = Math.min(140, e.target.scrollHeight) + "px"; });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); ripple($("#send-btn")); send($("#chat-input").value); });
  $("#new-session").onclick = () => newTopic().catch(fail);
  $("#mic-btn").onclick = toggleMic;
  $("#img-btn").innerHTML = ICON.image; micIdle();
  $("#voice-toggle").onclick = () => setAutoRead(!C.autoRead);
  setAutoRead(C.autoRead);
  $("#img-btn").onclick = () => $("#img-file").click();
  $("#img-file").onchange = (e) => { pickImage(e.target.files[0]); e.target.value = ""; };
  $("#drawer-toggle").onclick = () => ($("#drawer").classList.contains("hidden") ? openDrawer() : closeDrawer());
  $("#drawer-close").onclick = closeDrawer;
  $("#stage").addEventListener("pointermove", (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    C.stage?.setLook(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1));
  });
  bus.on("online", ({ ok, why }) => {
    $("#net-banner").textContent = ok ? "" : why || t("连接断开");
    $("#net-banner").classList.toggle("hidden", ok);
    if (ok) toast("连接恢复了");
  });
  bus.on("character", async () => {
    const c = curChar();
    if (!c) return;
    $("#chat-name").textContent = c.name;
    C.jobs = {};
    await Promise.all([loadSession().catch(fail), ensureStage().catch(fail)]);
    refreshAsks();
    if (!$("#drawer").classList.contains("hidden")) renderDrawer($("#drawer-body"));
    if (!C.session) greet();
  });
  bus.on("character:changed", () => { C.portraitFor = null; ensureStage().catch(fail); });
  bus.on("view", (v) => { if (v === "chat") { renderMessages(); ensureStage().catch(fail); } });
  bus.on("logout", () => { Object.assign(C, { session: null, pending: false, jobs: {} }); C.seen = new Set(); stopSpeaking(); });
}
