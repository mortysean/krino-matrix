// 圈子 → 酒馆：你自己的几个角色的私人小空间，像一个只有她们的群聊。
//   “让她们聊一会儿”（可以给个话题），或者直接插一句，几个角色接话。她们说话时这里自动刷新。
import { $, S, api, avaHTML, esc, fail, fmtTime, t } from "./core.js";

const V = { poll: 0, last: 0, cast: {} };

export async function tavernTab(box) {
  clearTimeout(V.poll);
  box.innerHTML = `<div class="tv-room"><div class="tv-log" id="tv-log"><p class="muted small">${t("加载中…")}</p></div>
      <form class="tv-bar" id="tv-say"><input name="text" maxlength="300" autocomplete="off" placeholder="${t("插一句，她们会接话…")}">
        <button>${t("说")}</button></form>
      <form class="tv-bar" id="tv-go"><input name="topic" maxlength="80" autocomplete="off" placeholder="${t("给她们一个话题（可以不填）")}">
        <button class="ghost" id="tv-go-btn">${t("让她们聊一会儿")}</button><button type="button" class="link small danger-link" id="tv-clear">${t("清空")}</button></form>
    </div>`;
  const r = await api("/api/tavern").catch((e) => (fail(e), null));
  if (!r || !box.isConnected) return;
  V.cast = Object.fromEntries(r.cast.map((c) => [c.id, c]));
  V.last = 0;
  $("#tv-log").innerHTML = r.messages.length ? "" : `<p class="muted small tv-empty">${r.cast.length < 2
    ? t("酒馆至少要两个角色：先去工作台新建一个") : t("这里是她们的私人小空间。给个话题，或者直接说句话。")}</p>`;
  append(r.messages);
  busy(r.busy);
  $("#tv-say").onsubmit = async (e) => {
    e.preventDefault();
    const text = e.target.text.value.trim();
    if (!text) return;
    e.target.text.value = "";
    try { const o = await api("/api/tavern/say", { body: { text } }); append([o.message]); busy(true); }
    catch (err) { fail(err); e.target.text.value = text; }
  };
  $("#tv-go").onsubmit = async (e) => {
    e.preventDefault();
    try { await api("/api/tavern/go", { body: { topic: e.target.topic.value.trim() } }); e.target.topic.value = ""; busy(true); }
    catch (err) { fail(err); }
  };
  $("#tv-clear").onclick = async () => {
    if (!confirm(t("清空酒馆的聊天记录？她们对彼此的印象不受影响。"))) return;
    try { await api("/api/tavern", { method: "DELETE" }); tavernTab(box); } catch (err) { fail(err); }
  };
}

function append(list) {
  const log = $("#tv-log");
  if (!log || !list.length) return;
  log.querySelector(".tv-empty")?.remove();
  const near = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  for (const m of list) {
    if (m.id <= V.last) continue;
    V.last = m.id;
    const c = m.author_id ? V.cast[m.author_id] : null;
    const who = c ? c.name : (S.me?.display_name || t("你"));
    log.insertAdjacentHTML("beforeend", `<div class="msg enter ${c ? "" : "user"}">${c ? avaHTML(c) : ""}
      <div class="msg-col"><div class="who">${esc(who)} · ${esc(fmtTime(m.created_at))}</div><div class="bubble">${esc(m.content)}</div></div></div>`);
  }
  if (near || list.some((m) => !m.author_id)) log.scrollTop = log.scrollHeight;
}

function busy(on) {
  const log = $("#tv-log");
  if (!log) return;
  log.querySelector(".tv-typing")?.remove();
  if (on) log.insertAdjacentHTML("beforeend", `<p class="muted small tv-typing">${t("她们正在聊…")}</p>`);
  $("#tv-go-btn") && ($("#tv-go-btn").disabled = on);
  clearTimeout(V.poll);
  if (on) V.poll = setTimeout(poll, 1200);
}

async function poll() {
  if (S.view !== "social" || !$("#tv-log")) return;
  const r = await api(`/api/tavern?after=${V.last}`).catch(() => null);
  if (!r) return busy(true);
  append(r.messages);
  busy(r.busy);
}
