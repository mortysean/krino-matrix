// 03 记忆与关系：记忆页 + 聊天页右侧的“她记得的”侧栏。两处共用同一套列表和编辑弹窗。
import { $, $$, S, api, avaHTML, bus, confirmBox, curChar, download, esc, fail, fmtTime, modal, t, toast, tr } from "./core.js";

// 标签在用到时才翻译（语言在启动后才确定）
const TYPE_ZH = { fact: "关于你", preference: "偏好", event: "共同经历", commitment: "约定", summary: "会话回忆" };
const STATUS_ZH = { active: "在用", archived: "淡了", forgotten: "不再记住", superseded: "旧版本" };
const ASK_WHY_ZH = { sensitive: "比较私密", inferred: "她猜的", conflict: "和之前的不一样", suggested: "她想记下来" };
const TYPE = new Proxy(TYPE_ZH, { get: (o, k) => (k in o ? t(o[k]) : undefined) });
const STATUS = new Proxy(STATUS_ZH, { get: (o, k) => (k in o ? t(o[k]) : undefined) });
const ASK_WHY = new Proxy(ASK_WHY_ZH, { get: (o, k) => (k in o ? t(o[k]) : undefined) });
const you = (s) => String(s || "").replace(/^用户/, "你");  // 记忆按第三人称存，给用户看时换成“你”（英文记忆不受影响）
const realityBadge = (m) => {
  const cls = m.reality === "story" ? "story" : (m.origin === "inferred" || m.origin === "summary") ? "inferred" : "real";
  return `<span class="badge ${cls}" title="${t({ real: "现实里发生的事", story: "你们一起编的故事，不是现实", inferred: "模型推断的，不是你的原话" }[cls])}">${esc(tr(m.reality_label))}</span>`;
};

const M = { status: "active", type: "", q: "", reality: "" };

// ---------- 列表 ----------
function memCardHTML(m) {
  const tags = [`<span class="badge">${TYPE[m.type] || esc(m.type)}</span>`, realityBadge(m)];
  if (m.pinned) tags.push(`<span class="badge cobalt">${t("固定")}</span>`);
  if (m.supersedes) tags.push(`<span class="badge">${t("更正过")}</span>`);
  if (m.sensitive) tags.push(`<span class="badge warn">${t("私密")}</span>`);
  if (m.status !== "active") tags.push(`<span class="badge">${STATUS[m.status]}</span>`);
  const acts = m.status === "active"
    ? `<button class="link small" data-m="edit">${t("改")}</button>${m.type !== "summary" ? `<button class="link small" data-m="pin">${m.pinned ? t("取消固定") : t("固定")}</button><button class="link small" data-m="forget">${t("不再记住")}</button>` : ""}`
    : m.status === "superseded" ? "" : `<button class="link small" data-m="restore">${t("恢复")}</button>`;
  return `<div class="mem-card ${m.status}" data-id="${m.id}">
    <div class="mem-text" data-m="detail">${esc(m.type === "summary" ? m.title : you(m.content))}</div>
    <div class="mem-meta">${tags.join("")}${m.status_reason && m.status !== "active" ? `<span class="muted small">${esc(tr(m.status_reason))}</span>` : ""}</div>
    <div class="mem-acts">${acts}<button class="link small danger-link" data-m="delete">${t("删除")}</button></div></div>`;
}

