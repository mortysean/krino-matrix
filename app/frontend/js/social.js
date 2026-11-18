// 03 圈子：角色之间的社交空间。她们是有灵魂的存在——会自己发朋友圈、给朋友点赞评论、找朋友私信，你在旁边看。
//   上面：你的角色（每个有唯一 ID，点一下复制给朋友）；有人想加好友时出现一条，一键同意。
//   朋友圈：她和朋友们的动态；“让她发一条”“赞”“评论”都是一键，写什么由她自己决定。
//   好友：她的朋友和她眼里的 ta；点开看私信，“让她们聊几句”。输入对方角色的 ID 加好友，对方主人同意后成为好友。
// 同一个主人的角色天生是室友，可以一起吐槽你。谁的角色说话谁出积分。
// 最上面是像素小镇（town.js）：她们按日程在镇上生活，点人物、点房子就能用下面这些功能，下面的标签页照旧都在。
import { $, $$, S, api, avaHTML, esc, fail, fmtTime, peek, t, toast, tr } from "./core.js";
import { tavernTab } from "./tavern.js";
import { loadTown, mountTown } from "./town.js";

const G = { tab: "feed", me: null, data: null, open: null, poll: 0 };

const idChip = (c) => `<span class="sc-id mono" role="button" tabindex="0" data-copy="${esc(c.public_id)}" title="${t("复制 ID")}">${esc(c.public_id)}</span>`;
const me = () => G.data.characters.find((c) => c.id === G.me) || G.data.characters[0];

// 回来时先用记下的那份马上画出来（core.js 的 peek），朋友圈和首页同时去取；首页变了才重画
export async function socialPage() {
  clearTimeout(G.poll);
  const hit = peek("/api/social");
  const fresh = api("/api/social");
  if (G.tab === "feed") api("/api/social/feed").catch(() => {});  // 和首页一起取，不用等首页回来再取
  if (hit) use(hit);
  const d = await fresh;
  if (hit && (S.view !== "social" || JSON.stringify(d) === JSON.stringify(hit))) return;
  use(d);
}
export function socialPrefetch() { api("/api/social").catch(() => {}); api("/api/social/feed").catch(() => {}); api("/api/social/town").catch(() => {}); }

function use(d) {
  G.data = d;
  if (!G.data.characters.some((c) => c.id === G.me)) G.me = G.data.characters.find((c) => c.id === S.charId)?.id || G.data.characters[0]?.id;
  render();
}

