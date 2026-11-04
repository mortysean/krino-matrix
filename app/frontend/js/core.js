// 共用的小工具：状态、接口调用、弹窗、提示。各页面模块只依赖这里，互相之间不直接引用。
import { getLocale, t, tr } from "./i18n.js";
export { t, tr };
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
  site: { edition: "cn", locale: "zh" },  // /api/site：国内版 / 海外版
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
    setOnline(false, t("连不上服务器，正在重试…"));
    throw new ApiError(t("网络连接失败，请检查网络后重试"), 0);
  }
  setOnline(true);
  if (res.status === 401 && S.token) { bus.emit("logout"); throw new ApiError(t("登录已过期"), 401); }
  if (opts.raw) {
    if (!res.ok) throw new ApiError(await errText(res), res.status);
    return res;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof data.detail === "string" ? data.detail : errDetail(data.detail) || t("请求失败（{status}）", { status: res.status }), res.status);
  return data;
}

async function errText(res) {
  const body = await res.text();
  try { const d = JSON.parse(body).detail; return typeof d === "string" ? d : errDetail(d); } catch { return body.slice(0, 200) || t("请求失败（{status}）", { status: res.status }); }
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
window.addEventListener("offline", () => setOnline(false, t("网络已断开")));
window.addEventListener("online", () => fetch("/api/health").then(() => setOnline(true)).catch(() => {}));

// 提示：消息先过一遍 tr()，中文原文和后端拼好的句子都能在海外版翻成英文
export function toast(msg, ms = 2400) {
  const el = $("#toast");
  el.textContent = tr(String(msg ?? "")); el.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}
export const fail = (e) => toast("✕ " + tr(e?.message || String(e)), 4000);

// 弹窗：onOk 返回 false 时不关闭；返回 Promise，取消时为 null
export function modal(title, html, onOk, { okText = "确定", wide = false, cancel = true } = {}) {
  title = tr(title); okText = tr(okText);
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

// 角色头像：有立绘就用立绘的头部，否则钴蓝方块加首字
// 头像：角色有立绘就用立绘的头部，否则钴蓝方块加首字
const HEADS = { "/static/assets/whale-girl.png": "/static/assets/whale-girl-head.png" };
export function avaHTML(c, cls = "") {
  if (!c) return "";
  const src = c.portrait?.kind === "image" ? HEADS[c.portrait.src] || c.portrait.src : null;
  const inner = src ? `<img src="${esc(src)}" alt="" class="${HEADS[c.portrait.src] ? "" : "top"}">` : esc([...(c.name || "?")][0]);
  return `<span class="ava ${cls}" style="--c:${esc(c.color)}">${inner}</span>`;
}

export const fmtTime = (ts) => (ts ? new Date(ts).toLocaleString(getLocale() === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
export const ripple = (el) => window.Mascot?.ripple(el);