async function renderList(box, opts, reload) {
  const p = new URLSearchParams({ character_id: S.charId, status: opts.status || "active" });
  if (opts.type) p.set("type", opts.type);
  if (opts.q) p.set("q", opts.q);
  let list = await api("/api/memories?" + p).catch((e) => (fail(e), []));
  if (opts.reality) list = list.filter((m) => (opts.reality === "inferred" ? m.origin === "inferred" || m.origin === "summary" : m.reality === opts.reality && !["inferred", "summary"].includes(m.origin)));
  box.innerHTML = list.length ? list.map(memCardHTML).join("")
    : `<p class="muted small">${opts.status === "active" ? t("还没有记下什么。你在聊天里明确说过的事，会在之后被记下来。") : t("这里是空的。")}</p>`;
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
        <p>${t("会一起删掉这条的所有版本，并清掉聊天记录里对应的原话。删除后她不会再想起，也不会被自动重新记下（除非你之后又亲口说起）。")}</p>
        <p class="muted small">${t("只是不想她再提的话，用“不再记住”就好，还能恢复。已经导出过的文件这里管不到。")}</p>`, "删除");
      if (!ok) return;
      const r = await api(`/api/memories/${m.id}`, { method: "DELETE" });
      toast(t("删掉了 {n} 条", { n: r.removed.memories }) + (r.removed.messages ? t("，清理了 {n} 条聊天", { n: r.removed.messages }) : ""));
    }
    reload();
  } catch (e) { fail(e); }
}

export function memoryEditor(init = {}) {
  const sens = S.me?.settings?.save_sensitive;
  const html = `
    <label>${t("内容")}<textarea name="content" rows="4">${esc(init.content || "")}</textarea></label>
    <div class="row">
      <label>${t("类型")} <select name="type">${Object.entries(TYPE).filter(([k]) => k !== "summary").map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></label>
      <label>${t("属于")} <select name="reality"><option value="real">${t("现实里的事")}</option><option value="story">${t("我们编的故事")}</option></select></label>
      <label>${t("重要度")} <select name="importance">${[1, 2, 3, 4, 5].map((i) => `<option>${i}</option>`).join("")}</select></label>
    </div>
    ${init.id ? "" : `<label class="inline"><input type="checkbox" name="sensitive" ${sens ? "" : "disabled"}> ${t("私密（只有在设置里允许后才会用于聊天）")}</label>`}
    ${init.id ? `<p class="muted small">${t("改了内容会存成新版本，旧的留在“旧版本”里可以对照。")}</p>` : ""}`;
  const p = modal(init.id ? "修改记忆" : "记下一件事", html, async (body) => {
    const v = (n) => $(`[name=${n}]`, body);
    const data = { content: v("content").value.trim(), type: v("type").value, reality: v("reality").value, importance: +v("importance").value };
    if (!data.content) throw new Error(t("内容不能为空"));
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
  const how = t({ stated: "你亲口说的", corrected: "你更正过", manual: "你自己写的", inferred: "她推测的，不是你的原话", imported: "导入的", summary: "会话结束时她写的回忆" }[d.origin] || d.origin);
  const src = d.sources.length ? d.sources.map((x) => `<li><q>${esc(d.evidence && x.content.includes(d.evidence) ? d.evidence : x.content)}</q> <span class="muted small">${fmtTime(x.at)}</span></li>`).join("")
    : `<li class="muted">${d.source_messages.includes("ui:edit") ? t("你在这里改过") : t("没有对应的聊天原话")}</li>`;
  const hist = d.history.length > 1 ? `<div class="section-title mono">HISTORY</div><ol class="hist">${d.history.map((h) =>
    `<li class="${h.id === d.id ? "cur" : ""}"><span class="badge">${STATUS[h.status]}</span> ${esc(you(h.content))} <span class="muted small">${fmtTime(h.created_at)}</span></li>`).join("")}</ol>` : "";
  await modal(TYPE[d.type] || "记忆", `<p class="detail-content">${esc(d.type === "summary" ? d.content : you(d.content))}</p>
    <div class="kv"><span>${t("属于")}</span><span>${realityBadge(d)}</span><span>${t("怎么来的")}</span><span>${esc(how)}</span>
      <span>${t("记下于")}</span><span>${fmtTime(d.created_at)}</span><span>${t("你最近提到")}</span><span>${fmtTime(d.last_confirmed)}</span>
      <span>${t("她最近想起")}</span><span>${fmtTime(d.last_recalled)}</span>${d.expires_at ? `<span>${t("到期")}</span><span>${fmtTime(d.expires_at)}</span>` : ""}</div>
    <div class="section-title mono">SOURCE</div><ul class="src">${src}</ul>${hist}`, null, { okText: "好", cancel: false });
  reload?.();
}

// ---------- 想问你的 ----------
export async function refreshAsks() {
  if (!S.charId) return [];
  const list = await api("/api/memories/candidates?character_id=" + S.charId).catch(() => []);
  $("#ask-count").textContent = list.length || "";
  $("#drawer-dot").classList.toggle("hidden", !list.length);
  return list;
}

async function renderAsks(box, reload) {
  const list = await refreshAsks();
  box.innerHTML = list.length ? list.map((c) => `<div class="mem-card ask" data-id="${c.id}">
      <div class="mem-text">${esc(you(c.content))}</div>
      <div class="mem-meta"><span class="badge warn">${ASK_WHY[c.reason] || c.reason}</span>${c.reality === "story" ? `<span class="badge story">${t("虚构故事")}</span>` : ""}${c.note ? `<span class="muted small">${esc(tr(c.note))}</span>` : ""}</div>
      ${c.evidence && c.basis !== "inferred" ? `<div class="muted small">${t("你说的：")}<q>${esc(c.evidence)}</q></div>` : ""}
      <div class="mem-acts"><button class="small" data-a="ok">${t("记住")}</button><button class="link small" data-a="edit">${t("改一下再记")}</button><button class="link small" data-a="no">${t("不用记")}</button></div>
    </div>`).join("") : `<p class="muted small">${t("没有要问你的。她推测的、比较私密的、和之前不一样的事，会先放在这里等你点头。")}</p>`;
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
      <div><div class="bond-stage">${esc(tr(b.stage))}</div><div class="muted small">${b.days ? t("认识第 {days} 天 · 见了 {sessions} 次 · 聊了 {turns} 句", b) : t("还没好好聊过")}</div></div></div>
    <div class="bond-steps">${b.stages.map((s, i) => `<span class="${i < b.stage_index ? "past" : i === b.stage_index ? "now" : ""}">${esc(tr(s.name))}</span>`).join("")}</div>
    <div class="track bond-track"><i style="width:${pct * 100}%"></i></div>
    <p class="muted small">${esc(tr(b.stage_hint))}</p>
    ${b.her_view ? `<div class="section-title mono">HER VIEW</div><p class="bond-view">“${esc(b.her_view)}”</p><button class="link small" data-b="view">${t("这不像她会想的，删掉")}</button>` : ""}
    <div class="section-title mono">NAME</div>
    <div class="row"><label class="inline small">${t("你叫她")} <input id="bond-nick" maxlength="24" value="${esc(b.user_calls_her || "")}" placeholder="${esc(c?.name)}"></label><button class="small ghost" data-b="nick">${t("改好了")}</button></div>
    ${b.milestones.length ? `<div class="section-title mono">MILESTONES</div><ul class="bond-ms">${b.milestones.map((m) => `<li><span class="mono small">${esc((m.at || "").slice(5, 10))}</span><span>${esc(m.text)}</span><button class="link small" data-ms="${esc(m.text)}">✕</button></li>`).join("")}</ul>` : ""}
    ${cur.topics.length || cur.mood_cues.length || cur.open_items.length ? `<div class="section-title mono">NOW · ${t("会过期")}</div><ul class="small">
      ${cur.topics.map((x) => `<li>${t("近期话题：")}${esc(x.text)}</li>`).join("")}${cur.mood_cues.map((x) => `<li>${t("情绪：")}${esc(x.text)}（${x.basis === "stated" ? t("你说的") : t("她推测的")}）</li>`).join("")}
      ${cur.open_items.map((x) => `<li>${t("没聊完：")}${esc(x.text)}</li>`).join("")}</ul>` : ""}
    <p class="muted small">${t("这些只属于你和她，会随相处慢慢变；她的人格设定不会因此改变。")}</p>
    <div class="row"><button class="ghost small" data-b="export">${t("导出我们的记忆")}</button><button class="danger small" data-b="reset">${t("从头认识")}</button></div>`;
  const patch = (body) => api(`/api/relations/${S.charId}/bond`, { method: "PATCH", body }).then(reload).catch(fail);
  $$("[data-b]", box).forEach((x) => (x.onclick = async () => {
    const k = x.dataset.b;
    if (k === "view") patch({ drop_view: true });
    if (k === "nick") patch({ user_calls_her: $("#bond-nick", box).value });
    if (k === "export") {
      const chats = await confirmBox("导出你们的记忆", `<p>${t("导出记忆和关系状态（JSON）。要不要连聊天原文一起导出？")}</p><p class='muted small'>${t("点“确定”包含聊天原文，点“取消”只导出记忆。")}</p>`, "包含聊天");
      download(`/api/relations/${S.charId}/export?chats=${!!chats}`, `${curChar()?.slug || "relation"}.relation.json`);
    }
    if (k === "reset" && await confirmBox("从头认识？", `<p>${t("亲近度、称呼、里程碑和她对你的看法都会清空。记忆和聊天记录不受影响。")}</p>`, "清空")) {
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
    box.innerHTML = `<input id="d-q" placeholder="${t("找一找…")}" value="${esc(M.dq || "")}"><div id="d-list" class="mem-list"></div><button id="d-add" class="ghost small">${t("自己写一条")}</button>`;
    renderList($("#d-list", box), { status: "active", q: M.dq }, reload);
    let timer; $("#d-q", box).oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => { M.dq = e.target.value.trim(); renderList($("#d-list", box), { status: "active", q: M.dq }, reload); }, 250); };
    $("#d-add", box).onclick = () => memoryEditor();
  } else if (drawerTab === "ask") {
    box.innerHTML = '<div class="mem-list"></div>'; renderAsks(box.firstChild, reload);
  } else {
    box.innerHTML = "<div></div>"; renderBond(box.firstChild, reload);
  }
}

export function initMemory() {
  bus.on("memory:new", (init) => memoryEditor(init));
  bus.on("memory:changed", () => {
    if (!$("#drawer").classList.contains("hidden")) renderDrawer($("#drawer-body"));
  });
  $$("#drawer-tabs button").forEach((b) => (b.onclick = () => renderDrawer($("#drawer-body"), b.dataset.dtab)));
}
