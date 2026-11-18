// 共用的小工具：状态、接口调用、弹窗、提示。各页面模块只依赖这里，互相之间不直接引用。
import { getLocale, t, tr } from "./i18n.js";
export { t, tr };
export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 应用挂在官网的 /cn/products/world/（国内）和 /global/products/world/（国际）下，也兼容直接挂在根目录（本地开发）。
// 接口地址要带上这个前缀，Caddy 才知道该转给哪个地区的后端；/static/、/media/ 两边都在根目录，不用改。
export const BASE = (location.pathname.match(/^\/(?:cn|global)\/products\/world\//) || ["/"])[0];
export const url = (p) => (typeof p === "string" && p.startsWith("/api/") ? BASE + p.slice(1) : p);
// 两个地区的应用在同一个域名下，浏览器存储按地区分开，免得国内版和国际版的登录互相覆盖
const NS = BASE === "/" ? "" : BASE.split("/")[1] + ".";
export function storeGet(k) { try { return localStorage.getItem(NS + k); } catch { return null; } }
export function storeSet(k, v) { try { v == null ? localStorage.removeItem(NS + k) : localStorage.setItem(NS + k, v); } catch { /* 无痕模式 */ } }

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

// 页面切换要快：GET 的结果记一份。回到看过的页面先用 peek() 拿到的这份马上画出来，同时照常去取最新的；
// 悬停在导航上、启动后空闲时提前取好（main.js 的 prefetch）。同一个地址正在取，就共用这一次请求。
// 改了东西（非 GET）就把记下的全部作废，免得先闪一下改之前的样子；聊天、语音、在线计时这些很频繁、
// 又不影响别的页面的，只作废自己那一类（/api/<第一段>）。
const CACHE = new Map(), INFLIGHT = new Map();
const NOISY = ["sessions", "voice", "guard"];
let epoch = 0;  // 作废一次加一：作废之前发出的请求回来了也不记
export const peek = (path) => CACHE.get(path);
const group = (path) => path.split(/[/?]/)[2];
function invalidate(path) {
  epoch += 1;
  const g = NOISY.includes(group(path)) ? group(path) : null;
  for (const m of [CACHE, INFLIGHT]) for (const k of [...m.keys()]) if (!g || group(k) === g) m.delete(k);
}
bus.on("logout", () => invalidate("/api/"));

// 所有接口调用都走这里：带上令牌、统一错误、断网提示
export function api(path, opts = {}) {
  const method = opts.method || (opts.body ? "POST" : "GET");
  if (method !== "GET") {
    invalidate(path);
    return request(path, opts, method).finally(() => invalidate(path));  // 改完再作废一次：改的过程中取回来的也是旧的
  }
  if (opts.raw || opts.signal) return request(path, opts, method);
  if (INFLIGHT.has(path)) return INFLIGHT.get(path);
  const at = epoch;
  const p = request(path, opts, method).then((d) => { if (at === epoch) CACHE.set(path, d); return d; })
    .finally(() => { if (INFLIGHT.get(path) === p) INFLIGHT.delete(path); });
  INFLIGHT.set(path, p);
  return p;
}

async function request(path, opts, method) {
  const headers = { ...(opts.headers || {}) };
  if (S.token) headers.Authorization = "Bearer " + S.token;
  let body = opts.body;
  if (body && !(body instanceof FormData)) { headers["Content-Type"] = "application/json"; body = JSON.stringify(body); }
  let res;
  try {
    res = await fetch(url(path), { method, headers, body, signal: opts.signal });
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
  try { const r = await fetch(url("/api/health")); if (r.ok) setOnline(true); } catch { /* 还没恢复 */ }
}, 5000);
window.addEventListener("offline", () => setOnline(false, t("网络已断开")));
window.addEventListener("online", () => fetch(url("/api/health")).then(() => setOnline(true)).catch(() => {}));

// 页面藏到后台时停掉纯视觉动画。只改一个 class，不读不写角色、记忆或会话。
if (typeof document !== "undefined") {
  const markPage = () => document.documentElement.classList.toggle("page-hidden", document.hidden);
  document.addEventListener("visibilitychange", markPage);
  markPage();
}

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

// 工作台角落的小窗。不用全站的 #modal：灵魂星图看见那个弹窗会停下来画。
const DOCK_FOCUS = "button, [href], input, select, textarea";
export function bindDock(root) {
  root._dockAbort?.abort();
  const ac = new AbortController();
  root._dockAbort = ac;
  const signal = ac.signal;
  let last = null;
  const docks = () => [...root.querySelectorAll(".studio-dock")];
  const focusable = (d) => [...d.querySelectorAll(DOCK_FOCUS)].filter((el) => !el.disabled && el.offsetParent !== null);
  function disarm(d) {
    if (!d) return;
    clearTimeout(d._closeTimer);
    d._closeTimer = 0;
    if (d._onCloseEnd) { d.removeEventListener("animationend", d._onCloseEnd); d._onCloseEnd = null; }
  }
  function finishClose(d) {
    if (!d || d.hidden) return;
    disarm(d);
    d.classList.remove("is-closing");
    d.hidden = true;
    if (last && root.contains(last)) last.focus();
    last = null;
  }
  function close(d) {
    if (!d || d.hidden || d.classList.contains("is-closing")) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) { finishClose(d); return; }
    d.classList.add("is-closing");
    d._onCloseEnd = (e) => {
      if (e.target !== d.querySelector(".dock-card") && e.target !== d) return;
      finishClose(d);
    };
    d.addEventListener("animationend", d._onCloseEnd);
    d._closeTimer = setTimeout(() => finishClose(d), 280);
  }
  function open(d) {
    if (!d) return;
    disarm(d);
    d.classList.remove("is-closing");
    docks().forEach((x) => {
      if (x === d) return;
      disarm(x);
      x.classList.remove("is-closing");
      x.hidden = true;
    });
    last = document.activeElement;
    d.hidden = false;
    (d.querySelector("textarea, input, select") || d.querySelector("button"))?.focus();
  }
  root.addEventListener("krino-open-dock", (e) => { if (e.target?.classList?.contains("studio-dock")) open(e.target); }, { signal });
  root.addEventListener("click", (e) => {
    const openBtn = e.target.closest("[data-dock]");
    if (openBtn && root.contains(openBtn) && !openBtn.closest(".studio-dock")) {
      const d = root.querySelector("#dock-" + openBtn.dataset.dock);
      if (!d) return;
      e.preventDefault();
      (d.hidden || d.classList.contains("is-closing")) ? open(d) : close(d);
      return;
    }
    const shut = e.target.closest("[data-dock-close]");
    if (shut && root.contains(shut)) close(shut.closest(".studio-dock"));
  }, { signal });
  root.addEventListener("keydown", (e) => {
    const d = docks().find((x) => !x.hidden);
    if (!d || !d.contains(e.target)) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(d); return; }
    if (e.key !== "Tab") return;
    const items = focusable(d);
    if (!items.length) return;
    const first = items[0], end = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); end.focus(); }
    else if (!e.shiftKey && document.activeElement === end) { e.preventDefault(); first.focus(); }
  }, { signal });
  return { open, close };
}

