// 01 互动主页：3D 角色在中间，右边是聊天。角色做什么（说话 / 表情 / 动作 / 讲故事 / 提议记住）由后端的互动策略决定，
// 这里只负责执行后端返回的结构化行为（actions），不自己决定。
import { $, $$, S, api, avaHTML, bus, curChar, esc, fail, fmtTime, modal, ripple, toast } from "./core.js";
import { listen, speak, stopSpeaking, sttAvailable } from "./voice.js";
import { renderDrawer, refreshAsks } from "./memory.js";

const GESTURES = [["wave", "挥手"], ["pat_head", "摸摸头"], ["high_five", "击掌"], ["poke", "戳一下"], ["cheer_up", "加油"]];
const ACTION_LABEL = { RESPOND: "回应", STORY: "幻想剧情", PERCEIVE: "看画面", NO_ACTION: "安静陪着", EMOTE: "表情", ANIMATE: "动作", REMEMBER: "提议记住" };

const C = {
  session: null, sessions: [], pending: false, voiceMode: false, listening: null, image: null,
  avatar: null, avatarFor: null, lastActivity: Date.now(), idleCount: 0, seen: new Set(), jobs: {},
};

// ---------- 3D 形象 ----------
// 角色切换和页面切换可能同时触发：串行执行，保证只有一个渲染器
let avatarQueue = Promise.resolve();
const ensureAvatar = () => (avatarQueue = avatarQueue.then(loadAvatar, loadAvatar));

async function loadAvatar() {
  const c = curChar();
  if (!c) return;
  if (!C.avatar) {
    try {
      const { createAvatar } = await import("./avatar.js");
      C.avatar = createAvatar($("#avatar-host"), { color: c.color, onStatus: avatarStatus });
    } catch (e) {
      avatarStatus({ state: "error", message: "3D 组件加载失败，已切换为平面立绘" });
      $("#avatar-host").innerHTML = '<div class="fallback-plate" data-mascot="stand"></div>';
      window.Mascot?.mount($("#avatar-host"));
      C.avatar = null;
      return;
    }
  }
  const key = c.id + ":" + (c.avatar_model_id || "default");
  if (C.avatarFor === key) return;
  C.avatarFor = key;
  const url = c.avatar_model_id ? await modelUrl(c.avatar_model_id) : "/static/assets/vrm/default.vrm";
  await C.avatar.load(url);
  C.avatar.setExpression(c.default_expression || "calm");
}

const urlCache = {};
async function modelUrl(id) {  // 自己上传的模型要带令牌下载，转成 blob URL 给加载器
  if (!urlCache[id]) {
    const res = await api(`/api/avatars/${id}/file`, { raw: true });
    urlCache[id] = URL.createObjectURL(await res.blob());
  }
  return urlCache[id];
}

function avatarStatus(s) {
  const el = $("#stage-status");
  const text = { loading: "LOADING MODEL", ready: s.kind === "vrm" ? "VRM · LIVE" : "BUILT-IN · LIVE" }[s.state] || s.message || s.state;
  el.textContent = s.state === "loading" && s.progress ? `LOADING ${Math.round(s.progress * 100)}%` : text;
  el.classList.toggle("err", s.state === "fallback" || s.state === "error");
  if (s.state === "fallback" || s.state === "error") { el.title = s.message || ""; toast(s.message || "3D 形象加载失败", 4000); }
}

function sayOnStage(text, story) {
  const el = $("#stage-say");
  if (!text) return el.classList.add("hidden");
  el.textContent = text.length > 120 ? text.slice(0, 118) + "…" : text;
  el.classList.toggle("story", !!story);
  el.classList.remove("hidden");
  clearTimeout(sayOnStage._t);
  sayOnStage._t = setTimeout(() => el.classList.add("hidden"), Math.min(14000, 3000 + text.length * 120));
}

