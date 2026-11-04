// 03 记忆与关系：记忆页 + 聊天页右侧的“她记得的”侧栏。两处共用同一套列表和编辑弹窗。
import { $, $$, S, api, avaHTML, bus, confirmBox, curChar, download, esc, fail, fmtTime, modal, toast } from "./core.js";

const TYPE = { fact: "关于你", preference: "偏好", event: "共同经历", commitment: "约定", summary: "会话回忆" };
const STATUS = { active: "在用", archived: "淡了", forgotten: "不再记住", superseded: "旧版本" };
const ASK_WHY = { sensitive: "比较私密", inferred: "她猜的", conflict: "和之前的不一样", suggested: "她想记下来" };
const you = (t) => String(t || "").replace(/^用户/, "你");
const realityBadge = (m) => {
  const cls = m.reality === "story" ? "story" : (m.origin === "inferred" || m.origin === "summary") ? "inferred" : "real";
  return `<span class="badge ${cls}" title="${{ real: "现实里发生的事", story: "你们一起编的故事，不是现实", inferred: "模型推断的，不是你的原话" }[cls]}">${esc(m.reality_label)}</span>`;
};

const M = { status: "active", type: "", q: "", reality: "" };

// ---------- 列表 ----------
function memCardHTML(m) {
  const tags = [`<span class="badge">${TYPE[m.type] || esc(m.type)}</span>`, realityBadge(m)];
  if (m.pinned) tags.push('<span class="badge cobalt">固定</span>');
  if (m.supersedes) tags.push('<span class="badge">更正过</span>');
  if (m.sensitive) tags.push('<span class="badge warn">私密</span>');
  if (m.status !== "active") tags.push(`<span class="badge">${STATUS[m.status]}</span>`);
  const acts = m.status === "active"
    ? `<button class="link small" data-m="edit">改</button>${m.type !== "summary" ? `<button class="link small" data-m="pin">${m.pinned ? "取消固定" : "固定"}</button><button class="link small" data-m="forget">不再记住</button>` : ""}`
    : m.status === "superseded" ? "" : '<button class="link small" data-m="restore">恢复</button>';
  return `<div class="mem-card ${m.status}" data-id="${m.id}">
    <div class="mem-text" data-m="detail">${esc(m.type === "summary" ? m.title : you(m.content))}</div>
    <div class="mem-meta">${tags.join("")}${m.status_reason && m.status !== "active" ? `<span class="muted small">${esc(m.status_reason)}</span>` : ""}</div>
    <div class="mem-acts">${acts}<button class="link small danger-link" data-m="delete">删除</button></div></div>`;
}

async function renderList(box, opts, reload) {
  const p = new URLSearchParams({ character_id: S.charId, status: opts.status || "active" });
  if (opts.type) p.set("type", opts.type);
  if (opts.q) p.set("q", opts.q);
  let list = await api("/api/memories?" + p).catch((e) => (fail(e), []));
  if (opts.reality) list = list.filter((m) => (opts.reality === "inferred" ? m.origin === "inferred" || m.origin === "summary" : m.reality === opts.reality && !["inferred", "summary"].includes(m.origin)));
  box.innerHTML = list.length ? list.map(memCardHTML).join("")
    : `<p class="muted small">${opts.status === "active" ? "还没有记下什么。你在聊天里明确说过的事，会在之后被记下来。" : "这里是空的。"}</p>`;
  $$("[data-m]", box).forEach((el) => (el.onclick = () => memAction(list.find((m) => m.id === el.closest(".mem-card").dataset.id), el.dataset.m, reload)));
}

async function memAction(m, act, reload) {
  try {
    if (act === "detail") return memDetail(m.id, reload);
    if (act === "edit") return memoryEditor(m).then(reload);
    if (act === "pin") { await api(`/api/memories/${m.id}`, { method: "PATCH", body: { pinned: !m.pinned } }); toast(m.pinned ? "取消固定" : "固定了，不会被淡忘"); }
    if (act === "forget") { await api(`/api/memories/${m.id}/forget`, { method: "POST" }); toast("好，她不会再提起这件事"); }
    if (act === "restore") { await api(`/api/memories/${m.id}/restore`, { method: "POST" }); toast("恢复了"); }
    if (act === "delete") {
      const ok = await confirmBox("彻底删除", `<p>「${esc(m.type === "summary" ? m.title : you(m.content))}」</p>
        <p>会一起删掉这条的所有版本，并清掉聊天记录里对应的原话。删除后她不会再想起，也不会被自动重新记下（除非你之后又亲口说起）。</p>
        <p class="muted small">只是不想她再提的话，用“不再记住”就好，还能恢复。已经导出过的文件这里管不到。</p>`, "删除");
      if (!ok) return;
      const r = await api(`/api/memories/${m.id}`, { method: "DELETE" });
      toast(`删掉了 ${r.removed.memories} 条` + (r.removed.messages ? `，清理了 ${r.removed.messages} 条聊天` : ""));
    }
    reload();
  } catch (e) { fail(e); }
}

