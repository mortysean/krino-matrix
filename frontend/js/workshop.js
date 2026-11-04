// 04 创意工坊：浏览 / 搜索 / 分类、详情预览、导入、下载、发布（选自己的角色或直接上传文件）、评分评论、举报、审核。
import { $, $$, S, api, bus, confirmBox, download, esc, fail, fmtTime, modal, toast } from "./core.js";

const W = { tab: "browse", q: "", category: "", tag: "", sort: "new", page: 1, items: [], meta: null };

async function meta() {
  if (!W.meta) W.meta = await api("/api/workshop/meta");
  $("#ws-review-tab").classList.toggle("hidden", !W.meta.admin);
  return W.meta;
}

const cover = (i) => `<div class="ws-cover" style="--c:${esc(i.color)}"><span>${esc([...(i.title || "?")][0])}</span><i class="mono">${esc(i.category_label)}</i></div>`;
const rating = (i) => (i.rating == null ? '<span class="muted">还没人评分</span>' : `${Math.round(i.rating * 100)}% 好评`);

function cardHTML(i, k = 0) {
  return `<div class="ws-card ${i.status !== "published" ? "dim" : ""}" data-id="${i.id}" style="animation-delay:${k * 30}ms">${cover(i)}
    <div class="ws-info"><h3>${esc(i.title)} <span class="ai-badge">AI</span></h3><p class="muted small">${esc(i.tagline)}</p>
      <div class="ws-meta small"><span>${esc(i.author)}</span><span class="mono">v${i.version}</span>${i.status !== "published" ? `<span class="badge warn">${esc(i.status_label)}</span>` : ""}${i.installed ? '<span class="badge cobalt">已导入</span>' : ""}</div>
      <div class="ws-stats small mono"><span>↓ ${i.installs}</span><span>${rating(i)}</span><span>💬 ${i.comments}</span></div></div></div>`;
}