// 执行后端给的行为
async function perform(actions, { speakIt = false } = {}) {
  const c = curChar();
  for (const a of actions || []) {
    if (a.type === "emote") C.avatar?.setExpression(a.expression);
    else if (a.type === "animate") C.avatar?.play(a.name).catch(() => {});
    else if (a.type === "perceive_request") toast("她想看看：点输入框左边的「图」发一张图片，或去眼镜模拟器打开摄像头", 5000);
    else if (a.type === "remember_suggest") rememberChip(a);
  }
  const say = (actions || []).find((a) => a.type === "say");
  if (!say) return;
  sayOnStage(say.text, say.story);
  if (speakIt || (C.voiceMode && S.me?.settings?.voice?.autoplay !== false)) {
    try {
      const r = await speak(say.text, c?.voice || {});
      if (r.audio) C.avatar?.attachAudio(r.audio); else C.avatar?.speaking(true);
      await r.done;
    } catch (e) { fail(e); }
    C.avatar?.speaking(false);
  } else {
    C.avatar?.speaking(true);
    setTimeout(() => C.avatar?.speaking(false), Math.min(6000, 600 + say.text.length * 90));
  }
}

function rememberChip(a) {
  const slot = $(`.mem-pill-slot:last-of-type`) || $("#messages");
  const div = document.createElement("div");
  div.className = "chip";
  div.innerHTML = `<b>REMEMBER</b>${esc(a.content.slice(0, 40))} <button class="small" data-ok>记下</button><button class="small ghost" data-no>不用</button>`;
  slot.appendChild(div);
  div.querySelector("[data-ok]").onclick = async () => {
    try { await api(`/api/memories/candidates/${a.candidate_id}/accept`, { body: {} }); toast("记下了"); div.remove(); refreshAsks(); } catch (e) { fail(e); }
  };
  div.querySelector("[data-no]").onclick = async () => {
    await api(`/api/memories/candidates/${a.candidate_id}`, { method: "DELETE" }).catch(() => {});
    div.remove(); refreshAsks();
  };
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

// ---------- 会话 ----------
async function loadSessions() {
  C.sessions = await api("/api/sessions?character_id=" + S.charId);
  const open = C.sessions.find((s) => !s.ended);
  C.session = open ? await api("/api/sessions/" + open.id) : null;
  renderSessionSelect();
  renderMessages();
}

function renderSessionSelect() {
  $("#session-select").innerHTML = '<option value="">— 历史会话 —</option>' + C.sessions.map((s) =>
    `<option value="${s.id}" ${C.session?.id === s.id ? "selected" : ""}>${s.ended ? "✓ " : "● "}${esc(s.title || "新会话")} · ${new Date(s.updated_at).toLocaleDateString()}</option>`).join("");
  $("#end-session").disabled = !C.session || C.session.ended;
}

async function newSession() {
  const s = await api("/api/sessions", { body: { character_id: S.charId } });
  C.session = { ...s, messages: [] };
  C.sessions.unshift(C.session);
  renderSessionSelect(); renderMessages();
  if (s.greeting) { sayOnStage(s.greeting); C.avatar?.play("wave").catch(() => {}); C.avatar?.setExpression("happy"); }
}

async function endSession(silent) {
  if (!C.session || C.session.ended) return;
  const r = await api(`/api/sessions/${C.session.id}/end`, { method: "POST" });
  if (r.summary?.title) toast("写下了这次的回忆：" + r.summary.title);
  else if (!silent) toast("会话已结束");
  await loadSessions();
}

// ---------- 消息 ----------
function renderMessages() {
  const box = $("#messages"), c = curChar();
  if (!C.session?.messages?.length) {
    box.innerHTML = c ? `<div class="empty"><div class="eyebrow mono">NEW SESSION</div>
      <div class="em-title">和 ${esc(c.name)} 打个招呼</div><div class="em-greet">${esc(c.tagline)}</div>
      <div class="muted small">${esc(c.name)} 是 AI 角色。</div></div>` : "";
    return;
  }
  box.innerHTML = C.session.messages.map(msgHTML).join("") + (C.pending ? typingHTML() : "");
  C.session.messages.forEach((m) => C.seen.add(m.id));
  bindMsgTools(box);
  box.scrollTop = box.scrollHeight;
}

const typingHTML = () => `<div class="typing">${avaHTML(curChar())}<div class="dots"><i></i><i></i><i></i></div><span class="lbl">${esc(curChar()?.name || "")} 正在想…</span></div>`;

function msgHTML(m) {
  const enter = C.seen.has(m.id) ? "" : " enter";
  if (m.role === "event") return `<div class="msg event${enter}">${esc(m.content)}</div>`;
  if (m.role === "user") {
    return `<div class="msg user${enter}" data-id="${m.id}"><div class="msg-col"><div class="who">${esc(S.me?.display_name || "你")}${m.meta?.image ? " · 图片" : ""}${m.meta?.source === "voice" ? " · 语音" : ""}</div>
      <div class="bubble">${esc(m.content)}</div>
      <div class="msg-tools"><button class="link" data-act="remember" data-id="${m.id}">记住这句</button></div></div></div>`;
  }
  const c = curChar(), meta = m.meta || {}, d = meta.decision;
  const story = (meta.actions || []).some((a) => a.type === "say" && a.story);
  const acts = d ? [d.primary.action, ...d.extras.map((x) => x.action)].filter((a) => a !== "RESPOND")
    .map((a) => `<span class="badge">${ACTION_LABEL[a] || a}</span>`).join("") : "";
  return `<div class="msg assistant${enter}" data-id="${m.id}" style="--c:${esc(c?.color || "")}">${avaHTML(c)}<div class="msg-col">
    <div class="who"><b>${esc(c?.name || "")}</b> · AI${story ? " · 虚构故事" : ""}</div>
    <div class="bubble${story ? " story" : ""}">${esc(m.content)}</div>
    ${acts ? `<div class="acts">${acts}</div>` : ""}
    <div class="mem-pill-slot" data-for="${m.id}">${memPillHTML(C.jobs[m.id])}</div>
    ${S.me?.dev ? devTraceHTML(m) : ""}</div></div>`;
}

function memPillHTML(job) {
  const r = job?.status === "done" ? job.result : null;
  if (!r) return "";
  const bits = [];
  if (r.created?.length) bits.push("记下了 " + r.created.map((x) => "「" + esc(x.title) + "」").join(""));
  if (r.updated?.length) bits.push("更新了 " + r.updated.map((x) => "「" + esc(x.title) + "」").join(""));
  if (r.pending?.length) bits.push(`有 ${r.pending.length} 件想问问你`);
  return bits.length ? `<button class="mem-pill" data-act="open-drawer" data-tab="${r.pending?.length && !r.created?.length ? "ask" : "mem"}">◇ ${bits.join(" · ")}</button>` : "";
}

// 开发者视图：这一轮策略的候选与打分、用到的记忆。不含模型的思考过程。
function devTraceHTML(m) {
  const d = m.meta?.decision;
  if (!d) return "";
  const cands = d.candidates.map((c) => `<li>${c.blocked ? "✗" : (c.id === d.primary.id || d.extras.some((x) => x.id === c.id)) ? "●" : "○"} ${esc(c.action)} ${esc(c.id)} · ${c.score}${c.blocked ? " — " + esc(c.blocked) : c.reason ? " — " + esc(c.reason) : ""}</li>`).join("");
  const recall = (m.meta.recall || []).map((u) => `<li>${esc(u.title)} <span class="muted">[${esc(u.section)}] ${esc((u.reasons || []).join("、"))}</span></li>`).join("");
  return `<details class="trace"><summary>◇ ${esc(d.label)}${d.experimental ? "（实验）" : ""} · ${d.latency_ms}ms${d.note ? " · " + esc(d.note) : ""}</summary>
    <ul>${cands}</ul>${recall ? `<div>用到的记忆：</div><ul>${recall}</ul>` : ""}
    ${m.meta.perception ? `<div>画面：${esc(m.meta.perception)}</div>` : ""}</details>`;
}

function bindMsgTools(root) {
  $$('[data-act="remember"]', root).forEach((b) => (b.onclick = () => {
    const m = C.session.messages.find((x) => x.id == b.dataset.id);
    bus.emit("memory:new", { content: m.content, source_message_id: m.id });
  }));
  $$('[data-act="open-drawer"]', root).forEach((b) => (b.onclick = () => openDrawer(b.dataset.tab)));
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
  text = text.trim();
  if (!text && !C.image) return;
  text ||= "你看看这个";
  activity();
  stopSpeaking();
  C.pending = true;
  $("#send-btn").disabled = true;
  try {
    if (!C.session || C.session.ended) await newSession();
    const image = C.image; clearImage();
    C.session.messages.push({ id: "tmp", role: "user", content: text, meta: { image: !!image, source } });
    renderMessages();
    if ($("#chat-input").value.trim() === text) $("#chat-input").value = "";
    C.avatar?.play("think").catch(() => {});
    const res = await api(`/api/sessions/${C.session.id}/stream`, { body: { text, image, source: source === "voice" ? "voice" : "app" }, raw: true });
    let live = null, done = null, error = null;
    for await (const [ev, data] of sse(res)) {
      if (ev === "decision" && data.actions[0] === "NO_ACTION") C.avatar?.play("idle").catch(() => {});
      if (ev === "delta") {
        if (!live) {
          C.pending = false; renderMessages();
          live = document.createElement("div");
          live.className = "msg assistant enter";
          live.innerHTML = `${avaHTML(curChar())}<div class="msg-col"><div class="who"><b>${esc(curChar()?.name)}</b> · AI</div><div class="bubble"></div></div>`;
          $("#messages").appendChild(live);
          C.avatar?.speaking(true);
        }
        live.querySelector(".bubble").textContent += data.text;
        $("#messages").scrollTop = $("#messages").scrollHeight;
      }
      if (ev === "done") done = data;
      if (ev === "error") error = data.message;
    }
    C.avatar?.speaking(false);
    if (error) throw new Error(error);
    C.session.messages.pop();
    C.pending = false;
    if (done.user) C.session.messages.push(done.user);
    if (done.reply) C.session.messages.push(done.reply);
    if (!C.session.title) { C.session.title = text.slice(0, 30); renderSessionSelect(); }
    renderMessages();
    if (!done.reply) toast("她安静地陪在你身边", 2000);
    perform(done.actions, { speakIt: source === "voice" });
    if (done.memory_job && done.reply) watchJob(done.memory_job, done.reply.id);
  } catch (e) {
    C.pending = false;
    if (C.session?.messages?.at(-1)?.id === "tmp") C.session.messages.pop();
    renderMessages();
    $("#chat-input").value = text;
    C.avatar?.setExpression("worried");
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

// ---------- 用户触发的互动 / 安静事件 ----------
async function sendEvent(body) {
  if (C.pending || !S.charId) return;
  if (!C.session || C.session.ended) await newSession();
  try {
    const r = await api(`/api/sessions/${C.session.id}/events`, { body });
    if (r.user) C.session.messages.push(r.user);
    if (r.reply) C.session.messages.push(r.reply);
    if (r.user || r.reply) renderMessages();
    perform(r.actions);
  } catch (e) { if (body.type !== "idle") fail(e); }
}

function activity() { C.lastActivity = Date.now(); C.idleCount = 0; }
setInterval(() => {  // 安静了一阵：交给互动策略决定要不要动一动（多数时候只是待机动作）
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
  $("#img-chip").innerHTML = `<img src="${C.image}" alt=""> 这张图会随下一句话发给她 <button class="link small" id="img-x">移除</button>`;
  $("#img-chip").classList.remove("hidden");
  $("#img-x").onclick = clearImage;
}

// ---------- 语音 ----------
async function setVoiceMode(on) {
  if (on) {
    const a = await sttAvailable();
    if (!a.ok) { toast(a.why, 5000); return; }
  }
  C.voiceMode = on;
  $$("#input-mode button").forEach((b) => b.classList.toggle("active", (b.dataset.input === "voice") === on));
  $("#mic-btn").classList.toggle("hidden", !on);
  $("#chat-input").placeholder = on ? "点「按住说话」开始说，再点一次发送；也可以直接打字" : "说点什么…（Enter 发送，Shift+Enter 换行）";
  if (!on) { C.listening?.cancel(); C.listening = null; stopSpeaking(); micIdle(); }
}
function micIdle() { const b = $("#mic-btn"); b.textContent = "按住说话"; b.classList.remove("listening", "on"); }
async function toggleMic() {
  const b = $("#mic-btn");
  if (C.listening) {
    const l = C.listening; C.listening = null; micIdle();
    try { const text = await l.stop(); if (text) send(text, { source: "voice" }); else toast("没听清，再说一次？"); } catch (e) { fail(e); }
    return;
  }
  stopSpeaking();
  try {
    C.listening = await listen({ onPartial: (t) => ($("#chat-input").value = t) });
    b.textContent = "说完了"; b.classList.add("listening", "on");
    C.avatar?.setExpression("focused");
  } catch (e) { C.listening = null; micIdle(); fail(e.name === "NotAllowedError" ? new Error("没有麦克风权限：请在浏览器地址栏允许麦克风") : e); }
}

// ---------- 侧栏 ----------
function openDrawer(tab) { $("#drawer").classList.remove("hidden"); renderDrawer($("#drawer-body"), tab); }
function closeDrawer() { $("#drawer").classList.add("hidden"); }

// ---------- 初始化 ----------
export function initChat() {
  $("#gestures").innerHTML = GESTURES.map(([id, label]) => `<button data-g="${id}" title="${label}">${label}</button>`).join("");
  $$("#gestures button").forEach((b) => (b.onclick = () => { activity(); ripple(b); sendEvent({ type: "gesture", gesture: b.dataset.g }); }));
  $("#chat-input").addEventListener("keydown", (e) => {
    activity();
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#chat-form").requestSubmit(); }
  });
  $("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); ripple($("#send-btn")); send($("#chat-input").value); });
  $("#session-select").onchange = async (e) => {
    if (!e.target.value) return;
    C.session = await api("/api/sessions/" + e.target.value).catch(fail);
    renderSessionSelect(); renderMessages();
  };
  $("#new-session").onclick = async () => {
    try { if (C.session && !C.session.ended && C.session.messages.length) await endSession(true); await newSession(); } catch (e) { fail(e); }
  };
  $("#end-session").onclick = () => endSession(false).catch(fail);
  $$("#input-mode button").forEach((b) => (b.onclick = () => setVoiceMode(b.dataset.input === "voice")));
  $("#mic-btn").onclick = toggleMic;
  $("#img-btn").onclick = () => $("#img-file").click();
  $("#img-file").onchange = (e) => { pickImage(e.target.files[0]); e.target.value = ""; };
  $("#drawer-toggle").onclick = () => ($("#drawer").classList.contains("hidden") ? openDrawer() : closeDrawer());
  $("#drawer-close").onclick = closeDrawer;
  $("#stage3d").addEventListener("pointermove", (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    C.avatar?.setLook(((e.clientX - r.left) / r.width) * 2 - 1, -(((e.clientY - r.top) / r.height) * 2 - 1));
  });
  bus.on("online", ({ ok, why }) => {
    $("#net-banner").textContent = ok ? "" : why || "连接断开";
    $("#net-banner").classList.toggle("hidden", ok);
    if (ok) toast("连接恢复了");
  });
  bus.on("character", async () => {
    const c = curChar();
    if (!c) return;
    $("#chat-avatar").innerHTML = avaHTML(c);
    $("#chat-name").textContent = c.name;
    $("#chat-tagline").textContent = c.tagline;
    C.jobs = {};
    await loadSessions().catch(fail);
    refreshAsks();
    if (!$("#drawer").classList.contains("hidden")) renderDrawer($("#drawer-body"));
    ensureAvatar().catch(fail);
  });
  bus.on("character:changed", () => { C.avatarFor = null; ensureAvatar().catch(fail); });
  bus.on("view", (v) => { if (v === "chat") { renderMessages(); ensureAvatar().catch(fail); } });
  bus.on("logout", () => { Object.assign(C, { session: null, sessions: [], pending: false, jobs: {} }); C.seen = new Set(); setVoiceMode(false); });
}

export const chatState = C;
