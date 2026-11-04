// 共用的小工具：状态、接口调用、弹窗、提示。各页面模块只依赖这里，互相之间不直接引用。
export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function storeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
export function storeSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* 无痕模式 */ } }

// 全局状态：只放跨页面共享的东西
export const S = {
  token: storeGet("krino_token"),
  me: null,
  chars: [],
  charId: storeGet("krino_char"),
  view: "chat",
  online: true,
};

// 简单的事件总线：角色切换、登录变化时通知各页面
const listeners = {};
export const bus = {
  on(ev, fn) { (listeners[ev] ||= []).push(fn); },
  emit(ev, data) { (listeners[ev] || []).forEach((fn) => fn(data)); },
};

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

function setOnline(ok, why) {
  if (S.online === ok) return;
  S.online = ok;
  bus.emit("online", { ok, why });
}

// 所有接口调用都走这里：带上令牌、统一错误、断网提示
export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  let body = opts.body;
  if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  let res;
  try {
    res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: opts.signal });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    setOnline(false, "连不上服务器，正在重试…");
    throw new ApiError("网络连接失败，请检查网络后重试", 0);
  }
  setOnline(true);
  if (res.status === 401 && S.token) { bus.emit("logout"); throw new ApiError("登录已过期", 401); }
  if (opts.raw) {
    if (!res.ok) throw new ApiError(await errText(res), res.status);
    return res;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : errDetail(data.detail) || `请求失败（${res.status}）`, res.status);
  return data;
}

async function errText(res) {
  const t = await res.text();
  try { const d = JSON.parse(t).detail; return typeof d === "string" ? d : errDetail(d); } catch { return t.slice(0, 200) || `请求失败（${res.status}）`; }
}
function errDetail(d) {
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("；");
  return d ? JSON.stringify(d) : "";
}

// 健康检查：断网后每 5 秒探一次，恢复时自动隐藏提示
setInterval(async () => {
  if (S.online) return;
  try { const r = await fetch("/api/health"); if (r.ok) setOnline(true); } catch { /* 还没恢复 */ }
}, 5000);
window.addEventListener("offline", () => setOnline(false, "网络已断开"));
window.addEventListener("online", () => fetch("/api/health").then(() => setOnline(true)).catch(() => {}));

export function toast(msg, ms = 2400) {
  const t = $("#toast");
  t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}
export const fail = (e) => toast("✕ " + (e?.message || e), 4000);

// 弹窗：onOk 返回 false 时不关闭；返回 Promise，取消时为 null
export function modal(title, html, onOk, { okText = "确定", wide = false, cancel = true } = {}) {
  $("#modal-cancel").classList.toggle("hidden", !cancel);
  $("#modal .modal-card").classList.toggle("wide", wide);
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $("#modal-ok").textContent = okText;
  $("#modal").classList.remove("hidden");
  return new Promise((resolve) => {
    const close = (v) => { $("#modal").classList.add("hidden"); $("#modal-ok").onclick = $("#modal-cancel").onclick = null; resolve(v); };
    $("#modal-cancel").onclick = () => close(null);
    $("#modal-ok").onclick = async () => {
      try { const r = onOk ? await onOk($("#modal-body")) : true; if (r !== false) close(r); } catch (e) { fail(e); }
    };
  });
}
export const confirmBox = (title, html, okText = "确定") => modal(title, html, null, { okText });

export async function download(url, name) {
  const res = await api(url, { raw: true }).catch(fail);
  if (!res) return;
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a"); a.href = href; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export const curChar = () => S.chars.find((c) => c.id === S.charId);

// 角色头像：官方角色用鲸鱼娘线刻头像，其他用钴蓝方块加首字
export function avaHTML(c, cls = "") {
  if (!c) return "";
  const inner = c.official ? '<span class="fig-head"></span>' : esc([...(c.name || "?")][0]);
  return `<span class="ava ${cls}" style="--c:${esc(c.color)}">${inner}</span>`;
}

export const fmtTime = (t) => (t ? new Date(t).toLocaleString([], { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
export const ripple = (el) => window.Mascot?.ripple(el);