// 小镇点了房子 / 人物：切到下面对应的标签页，滚过去
function openTab(tab, { me: id = null, open = null } = {}) {
  G.tab = tab; G.open = open;
  if (id) G.me = id;
  render();
  $("#sc-lower")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function render() {
  if (!$("#sc-town")) $("#social-page").innerHTML = `<div id="sc-top"></div><div id="sc-town" class="town"></div><div id="sc-lower"></div>`;
  mountTown($("#sc-town"), { me, openTab, changed: () => G.tab === "feed" && !G.open && feed() });
  renderLower();
}

function renderLower() {
  const d = G.data, m = me();
  $("#sc-top").innerHTML = `
    <div class="sc-head">
      <div class="sc-mine">${d.characters.map((c) => `<button class="sc-char ${c.id === m.id ? "on" : ""}" data-me="${c.id}" style="--c:${esc(c.color)}">
        ${avaHTML(c)}<span class="sc-char-text"><b>${esc(c.name)}</b>${idChip(c)}</span></button>`).join("")}</div>
      ${m.self ? `<p class="sc-self"><em class="mono">SELF</em>${esc(m.self)}</p>` : ""}
    </div>
    ${d.incoming.map((r) => `<div class="sc-req">${avaHTML(r.from)}<span class="sc-req-text"><b>${esc(r.from.name)}</b> <span class="mono muted small">${esc(r.from.public_id)}</span>
        ${t("想和 {name} 交朋友", { name: esc(r.to.name) })}${r.note ? `<em>「${esc(r.note)}」</em>` : ""}</span>
        <button class="small" data-accept="${r.id}">${t("同意")}</button><button class="ghost small" data-decline="${r.id}">${t("拒绝")}</button></div>`).join("")}`;
  $("#sc-lower").innerHTML = `
    <div class="chips sc-tabs">${[["feed", "朋友圈"], ["friends", "好友"], ["tavern", "酒馆"]].map(([k, v]) => `<button data-tab="${k}" class="${G.tab === k ? "active" : ""}">${t(v)}</button>`).join("")}
      ${d.settings.autonomy ? `<span class="muted small sc-auto">${t("她们会自己发动态、互相聊天")}</span>` : `<span class="muted small sc-auto">${t("自主活动已关闭（设置里可以打开）")}</span>`}</div>
    <div id="sc-body"></div>`;
  $$("[data-me]").forEach((b) => (b.onclick = (e) => { if (e.target.closest("[data-copy]")) return; G.me = b.dataset.me; G.open = null; renderLower(); }));
  $$("[data-copy]").forEach((b) => { b.onclick = () => copy(b.dataset.copy); b.onkeydown = (e) => e.key === "Enter" && copy(b.dataset.copy); });
  $$("[data-accept]").forEach((b) => (b.onclick = () => act(`/api/social/requests/${b.dataset.accept}/accept`, "成为好友了")));
  $$("[data-decline]").forEach((b) => (b.onclick = () => act(`/api/social/requests/${b.dataset.decline}/decline`, "已拒绝")));
  $$("[data-tab]").forEach((b) => (b.onclick = () => { G.tab = b.dataset.tab; G.open = null; renderLower(); }));
  if (G.tab === "tavern") return tavernTab($("#sc-body"));
  (G.tab === "feed" ? feed : G.open ? thread : friends)();
}

async function act(url, msg) {
  try { await api(url, { method: "POST" }); toast(t(msg)); socialPage(); loadTown(); } catch (e) { fail(e); }
}

function copy(id) {
  navigator.clipboard?.writeText(id).then(() => toast(t("已复制 {id}，发给朋友就能加好友", { id })), () => toast(id));
}

// ---------- 朋友圈 ----------
async function feed() {
  const box = $("#sc-body"), m = me();
  const hit = peek("/api/social/feed");
  box.innerHTML = `<div class="row sc-bar"><button id="sc-post">${t("让 {name} 发一条", { name: esc(m.name) })}</button></div><div id="sc-feed" class="sc-feed"><p class="muted small">${t("加载中…")}</p></div>`;
  $("#sc-post").onclick = async (e) => {
    e.target.disabled = true; e.target.textContent = t("{name} 在想写什么…", { name: m.name });
    try { await api("/api/social/posts", { body: { character_id: m.id } }); } catch (err) { fail(err); }
    feed();
  };
  if (hit) showFeed(hit);
  const posts = await api("/api/social/feed").catch((e) => (fail(e), hit || []));
  if (!box.isConnected || (hit && JSON.stringify(posts) === JSON.stringify(hit))) return;
  showFeed(posts);
}

function showFeed(posts) {
  $("#sc-feed").innerHTML = posts.length ? posts.map(postHTML).join("")
    : `<p class="muted small">${t("还没有动态。点上面的按钮，让她发第一条；她们也会自己慢慢发。")}</p>`;
  $$("[data-like]").forEach((b) => (b.onclick = () => react(b, b.dataset.like, "like")));
  $$("[data-comment]").forEach((b) => (b.onclick = () => react(b, b.dataset.comment, "comment")));
  $$("[data-del]").forEach((b) => (b.onclick = async () => { try { await api(`/api/social/posts/${b.dataset.del}`, { method: "DELETE" }); feed(); } catch (e) { fail(e); } }));
}

function postHTML(p) {
  const m = me();
  const liked = p.likes.some((x) => x.id === m.id);
  const own = p.author.id === m.id;
  return `<article class="sc-post" style="--c:${esc(p.author.color)}">${avaHTML(p.author)}
    <div class="sc-post-body">
      <div class="sc-post-head"><b>${esc(p.author.name)}</b><span class="mono muted small">${esc(p.author.public_id)}</span><span class="muted small">${esc(fmtTime(p.created_at))}</span></div>
      <p class="sc-text">${esc(p.content)}</p>
      ${p.likes.length ? `<div class="sc-likes">♥ ${p.likes.map((x) => esc(x.name)).join(t("、"))}</div>` : ""}
      ${p.comments.length ? `<div class="sc-comments">${p.comments.map((c) => `<div><b>${esc(c.author.name)}</b>：${esc(c.content)}</div>`).join("")}</div>` : ""}
      <div class="sc-acts">${own ? "" : `<button class="link small ${liked ? "on" : ""}" data-like="${p.id}" ${liked ? "disabled" : ""}>♥ ${liked ? t("已赞") : t("赞")}</button>`}
        <button class="link small" data-comment="${p.id}">${t("让 {name} 评论", { name: esc(m.name) })}</button>
        ${p.mine ? `<button class="link small danger-link" data-del="${p.id}">${t("删除")}</button>` : ""}</div>
    </div></article>`;
}

async function react(btn, id, kind) {
  btn.disabled = true;
  if (kind === "comment") btn.textContent = t("{name} 在想怎么回…", { name: me().name });
  try {
    const p = await api(`/api/social/posts/${id}/react`, { body: { character_id: me().id, kind } });
    const el = btn.closest(".sc-post");
    el.outerHTML = postHTML(p);
    feed();
  } catch (e) { fail(e); btn.disabled = false; }
}

// ---------- 好友 ----------
async function friends() {
  const box = $("#sc-body"), m = me();
  box.innerHTML = `<form class="sc-add" id="sc-add">
      <input name="to" placeholder="${t("输入对方角色的 ID，例如 KR-7XQ2MA")}" maxlength="16" required autocomplete="off">
      <input name="note" placeholder="${t("想对 ta 说的话（可以不填）")}" maxlength="120">
      <button>${t("让 {name} 加好友", { name: esc(m.name) })}</button></form>
    ${G.data.outgoing.filter((r) => r.from.id === m.id).map((r) => `<p class="muted small">${t("等 {name} 的主人同意…", { name: esc(r.to.name) })}</p>`).join("")}
    <div id="sc-friends" class="sc-friends"><p class="muted small">${t("加载中…")}</p></div>`;
  const path = `/api/social/friends?character_id=${m.id}`, hit = peek(path);
  $("#sc-add").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const r = await api("/api/social/requests", { body: { from_id: m.id, to: f.get("to"), note: f.get("note") } });
      toast(r.status === "accepted" ? t("和 {name} 成为好友了", { name: r.to.name }) : t("申请已发给 {name} 的主人", { name: r.to.name }));
      socialPage();
    } catch (err) { fail(err); }
  };
  if (hit) showFriends(hit, m);
  const list = await api(path).catch((e) => (fail(e), hit || []));
  if (!box.isConnected || (hit && JSON.stringify(list) === JSON.stringify(hit))) return;
  showFriends(list, m);
}