async function browse(append = false) {
  const m = await meta();
  if (!append) W.page = 1;
  const p = new URLSearchParams({ q: W.q, category: W.category, tag: W.tag, sort: W.sort, page: W.page });
  const r = await api("/api/workshop/items?" + p).catch((e) => (fail(e), { items: [], tags: [], more: false }));
  W.items = append ? W.items.concat(r.items) : r.items;
  const body = $("#ws-body");
  if (!append) {
    body.innerHTML = `<div class="ws-bar"><input id="ws-q" placeholder="搜索角色、简介、标签…" value="${esc(W.q)}">
        <div class="chips" id="ws-sort">${[["new", "最新"], ["hot", "最热"], ["top", "好评"], ["installs", "导入最多"]].map(([k, v]) => `<button data-sort="${k}" class="${W.sort === k ? "active" : ""}">${v}</button>`).join("")}</div></div>
      <div class="chips ws-tags">${[["", "全部分类"], ...Object.entries(m.categories)].map(([k, v]) => `<button data-cat="${k}" class="${W.category === k ? "active" : ""}">${esc(v)}</button>`).join("")}</div>
      <div class="chips ws-tags">${r.tags.map((t) => `<button data-tag="${esc(t.tag)}" class="${W.tag === t.tag ? "active" : ""}">#${esc(t.tag)}</button>`).join("")}</div>
      <div id="ws-grid" class="ws-grid"></div><div class="row"><button id="ws-more" class="ghost small hidden">再看看</button></div>`;
    let t; $("#ws-q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { W.q = e.target.value.trim(); browse(); }, 300); };
    $$("[data-sort]").forEach((b) => (b.onclick = () => { W.sort = b.dataset.sort; browse(); }));
    $$("[data-cat]").forEach((b) => (b.onclick = () => { W.category = b.dataset.cat; browse(); }));
    $$("[data-tag]").forEach((b) => (b.onclick = () => { W.tag = W.tag === b.dataset.tag ? "" : b.dataset.tag; browse(); }));
    $("#ws-more").onclick = () => { W.page += 1; browse(true); };
  }
  $("#ws-grid").innerHTML = W.items.length ? W.items.map(cardHTML).join("") : '<p class="muted ws-empty">还没有符合条件的角色。去“发布”分享第一个吧。</p>';
  $("#ws-more").classList.toggle("hidden", !r.more);
  $$("#ws-grid .ws-card").forEach((el) => (el.onclick = () => open(el.dataset.id)));
}

async function open(id) {
  const d = await api(`/api/workshop/items/${id}`).catch(fail);
  if (!d) return;
  const p = d.preview.persona;
  const sec = (k, label) => (p[k] ? `<div class="section-title mono">${label}</div><div class="small" style="white-space:pre-wrap">${esc(p[k])}</div>` : "");
  const html = `<div class="ws-detail-head">${cover(d)}<div>
      <p class="muted">${esc(d.tagline)}</p>
      <div class="chips">${d.tags.map((t) => `<span class="badge">${esc(t)}</span>`).join("")}<span class="badge">${esc(d.category_label)}</span><span class="badge">${esc(d.preview.style || "")}</span></div>
      <p class="small muted">作者 ${esc(d.author)} · v${d.version} · ${fmtTime(d.updated_at)} · 导入 ${d.installs} · ${rating(d)}</p>
      ${d.status !== "published" ? `<p class="small error">${esc(d.status_label)}${d.status_note ? "：" + esc(d.status_note) : ""}</p>` : ""}</div></div>
    ${d.description ? `<p style="white-space:pre-wrap">${esc(d.description)}</p>` : ""}
    <div class="ws-actions">
      ${d.installed ? `<button class="small" data-w="use">和她互动</button>${d.installed.update ? '<button class="small" data-w="update">更新到最新版</button>' : ""}`
        : d.status === "published" || d.own ? '<button class="small" data-w="install">导入到我的角色</button>' : ""}
      <button class="ghost small" data-w="download">下载人设包</button>
      ${d.own ? "" : `<button class="vote ${d.my_vote === 1 ? "on" : ""}" data-v="1">👍 ${d.up}</button><button class="vote ${d.my_vote === -1 ? "on" : ""}" data-v="-1">👎 ${d.down}</button>`}
      <span class="grow"></span>
      ${d.own ? '<button class="link small danger-link" data-w="withdraw">撤下</button>' : '<button class="link small" data-w="report">举报</button>'}
      ${d.admin ? ["published", "hidden", "removed"].filter((s) => s !== d.status).map((s) => `<button class="ghost small" data-mod="${s}">${{ published: "上架", hidden: "隐藏", removed: "下架" }[s]}</button>`).join("") : ""}
    </div>
    <div class="ws-body">${p.greeting ? `<p><q>${esc(p.greeting)}</q></p>` : ""}${sec("background", "BACKGROUND · 背景")}${sec("personality", "PERSONALITY · 性格")}${sec("speech", "SPEECH · 语言风格")}${sec("interests", "INTERESTS · 兴趣")}${sec("worldview", "WORLD · 世界观")}
      ${d.preview.lore.length ? `<div class="section-title mono">LORE</div><div class="small">${esc(d.preview.lore.join("、"))}</div>` : ""}</div>
    <p class="muted small">人设包只包含人格配置，不含任何人的私人记忆。导入后是你自己的一份，你们的记忆作者看不到。</p>
    <div class="section-title mono">VERSIONS</div><ul class="ws-log">${d.versions.map((v) => `<li><b class="mono">v${v.version}</b> <span class="muted small">${fmtTime(v.at)}</span> ${esc(v.changelog || "")}</li>`).join("")}</ul>
    <div class="section-title mono">COMMENTS</div>
    <div class="ws-cform"><textarea id="ws-c" rows="2" maxlength="1000" placeholder="说点什么…"></textarea><button class="small" data-w="comment">发表</button></div>
    ${d.comments.map((c) => `<div class="ws-c"><div><b class="small">${esc(c.author)}</b><span class="muted small">${fmtTime(c.at)}</span>
      ${c.own || d.admin ? `<button class="link small" data-cdel="${c.id}">删除</button>` : `<button class="link small" data-crep="${c.id}">举报</button>`}</div><p>${esc(c.body)}</p></div>`).join("") || '<p class="muted small">还没有评论。</p>'}`;
  modal(d.title, html, null, { okText: "关闭", cancel: false, wide: true }).then(() => { if (W.tab === "browse") browse(); });
  const body = $("#modal-body"), reopen = () => open(id), run = (p) => p.then(reopen).catch(fail);
  const acts = {
    install: async () => { const c = await api(`/api/workshop/items/${id}/install`, { method: "POST" }); S.chars = await api("/api/characters"); bus.emit("chars"); toast(`${c.name} 来到了你的角色里`); },
    update: async () => {
      let r = await api(`/api/workshop/items/${id}/update`, { method: "POST" });
      if (r.conflict && await confirmBox("本地改过", `<p>${esc(r.reason)}</p>`, "仍然更新")) r = await api(`/api/workshop/items/${id}/update?force=true`, { method: "POST" });
      if (r.updated) { toast("更新到 v" + r.version); bus.emit("character:changed"); }
    },
    use: async () => { $("#modal").classList.add("hidden"); bus.emit("select", { id: d.installed.character_id, view: "chat" }); throw null; },
    download: async () => download(`/api/workshop/items/${id}/download`, `${d.title}.krino.json`),
    withdraw: async () => { if (await confirmBox("撤下作品", "<p>撤下后别人就看不到了；已经导入的人不受影响。</p>", "撤下")) await api(`/api/workshop/items/${id}`, { method: "DELETE" }); },
    comment: async () => { const t = $("#ws-c", body).value.trim(); if (t) await api(`/api/workshop/items/${id}/comments`, { body: { body: t } }); },
    report: async () => report(id),
  };
  $$("[data-w]", body).forEach((b) => (b.onclick = () => run(acts[b.dataset.w]()).catch(() => {})));
  $$("[data-v]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/items/${id}/vote`, { body: { value: d.my_vote === +b.dataset.v ? 0 : +b.dataset.v } }))));
  $$("[data-cdel]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/comments/${b.dataset.cdel}`, { method: "DELETE" }))));
  $$("[data-crep]", body).forEach((b) => (b.onclick = () => run(report(id, b.dataset.crep))));
  $$("[data-mod]", body).forEach((b) => (b.onclick = () => run(api(`/api/workshop/items/${id}/moderate`, { body: { status: b.dataset.mod } }))));
}