export function memoryEditor(init = {}) {
  const sens = S.me?.settings?.save_sensitive;
  const html = `
    <label>内容<textarea name="content" rows="4">${esc(init.content || "")}</textarea></label>
    <div class="row">
      <label>类型 <select name="type">${Object.entries(TYPE).filter(([k]) => k !== "summary").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label>属于 <select name="reality"><option value="real">现实里的事</option><option value="story">我们编的故事</option></select></label>
      <label>重要度 <select name="importance">${[1, 2, 3, 4, 5].map((i) => `<option>${i}</option>`).join("")}</select></label>
    </div>
    ${init.id ? "" : `<label class="inline"><input type="checkbox" name="sensitive" ${sens ? "" : "disabled"}> 私密（只有在设置里允许后才会用于聊天）</label>`}
    ${init.id ? '<p class="muted small">改了内容会存成新版本，旧的留在“旧版本”里可以对照。</p>' : ""}`;
  const p = modal(init.id ? "修改记忆" : "记下一件事", html, async (body) => {
    const v = (n) => $(`[name=${n}]`, body);
    const data = { content: v("content").value.trim(), type: v("type").value, reality: v("reality").value, importance: +v("importance").value };
    if (!data.content) throw new Error("内容不能为空");
    if (init.id) await api(`/api/memories/${init.id}`, { method: "PATCH", body: data });
    else await api("/api/memories", { body: { ...data, character_id: S.charId, sensitive: !!v("sensitive")?.checked, source_message_id: init.source_message_id || null } });
    toast(init.id ? "改好了" : "记住了");
    bus.emit("memory:changed");
    return true;
  });
  const b = $("#modal-body");
  $("[name=type]", b).value = TYPE[init.type] && init.type !== "summary" ? init.type : "fact";
  $("[name=reality]", b).value = init.reality || "real";
  $("[name=importance]", b).value = String(init.importance || 3);
  return p;
}

async function memDetail(id, reload) {
  const d = await api(`/api/memories/${id}`).catch(fail);
  if (!d) return;
  const how = { stated: "你亲口说的", corrected: "你更正过", manual: "你自己写的", inferred: "她推测的，不是你的原话", imported: "导入的", summary: "会话结束时她写的回忆" }[d.origin] || d.origin;
  const src = d.sources.length ? d.sources.map((x) => `<li><q>${esc(d.evidence && x.content.includes(d.evidence) ? d.evidence : x.content)}</q> <span class="muted small">${fmtTime(x.at)}</span></li>`).join("")
    : `<li class="muted">${d.source_messages.includes("ui:edit") ? "你在这里改过" : "没有对应的聊天原话"}</li>`;
  const hist = d.history.length > 1 ? `<div class="section-title mono">HISTORY</div><ol class="hist">${d.history.map((h) =>
    `<li class="${h.id === d.id ? "cur" : ""}"><span class="badge">${STATUS[h.status]}</span> ${esc(you(h.content))} <span class="muted small">${fmtTime(h.created_at)}</span></li>`).join("")}</ol>` : "";
  await modal(TYPE[d.type] || "记忆", `<p class="detail-content">${esc(d.type === "summary" ? d.content : you(d.content))}</p>
    <div class="kv"><span>属于</span><span>${realityBadge(d)}</span><span>怎么来的</span><span>${esc(how)}</span>
      <span>记下于</span><span>${fmtTime(d.created_at)}</span><span>你最近提到</span><span>${fmtTime(d.last_confirmed)}</span>
      <span>她最近想起</span><span>${fmtTime(d.last_recalled)}</span>${d.expires_at ? `<span>到期</span><span>${fmtTime(d.expires_at)}</span>` : ""}</div>
    <div class="section-title mono">SOURCE</div><ul class="src">${src}</ul>${hist}`, null, { okText: "好", cancel: false });
  reload?.();
}

// ---------- 想问你的 ----------
export async function refreshAsks() {
  if (!S.charId) return [];
  const list = await api("/api/memories/candidates?character_id=" + S.charId).catch(() => []);
  $("#ask-count").textContent = list.length || "";
  $("#drawer-dot").classList.toggle("hidden", !list.length);
  $("#nav-ask-dot").classList.toggle("hidden", !list.length);
  return list;
}