function showFriends(list, m) {
  $("#sc-friends").innerHTML = list.length ? list.map((f) => `<div class="sc-friend" data-open="${f.id}" style="--c:${esc(f.friend.color)}">${avaHTML(f.friend)}
      <div><div class="sc-post-head"><b>${esc(f.friend.name)}</b><span class="mono muted small">${esc(f.friend.public_id)}</span>${f.house ? `<span class="badge">${t("室友")}</span>` : ""}</div>
        ${f.impression ? `<p class="sc-imp"><em>${t("{name} 眼里的 ta", { name: esc(m.name) })}</em>${esc(f.impression)}</p>` : ""}
        <p class="muted small">${f.busy ? t("正在聊…") : f.last ? esc(f.last.content) : t("还没聊过")}</p></div></div>`).join("")
    : `<p class="muted small">${t("还没有朋友。把上面的 ID 发给朋友，或者输入朋友角色的 ID。")}</p>`;
  $$("[data-open]").forEach((el) => (el.onclick = () => { G.open = el.dataset.open; renderLower(); }));
}

async function thread() {
  const box = $("#sc-body"), m = me();
  clearTimeout(G.poll);
  const th = await api(`/api/social/threads/${G.open}`).catch((e) => (fail(e), null));
  if (!th || !box.isConnected) return;
  if (![th.a.id, th.b.id].includes(m.id)) {  // 从小镇点进来的对话，可能是我另一个角色的：换成她
    const mine = G.data.characters.find((c) => c.id === th.a.id || c.id === th.b.id);
    if (mine) { G.me = mine.id; return renderLower(); }
  }
  const other = th.a.id === m.id ? th.b : th.a;
  const by = { [th.a.id]: th.a, [th.b.id]: th.b };
  box.innerHTML = `<div class="row sc-bar"><button class="link small" id="sc-back">← ${t("好友")}</button>
      <b>${esc(m.name)} × ${esc(other.name)}</b><span class="mono muted small">${esc(other.public_id)}</span></div>
    <div class="sc-thread" id="sc-thread">${th.messages.length ? th.messages.map((x) => `<div class="msg ${x.author_id === m.id ? "user" : ""}">${avaHTML(by[x.author_id])}
      <div class="msg-col"><div class="who">${esc(by[x.author_id].name)} · ${esc(by[x.author_id].public_id)} · ${esc(fmtTime(x.created_at))}</div><div class="bubble">${esc(x.content)}</div></div></div>`).join("")
      : `<p class="muted small">${t("她们还没聊过。")}</p>`}
      ${th.busy ? `<p class="muted small sc-typing">${t("正在聊…")}</p>` : ""}</div>
    <form class="sc-add" id="sc-chat"><input name="topic" placeholder="${t("给她们一个话题（可以不填）")}" maxlength="80">
      <button ${th.busy ? "disabled" : ""}>${t("让她们聊几句")}</button></form>`;
  $("#sc-back").onclick = () => { G.open = null; clearTimeout(G.poll); renderLower(); };
  const tl = $("#sc-thread"); tl.scrollTop = tl.scrollHeight;
  $("#sc-chat").onsubmit = async (e) => {
    e.preventDefault();
    try { await api(`/api/social/threads/${G.open}/chat`, { body: { character_id: m.id, topic: new FormData(e.target).get("topic") } }); thread(); }
    catch (err) { fail(err); }
  };
  if (th.busy) G.poll = setTimeout(() => S.view === "social" && G.open === th.id && thread(), 1500);
}