async function report(id, commentId = null) {
  const m = await meta();
  const card = $("#modal .modal-card"), prev = $("#modal-body").innerHTML;
  // 在详情弹窗里叠一个小表单，不另开弹窗
  return new Promise((resolve) => {
    $("#modal-body").innerHTML = `<p>举报${commentId ? "这条评论" : "这个作品"}</p>
      <label>原因<select id="rep-r">${Object.entries(m.reasons).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
      <label>补充说明（可选）<textarea id="rep-d" rows="3" maxlength="500"></textarea></label>
      <div class="row right"><button class="ghost small" id="rep-x">算了</button><button class="small" id="rep-ok">提交</button></div>`;
    $("#rep-x").onclick = () => { $("#modal-body").innerHTML = prev; resolve(); };
    $("#rep-ok").onclick = async () => {
      try { await api(`/api/workshop/items/${id}/report`, { body: { reason: $("#rep-r").value, detail: $("#rep-d").value, comment_id: commentId } }); toast("收到了，管理员会处理"); }
      catch (e) { fail(e); }
      resolve();
    };
    void card;
  });
}

async function mine() {
  const r = await api("/api/workshop/items?mine=true").catch((e) => (fail(e), { items: [] }));
  $("#ws-body").innerHTML = `<div class="ws-grid">${r.items.map(cardHTML).join("") || '<p class="muted ws-empty">你还没有发布过角色。</p>'}</div>`;
  $$("#ws-body .ws-card").forEach((el) => (el.onclick = () => open(el.dataset.id)));
}