async function renderAsks(box, reload) {
  const list = await refreshAsks();
  box.innerHTML = list.length ? list.map((c) => `<div class="mem-card ask" data-id="${c.id}">
      <div class="mem-text">${esc(you(c.content))}</div>
      <div class="mem-meta"><span class="badge warn">${ASK_WHY[c.reason] || c.reason}</span>${c.reality === "story" ? '<span class="badge story">虚构故事</span>' : ""}${c.note ? `<span class="muted small">${esc(c.note)}</span>` : ""}</div>
      ${c.evidence && c.basis !== "inferred" ? `<div class="muted small">你说的：<q>${esc(c.evidence)}</q></div>` : ""}
      <div class="mem-acts"><button class="small" data-a="ok">记住</button><button class="link small" data-a="edit">改一下再记</button><button class="link small" data-a="no">不用记</button></div>
    </div>`).join("") : '<p class="muted small">没有要问你的。她推测的、比较私密的、和之前不一样的事，会先放在这里等你点头。</p>';
  $$("[data-a]", box).forEach((b) => (b.onclick = async () => {
    const c = list.find((x) => x.id === b.closest(".mem-card").dataset.id);
    try {
      if (b.dataset.a === "no") { await api(`/api/memories/candidates/${c.id}`, { method: "DELETE" }); toast("好，不记"); }
      else {
        let content = null;
        if (b.dataset.a === "edit") {
          content = await modal("改一下再记", `<textarea name="c" rows="3">${esc(c.content)}</textarea>`, (body) => $("[name=c]", body).value);
          if (!content) return;
        }
        await api(`/api/memories/candidates/${c.id}/accept`, { body: { content } }); toast("记住了");
      }
      reload();
    } catch (e) { fail(e); }
  }));
}

// ---------- 关系 ----------
async function renderBond(box, reload) {
  const b = await api(`/api/relations/${S.charId}/bond`).catch(fail);
  if (!b) return;
  const c = curChar();
  const lo = b.stages[b.stage_index].at, hi = b.next_at ?? 100;
  const pct = Math.min(1, (b.closeness - lo) / Math.max(1, hi - lo));
  const cur = b.current;
  box.innerHTML = `<div class="bond-head" style="--c:${esc(c?.color)}">${avaHTML(c, "lg")}
      <div><div class="bond-stage">${esc(b.stage)}</div><div class="muted small">${b.days ? `认识第 ${b.days} 天 · 见了 ${b.sessions} 次 · 聊了 ${b.turns} 句` : "还没好好聊过"}</div></div></div>
    <div class="bond-steps">${b.stages.map((s, i) => `<span class="${i < b.stage_index ? "past" : i === b.stage_index ? "now" : ""}">${esc(s.name)}</span>`).join("")}</div>
    <div class="track bond-track"><i style="width:${pct * 100}%"></i></div>
    <p class="muted small">${esc(b.stage_hint)}</p>
    ${b.her_view ? `<div class="section-title mono">HER VIEW</div><p class="bond-view">“${esc(b.her_view)}”</p><button class="link small" data-b="view">这不像她会想的，删掉</button>` : ""}
    <div class="section-title mono">NAME</div>
    <div class="row"><label class="inline small">你叫她 <input id="bond-nick" maxlength="24" value="${esc(b.user_calls_her || "")}" placeholder="${esc(c?.name)}"></label><button class="small ghost" data-b="nick">改好了</button></div>
    ${b.milestones.length ? `<div class="section-title mono">MILESTONES</div><ul class="bond-ms">${b.milestones.map((m) => `<li><span class="mono small">${esc((m.at || "").slice(5, 10))}</span><span>${esc(m.text)}</span><button class="link small" data-ms="${esc(m.text)}">✕</button></li>`).join("")}</ul>` : ""}
    ${cur.topics.length || cur.mood_cues.length || cur.open_items.length ? `<div class="section-title mono">NOW · 会过期</div><ul class="small">
      ${cur.topics.map((x) => `<li>近期话题：${esc(x.text)}</li>`).join("")}${cur.mood_cues.map((x) => `<li>情绪：${esc(x.text)}（${x.basis === "stated" ? "你说的" : "她推测的"}）</li>`).join("")}
      ${cur.open_items.map((x) => `<li>没聊完：${esc(x.text)}</li>`).join("")}</ul>` : ""}
    <p class="muted small">这些只属于你和她，会随相处慢慢变；她的人格设定不会因此改变。</p>
    <div class="row"><button class="ghost small" data-b="export">导出我们的记忆</button><button class="danger small" data-b="reset">从头认识</button></div>`;
  const patch = (body) => api(`/api/relations/${S.charId}/bond`, { method: "PATCH", body }).then(reload).catch(fail);
  $$("[data-b]", box).forEach((x) => (x.onclick = async () => {
    const k = x.dataset.b;
    if (k === "view") patch({ drop_view: true });
    if (k === "nick") patch({ user_calls_her: $("#bond-nick", box).value });
    if (k === "export") {
      const chats = await confirmBox("导出你们的记忆", "<p>导出记忆和关系状态（JSON）。要不要连聊天原文一起导出？</p><p class='muted small'>点“确定”包含聊天原文，点“取消”只导出记忆。</p>", "包含聊天");
      download(`/api/relations/${S.charId}/export?chats=${!!chats}`, `${curChar()?.slug || "relation"}.relation.json`);
    }
    if (k === "reset" && await confirmBox("从头认识？", "<p>亲近度、称呼、里程碑和她对你的看法都会清空。记忆和聊天记录不受影响。</p>", "清空")) {
      await api(`/api/relations/${S.charId}/bond`, { method: "DELETE" }).catch(fail); reload();
    }
  }));
  $$("[data-ms]", box).forEach((x) => (x.onclick = () => patch({ drop_milestone: x.dataset.ms })));
}