export async function download(url, name) {
  const res = await api(url, { raw: true }).catch(fail);
  if (!res) return;
  const href = URL.createObjectURL(await res.blob());
  const a = document.createElement("a"); a.href = href; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export const curChar = () => S.chars.find((c) => c.id === S.charId);

// 头像：角色有立绘就用立绘的头部，否则钴蓝方块加首字
const HEADS = { "/static/assets/whale-girl.png": "/static/assets/whale-girl-head.png", "/static/assets/krino.png": "/static/assets/krino-head.png",
  "/static/chibi/whale/chibi.json": "/static/assets/whale-girl-head.png", "/static/chibi/krino/chibi.json": "/static/assets/krino-head.png" };
export function avaHTML(c, cls = "") {
  if (!c) return "";
  // 自己创建的角色换成动图后，头像用动图的静态封面（官方角色有专门的头像图）
  const src = c.portrait?.kind === "image" ? HEADS[c.portrait.src] || c.portrait.src : c.portrait?.kind === "chibi" ? HEADS[c.portrait.src] || c.portrait.still || null : null;
  const inner = src ? `<img src="${esc(src)}" alt="" class="${HEADS[c.portrait.src] ? "" : "top"}">` : esc([...(c.name || "?")][0]);
  return `<span class="ava ${cls}" style="--c:${esc(c.color)}">${inner}</span>`;
}

export const fmtTime = (ts) => (ts ? new Date(ts).toLocaleString(getLocale() === "en" ? "en-US" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
export const ripple = (el) => window.Mascot?.ripple(el);