async function publish() {
  const m = await meta();
  S.chars = await api("/api/characters");
  const cats = Object.entries(m.categories).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  $("#ws-body").innerHTML = `<div class="editor-grid">
    <div class="panel"><div class="section-title mono">FROM CAST · 发布我的角色</div>
      <label>角色<select id="pub-c">${S.chars.map((c) => `<option value="${c.id}">${esc(c.name)}${c.workshop?.own ? "（发布新版本）" : ""}</option>`).join("")}</select></label>
      <label>分类<select id="pub-cat">${cats}</select></label>
      <label>介绍（可选）<textarea id="pub-desc" rows="4" maxlength="4000"></textarea></label>
      <label>这次更新了什么（可选）<input id="pub-log" maxlength="500"></label>
      <div class="row"><button id="pub-go">发布</button></div>
      <p class="muted small">发布的只有人格配置：你们的记忆、聊天和关系不会公开。${m.require_review ? "新作品要管理员审核后才会出现在浏览里。" : ""}</p></div>
    <div class="panel"><div class="section-title mono">UPLOAD · 上传人设文件</div>
      <form class="dropzone" id="pub-dz"><input type="file" id="pub-file" accept=".json,.md,.png,.charx,.zip"><div class="dz-inner"><div class="dz-title">把人设包拖到这里直接发布</div><div class="muted small">格式同“导入人设”</div><div id="pub-name" class="mono small"></div></div></form>
      <label>分类<select id="up-cat">${cats}</select></label>
      <div class="row"><button id="up-go" disabled>上传并发布</button></div>
      <p class="muted small">请只上传你有权分享的角色。被多人举报的作品会先自动隐藏，等待管理员复核。</p></div></div>`;
  $("#pub-go").onclick = async () => {
    try {
      const it = await api("/api/workshop/publish", { body: { character_id: $("#pub-c").value, category: $("#pub-cat").value,
        description: $("#pub-desc").value, changelog: $("#pub-log").value } });
      toast(`发布了 ${it.title} v${it.version}`); S.chars = await api("/api/characters"); bus.emit("chars"); W.tab = "mine"; render();
    } catch (e) { fail(e); }
  };
  let file = null;
  $("#pub-file").onchange = (e) => { file = e.target.files[0]; $("#pub-name").textContent = file ? file.name : ""; $("#up-go").disabled = !file; };
  $("#up-go").onclick = async () => {
    const fd = new FormData(); fd.append("file", file); fd.append("category", $("#up-cat").value);
    try { const it = await api("/api/workshop/upload", { body: fd }); toast("发布了 " + it.title); W.tab = "mine"; render(); } catch (e) { fail(e); }
  };
}

async function review() {
  const r = await api("/api/workshop/reports").catch(fail);
  if (!r) return;
  $("#ws-body").innerHTML = `${r.pending.length ? `<div class="section-title mono">PENDING · 待审核</div><div class="ws-grid">${r.pending.map(cardHTML).join("")}</div>` : ""}
    <div class="section-title mono">REPORTS · 举报</div>
    <div class="mem-list">${r.reports.map((x) => `<div class="mem-card ask"><div class="mem-text">${esc(x.title)} ${x.comment_id ? "（评论）" : ""} <span class="badge warn">${esc(x.reason)}</span> <span class="badge">${esc(x.item_status)}</span></div>
      ${x.detail ? `<div class="muted small">${esc(x.detail)}</div>` : ""}<div class="mem-acts"><button class="small ghost" data-open="${x.item_id}">查看</button>
      <button class="small" data-rs="${x.id}" data-a="dismiss">驳回</button><button class="small ghost" data-rs="${x.id}" data-a="hide">隐藏</button><button class="small danger" data-rs="${x.id}" data-a="remove">下架</button></div></div>`).join("") || '<p class="muted small">没有待处理的举报。</p>'}</div>`;
  $$("#ws-body .ws-card").forEach((el) => (el.onclick = () => open(el.dataset.id)));
  $$("[data-open]").forEach((b) => (b.onclick = () => open(b.dataset.open)));
  $$("[data-rs]").forEach((b) => (b.onclick = () => api(`/api/workshop/reports/${b.dataset.rs}`, { body: { action: b.dataset.a } }).then(review).catch(fail)));
}

function render() {
  $$("#ws-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.wtab === W.tab));
  ({ browse, mine, publish, review })[W.tab]();
}

export const workshopPage = render;
export function initWorkshop() {
  $$("#ws-tabs button").forEach((b) => (b.onclick = () => { W.tab = b.dataset.wtab; render(); }));
}