// ---------- 聊天页侧栏 ----------
let drawerTab = "mem";
export function renderDrawer(box, tab) {
  if (tab) drawerTab = tab;
  $$("#drawer-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.dtab === drawerTab));
  const reload = () => renderDrawer(box);
  if (drawerTab === "mem") {
    box.innerHTML = `<input id="d-q" placeholder="找一找…" value="${esc(M.dq || "")}"><div id="d-list" class="mem-list"></div><button id="d-add" class="ghost small">自己写一条</button>`;
    renderList($("#d-list", box), { status: "active", q: M.dq }, reload);
    let t; $("#d-q", box).oninput = (e) => { clearTimeout(t); t = setTimeout(() => { M.dq = e.target.value.trim(); renderList($("#d-list", box), { status: "active", q: M.dq }, reload); }, 250); };
    $("#d-add", box).onclick = () => memoryEditor();
  } else if (drawerTab === "ask") {
    box.innerHTML = '<div class="mem-list"></div>'; renderAsks(box.firstChild, reload);
  } else {
    box.innerHTML = "<div></div>"; renderBond(box.firstChild, reload);
  }
}

// ---------- 记忆页 ----------
export async function memoryPage() {
  const root = $("#memory-page");
  root.innerHTML = `<div class="mem-layout"><div>
      <div class="toolbar">
        <input id="m-q" placeholder="搜索记忆…" value="${esc(M.q)}" style="flex:1;min-width:160px">
        <select id="m-status">${["active", "archived", "forgotten", "superseded", "all"].map((s) => `<option value="${s}" ${M.status === s ? "selected" : ""}>${{ ...STATUS, all: "全部状态" }[s]}</option>`).join("")}</select>
        <select id="m-type"><option value="">全部类型</option>${Object.entries(TYPE).map(([k, v]) => `<option value="${k}" ${M.type === k ? "selected" : ""}>${v}</option>`).join("")}</select>
        <select id="m-real"><option value="">现实 / 推断 / 虚构</option><option value="real" ${M.reality === "real" ? "selected" : ""}>只看现实事件</option><option value="inferred" ${M.reality === "inferred" ? "selected" : ""}>只看模型推断</option><option value="story" ${M.reality === "story" ? "selected" : ""}>只看虚构故事</option></select>
        <button id="m-add">记下一件事</button>
      </div>
      <div id="m-list" class="mem-list"></div></div>
    <div><div class="panel"><div class="section-title mono">ASK · 想问你的</div><div id="m-ask" class="mem-list"></div></div>
      <div class="panel" style="margin-top:14px"><div class="section-title mono">BOND · 你们</div><div id="m-bond"></div></div></div></div>`;
  const reload = () => memoryPage();
  const list = () => renderList($("#m-list"), M, () => list());
  list();
  renderAsks($("#m-ask"), reload);
  renderBond($("#m-bond"), reload);
  let t; $("#m-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { M.q = e.target.value.trim(); list(); }, 250); };
  $("#m-status").onchange = (e) => { M.status = e.target.value; list(); };
  $("#m-type").onchange = (e) => { M.type = e.target.value; list(); };
  $("#m-real").onchange = (e) => { M.reality = e.target.value; list(); };
  $("#m-add").onclick = () => memoryEditor();
}

export function initMemory() {
  bus.on("memory:new", (init) => memoryEditor(init));
  bus.on("memory:changed", () => {
    if (S.view === "memory") memoryPage();
    if (!$("#drawer").classList.contains("hidden")) renderDrawer($("#drawer-body"));
  });
  $$("#drawer-tabs button").forEach((b) => (b.onclick = () => renderDrawer($("#drawer-body"), b.dataset.dtab)));
}
