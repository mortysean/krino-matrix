// 03 工坊：一个网格。卡片上直接“领养”（一键导入成自己的角色并去聊天），点卡片看详情。
// 发布在“角色 → 更多 → 发布到工坊”，或者这里右上角“上传”。管理员多一个“审核”入口。
import { $, $$, S, api, bus, confirmBox, download, esc, fail, fmtTime, modal, t, toast, tr } from "./core.js";

const W = { q: "", category: "", sort: "hot", page: 1, items: [], meta: null, mine: false };

const meta = async () => (W.meta ||= await api("/api/workshop/meta"));
const cover = (i) => `<div class="ws-cover" style="--c:${esc(i.color)}"><span>${esc([...(i.title || "?")][0])}</span><i class="mono">${esc(tr(i.category_label))}</i></div>`;

function cardHTML(i, k = 0) {
  const btn = i.installed ? `<button class="small ghost" data-chat="${i.installed.character_id}">${t("去聊天")}</button>`
    : i.own ? `<span class="muted small">${t("我发布的")}</span>` : `<button class="small" data-adopt="${i.id}">${t("领养")}</button>`;
  return `<div class="ws-card" data-id="${i.id}" style="animation-delay:${k * 25}ms">${cover(i)}
    <div class="ws-info"><h3>${esc(i.title)}</h3><p class="muted small">${esc(i.tagline)}</p>
      <div class="ws-foot"><span class="muted small">${esc(tr(i.author))} · ↓${i.installs}${i.status !== "published" ? " · " + esc(tr(i.status_label)) : ""}</span>${btn}</div></div></div>`;
}

export async function workshopPage() {
  const m = await meta();
  const root = $("#ws-page");
  root.innerHTML = `<div class="ws-bar">
      <input id="ws-q" placeholder="${t("搜索角色…")}" value="${esc(W.q)}">
      <div class="chips">${[["hot", "最热"], ["new", "最新"], ["top", "好评"]].map(([k, v]) => `<button data-sort="${k}" class="${W.sort === k ? "active" : ""}">${t(v)}</button>`).join("")}</div>
      <label class="ghost-btn small">${t("上传")}<input type="file" id="ws-up" accept=".json,.md,.png,.charx,.zip" hidden></label>
      <button class="link small" id="ws-mine">${W.mine ? t("← 全部") : t("我发布的")}</button>
      ${m.admin ? `<button class="link small" id="ws-review">${t("审核")}</button>` : ""}
    </div>
    <div class="chips ws-tags">${[["", "全部"], ...Object.entries(m.categories)].map(([k, v]) => `<button data-cat="${k}" class="${W.category === k ? "active" : ""}">${esc(tr(v))}</button>`).join("")}</div>
    <div id="ws-grid" class="ws-grid"></div><div class="row"><button id="ws-more" class="ghost small hidden">${t("再看看")}</button></div>`;
  let timer; $("#ws-q").oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => { W.q = e.target.value.trim(); load(); }, 300); };
  $$("[data-sort]").forEach((b) => (b.onclick = () => { W.sort = b.dataset.sort; workshopPage(); }));
  $$("[data-cat]").forEach((b) => (b.onclick = () => { W.category = b.dataset.cat; workshopPage(); }));
  $("#ws-mine").onclick = () => { W.mine = !W.mine; workshopPage(); };
  $("#ws-more").onclick = () => { W.page += 1; load(true); };
  $("#ws-up").onchange = (e) => upload(e.target.files[0]);
  if ($("#ws-review")) $("#ws-review").onclick = review;
  load();
}

async function load(append = false) {
  if (!append) W.page = 1;
  const p = new URLSearchParams({ q: W.q, category: W.category, sort: W.sort, page: W.page, mine: W.mine });
  const r = await api("/api/workshop/items?" + p).catch((e) => (fail(e), { items: [], more: false }));
  W.items = append ? W.items.concat(r.items) : r.items;
  $("#ws-grid").innerHTML = W.items.length ? W.items.map(cardHTML).join("") : `<p class="muted ws-empty">${W.mine ? t("你还没有发布过角色。在“角色 → 更多”里可以发布。") : t("没有找到。换个词试试？")}</p>`;
  $("#ws-more").classList.toggle("hidden", !r.more);
  bind($("#ws-grid"));
}

