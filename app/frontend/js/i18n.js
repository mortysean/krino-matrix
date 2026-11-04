// 界面翻译（见 i18n/README.md）：中文原文就是键，海外版查 i18n/en.json。
let locale = "zh";
let dict = {};
let patterns = [];  // 带 {x} 占位的条目，用来匹配后端拼出来的报错

const fill = (s, vars) => (vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s);
const reEscape = (s) => s.replace(/[.*+?^$()|[\]\\]/g, "\\$&");

export async function setLocale(l) {
  locale = l === "en" ? "en" : "zh";
  document.documentElement.lang = locale === "en" ? "en" : "zh-CN";
  if (locale === "zh") { dict = {}; patterns = []; return; }
  dict = await fetch("/static/i18n/en.json").then((r) => r.json()).catch(() => ({}));
  patterns = Object.keys(dict).filter((k) => k.includes("{")).map((k) => {
    const names = [...k.matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
    const re = new RegExp("^" + reEscape(k).replace(/\\\{\w+\\\}|\{\w+\}/g, "(.+?)") + "$");
    return { re, names, out: dict[k] };
  });
}

export const getLocale = () => locale;

// 界面文案
export function t(s, vars) {
  if (locale === "zh" || !s) return fill(s, vars);
  return fill(dict[s] ?? s, vars);
}

// 服务器或别处拼好的句子：先精确匹配，再按占位模板匹配
export function tr(s) {
  if (locale === "zh" || !s) return s;
  if (dict[s]) return dict[s];
  for (const p of patterns) {
    const m = p.re.exec(s);
    if (m) return fill(p.out, Object.fromEntries(p.names.map((n, i) => [n, m[i + 1]])));
  }
  return s;
}

// 翻译 HTML 里标了 data-i18n 的静态文字（第一次记下中文原文，重复调用不会翻两次）
export function applyDom(root = document) {
  if (locale === "zh") return;
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.dataset.i18n ||= el.textContent.trim();
    el.textContent = t(el.dataset.i18n);
  });
  for (const [attr, key] of [["placeholder", "i18nPh"], ["title", "i18nTitle"]]) {
    root.querySelectorAll(`[data-${key === "i18nPh" ? "i18n-ph" : "i18n-title"}]`).forEach((el) => {
      el.dataset[key] ||= el.getAttribute(attr) || "";
      el.setAttribute(attr, t(el.dataset[key]));
    });
  }
}