function bind(root) {
  $$(".ws-card", root).forEach((el) => (el.onclick = (e) => { if (!e.target.closest("button")) open(el.dataset.id); }));
  $$("[data-adopt]", root).forEach((b) => (b.onclick = () => adopt(b.dataset.adopt, b)));
  $$("[data-chat]", root).forEach((b) => (b.onclick = () => bus.emit("select", { id: b.dataset.chat, view: "chat" })));
}

// 领养 = 导入 + 切到她 + 去聊天，一次点击完成
async function adopt(id, btn) {
  if (btn) btn.disabled = true;
  try {
    const c = await api(`/api/workshop/items/${id}/install`, { method: "POST" });
    S.chars = await api("/api/characters"); bus.emit("chars");
    toast(t("{name} 来了", { name: c.name }));
    $("#modal").classList.add("hidden");
    bus.emit("select", { id: c.id, view: "chat" });
  } catch (e) { fail(e); if (btn) btn.disabled = false; }
}

async function open(id) {
  const d = await api(`/api/workshop/items/${id}`).catch(fail);
  if (!d) return;
  const p = d.preview.persona;
  const sec = (k, label) => (p[k] ? `<div class="section-title mono">${t(label)}</div><div class="small pre">${esc(p[k])}</div>` : "");
  modal(d.title, `<div class="ws-detail-head">${cover(d)}<div>
      <p>${esc(d.tagline)}</p>
      <p class="small muted">${esc(tr(d.author))} · v${d.version} · ${t("导入 {n}", { n: d.installs })} · ${d.rating == null ? t("还没人评分") : t("{n}% 好评", { n: Math.round(d.rating * 100) })}</p>
      <div class="row">${d.installed ? `<button data-chat="${d.installed.character_id}">${t("去聊天")}</button>${d.installed.update ? `<button class="ghost" data-w="update">${t("更新到新版")}</button>` : ""}`
        : d.own ? "" : `<button data-adopt="${d.id}">${t("领养")}</button>`}
        ${d.own ? "" : `<button class="vote ${d.my_vote === 1 ? "on" : ""}" data-v="1">👍 ${d.up}</button>`}</div></div></div>
    ${p.greeting ? `<p><q>${esc(p.greeting)}</q></p>` : ""}
    <div class="ws-body">${sec("background", "背景")}${sec("personality", "性格")}${sec("speech", "说话方式")}${sec("worldview", "世界观")}</div>
    <details><summary class="small muted">${t("评论（{n}）· 更多", { n: d.comments.length })}</summary>
      <div class="ws-cform"><textarea id="ws-c" rows="2" maxlength="1000" placeholder="${t("说点什么…")}"></textarea><button class="small" data-w="comment">${t("发表")}</button></div>
      ${d.comments.map((c) => `<div class="ws-c"><b class="small">${esc(c.author)}</b> <span class="muted small">${fmtTime(c.at)}</span>
        ${c.own || d.admin ? `<button class="link small" data-cdel="${c.id}">${t("删除")}</button>` : ""}<p>${esc(c.body)}</p></div>`).join("")}
      <div class="row"><button class="link small" data-w="download">${t("下载人设包")}</button>
        ${d.own ? `<button class="link small danger-link" data-w="withdraw">${t("撤下")}</button>` : `<button class="link small" data-w="report">${t("举报")}</button>`}
        ${d.admin ? ["published", "hidden", "removed"].filter((s) => s !== d.status).map((s) => `<button class="link small" data-mod="${s}">${t({ published: "上架", hidden: "隐藏", removed: "下架" }[s])}</button>`).join("") : ""}</div>
    </details>`, null, { okText: "关闭", cancel: false, wide: true }).then(() => load());
  const body = $("#modal-body"), reopen = () => open(id), run = (pr) => pr.then(reopen).catch(fail);
  bind(body);
  const acts = {
    update: async () => {
      let r = await api(`/api/workshop/items/${id}/update`, { method: "POST" });
      if (r.conflict && await confirmBox("你改过她", `<p>${esc(tr(r.reason))}</p>`, "仍然更新")) r = await api(`/api/workshop/items/${id}/update?force=true`, { method: "POST" });
      if (r.updated) { toast(t("更新到 v{n}", { n: r.version })); bus.emit("character:changed"); }
    },
    download: async () => download(`/api/workshop/items/${id}/download`, `${d.title}.krino.json`),
    withdraw: async () => { if (await confirmBox("撤下作品", `<p>${t("撤下后别人就看不到了；已经领养的人不受影响。")}</p>`, "撤下")) await api(`/api/workshop/items/${id}`, { method: "DELETE" }); },
    comment: async () => { const text = $("#ws-c", body).value.trim(); if (text) await api(`/api/workshop/items/${id}/comments`, { body: { body: text } }); },
    report: async () => {
      const m = await meta();
      const reason = await modal("举报", `<select id="rep-r">${Object.entries(m.reasons).map(([k, v]) => `<option value="${k}">${esc(tr(v))}</option>`).join("")}</select>`,
        (b) => $("#rep-r", b).value, { okText: "提交" });
      if (reason) { await api(`/api/workshop/items/${id}/report`, { body: { reason } }); toast("收到了，管理员会处理"); }
    },
  };
  $$("[data-w]", body).forEach((b) => (b.onclick = () => run(acts[b.dataset.w]())));
  $$("[data-v]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/items/${id}/vote`, { body: { value: d.my_vote === 1 ? 0 : 1 } }))));
  $$("[data-cdel]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/comments/${b.dataset.cdel}`, { method: "DELETE" }))));
  $$("[data-mod]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/items/${id}/moderate`, { body: { status: b.dataset.mod } }))));
}

// 发布：从“角色 → 更多”进来，只问一个分类
export async function publish(characterId) {
  const m = await meta();
  const c = S.chars.find((x) => x.id === characterId);
  const ok = await modal(t("发布「{name}」到工坊", { name: c?.name }), `<label>${t("分类")}<select id="pub-cat">${Object.entries(m.categories).map(([k, v]) => `<option value="${k}">${esc(tr(v))}</option>`).join("")}</select></label>
    <p class="muted small">${t("只发布人格设定，你们的记忆和聊天不会公开。和工坊里已有角色一模一样的内容发布不了。")}</p>`,
    async (b) => api("/api/workshop/publish", { body: { character_id: characterId, category: $("#pub-cat", b).value } }), { okText: "发布" });
  if (ok) { toast(t("发布了「{name}」", { name: ok.title })); W.mine = true; bus.emit("goto", "workshop"); }
}

async function upload(file) {
  if (!file) return;
  const fd = new FormData(); fd.append("file", file); fd.append("category", "other");
  try { const it = await api("/api/workshop/upload", { body: fd }); toast(t("发布了「{name}」", { name: it.title })); W.mine = true; workshopPage(); }
  catch (e) { fail(e); }
}

async function review() {
  const r = await api("/api/workshop/reports").catch(fail);
  if (!r) return;
  modal("审核", `${r.pending.length ? `<div class="section-title mono">${t("待审核")}</div><div class="ws-grid">${r.pending.map(cardHTML).join("")}</div>` : ""}
    <div class="section-title mono">${t("举报")}</div>
    ${r.reports.map((x) => `<div class="mem-card ask"><div>${esc(x.title)}${x.comment_id ? t("（评论）") : ""} <span class="badge warn">${esc(tr(x.reason))}</span></div>
      ${x.detail ? `<div class="muted small">${esc(x.detail)}</div>` : ""}
      <div class="row"><button class="small" data-rs="${x.id}" data-a="dismiss">${t("驳回")}</button><button class="small ghost" data-rs="${x.id}" data-a="hide">${t("隐藏")}</button><button class="small danger" data-rs="${x.id}" data-a="remove">${t("下架")}</button></div></div>`).join("") || `<p class="muted small">${t("没有待处理的举报。")}</p>`}`,
    null, { okText: "关闭", cancel: false, wide: true });
  bind($("#modal-body"));
  $$("[data-rs]", $("#modal-body")).forEach((b) => (b.onclick = () => api(`/api/workshop/reports/${b.dataset.rs}`, { body: { action: b.dataset.a } }).then(review).catch(fail)));
}

export function initWorkshop() { bus.on("publish", publish); }
