// 工作台的“肉体”半边：她的形象。嵌在 02 工作台页（persona.js）左栏，和右栏的“灵魂”一起点一次“保存”生效。
// 一键原则：写一句描述 → “生成新形象” → 点一张喜欢的 →（可选）写一句 → “在这张上改” → “一键生成整套表情”。
// 也可以选内置立绘、Live2D，或上传自己画的。生成的立绘先是草稿，点页面顶上的“保存”才写进角色；
// 整套表情花的额度多，生成好就自动连同这张立绘存进角色（右栏没保存的人设修改不受影响）。
import { $, $$, S, api, bus, esc, fail, t, toast } from "./core.js";

const BUILTIN = [  // 内置可选的形象
  { kind: "image", src: "/static/assets/whale-girl.png", label: "大肥鱼立绘" },
  { kind: "image", src: "/static/assets/krino.png", label: "KRINO 立绘" },
  { kind: "live2d", src: "/models/live2d/hiyori/Hiyori.model3.json", label: "Live2D 示例（Hiyori）" },
];
const LABELS = { neutral: "平静", calm: "温和", happy: "开心", shy: "害羞", sad: "难过", worried: "担心", angry: "生气",
  surprised: "惊讶", sleepy: "困", focused: "认真" };
const drafts = {};  // 每个角色一份草稿，切页面不丢：{ version, portrait, candidates, faces, prompt, busy, pending }
// faces：每张立绘各自的整套表情 { 立绘地址: { 表情: 图片 } }，点别的立绘再点回来，表情还在
let info = null;

const same = (a = {}, b = {}) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k]);
const samePortrait = (a, b) => (!a && !b) || (!!a && !!b && a.kind === b.kind && a.src === b.src && same(a.expressions, b.expressions));

function draft(c) {
  let d = drafts[c.id];
  if (!d || c.version > d.version) {  // 保存过、还原过：按角色现在的形象重来，生成过的候选和描述留着（旧数据不会把草稿冲回去）
    d = drafts[c.id] = { version: c.version, portrait: c.behavior.portrait ? { ...c.behavior.portrait } : null,
      candidates: d?.candidates || [], faces: d?.faces || {}, prompt: d?.prompt || "", busy: "", pending: new Set() };
    const saved = c.behavior.portrait;
    if (saved?.expressions && Object.keys(saved.expressions).length) d.faces[saved.src] = { ...saved.expressions };
  }
  return d;
}

// 给 persona.js 用：草稿里的形象、有没有改过、预填描述（一句话新建角色后接着生成形象）
export const bodyPortrait = (c) => draft(c).portrait;
export const bodyDirty = (c) => !samePortrait(draft(c).portrait, c.behavior.portrait || null);
export function bodyPrompt(cid, text) { (drafts[cid] ||= { version: -1, candidates: [], faces: {}, prompt: "" }).prompt = text; }

function facesLabel(p) {
  const n = Object.keys(p.expressions || {}).length, all = info.expressions.length;
  return !n ? t("一键生成整套表情") : n < all ? t("补齐剩下 {n} 个表情", { n: all - n }) : t("重新生成整套表情");
}

export async function bodyPanel(host, c, { onChange } = {}) {
  info ||= await api("/api/workbench").catch(() => ({ ready: false, limit: 0, used: 0, expressions: Object.keys(LABELS) }));
  const d = draft(c);
  const changed = () => { onChange?.(); render(); };

  function render() {
    if (!host.isConnected) return;  // 生成期间切走了页面
    const p = d.portrait, img = p?.kind === "image";
    const left = Math.max(0, info.limit - info.used);
    const tiles = [...d.candidates.map((src) => ({ kind: "image", src, label: "" })), ...BUILTIN];
    const saved = c.behavior.portrait;  // 已保存的那张始终在：换成别的之后还能点回来
    if (saved && !tiles.some((x) => x.src === saved.src)) tiles.unshift({ ...saved, label: "现在的" });
    if (p && !tiles.some((x) => x.src === p.src)) tiles.unshift({ ...p, label: "" });
    const off = d.busy || !info.ready ? "disabled" : "";
    host.innerHTML = `
      <div class="wb-stage">
        ${img ? `<img src="${esc(p.src)}" alt="">` : p ? `<span class="l2d-tag">Live2D</span>` : `<div class="wb-empty">${t("还没有形象：在下面写一句描述，点“生成新形象”")}</div>`}
        ${d.busy ? `<div class="wb-busy"><i></i>${esc(d.busy)}</div>` : ""}
      </div>
      <label>${t("描述她的样子，或者想改哪里")}
        <textarea id="wb-prompt" rows="3" maxlength="500" placeholder="${t("比如：蓝色长发、鲸鱼发饰、蓝白连帽卫衣、抱着一碗白米饭、傲娇的表情")}">${esc(d.prompt || "")}</textarea></label>
      <div class="row wb-actions">
        <button id="wb-new" ${off}>${t("生成新形象")}</button>
        ${img ? `<button class="ghost" id="wb-edit" ${off}>${t("在这张上改")}</button>` : ""}
        <span class="grow"></span>
        <span class="muted small">${info.ready ? (info.credit_limited ? "" : t("今天还能生成 {n} 张", { n: left })) : t("图像服务没有配置（需要 DASHSCOPE_API_KEY）")}</span>
      </div>
      <div class="section-title mono">${t("形象 · 点一张换上")}</div>
      <div class="pick-portrait">${tiles.map((x) => `<button class="portrait-opt ${p?.src === x.src ? "active" : ""}" data-portrait='${esc(JSON.stringify({ kind: x.kind, src: x.src }))}'>
          ${x.kind === "image" ? `<img src="${esc(x.src)}" alt="">` : '<span class="l2d-tag">Live2D</span>'}${x.label ? `<em>${esc(t(x.label))}</em>` : ""}</button>`).join("")}
        <label class="portrait-opt upload"><input type="file" id="portrait-file" accept="image/png,image/webp,image/jpeg" hidden><span>＋</span><em>${t("上传立绘")}</em></label></div>
      ${img ? `<div class="section-title mono">${t("表情 · 聊天时她换表情就换成这张")}</div>
        <div class="wb-faces">${info.expressions.map((e) => `<button class="wb-face ${d.pending.has(e) ? "loading" : ""}" data-face="${e}" title="${t(LABELS[e])}">
            ${p.expressions?.[e] ? `<img src="${esc(p.expressions[e])}" alt="">` : "<span>＋</span>"}<em>${t(LABELS[e])}</em></button>`).join("")}</div>
        <div class="row"><button class="ghost small" id="wb-faces" ${off}>${facesLabel(p)}</button>
        <span class="muted small">${t("生成好自动存进她的形象，大约一两分钟；人物、衣服和姿势不变，只换表情。")}</span></div>` : ""}`;

    $("#wb-prompt", host).oninput = (e) => (d.prompt = e.target.value);
    $("#wb-new", host).onclick = () => generate(null);
    if ($("#wb-edit", host)) $("#wb-edit", host).onclick = () => generate(p.src);
    $$("[data-portrait]", host).forEach((b) => (b.onclick = () => {
      const pick = JSON.parse(b.dataset.portrait);
      if (pick.src === d.portrait?.src) return;
      const ex = d.faces[pick.src];  // 这张生成过表情：表情跟着回来
      d.portrait = ex ? { ...pick, expressions: { ...ex } } : pick;
      changed();
    }));
    $("#portrait-file", host).onchange = (e) => upload(e.target.files[0]);
    $$("[data-face]", host).forEach((b) => (b.onclick = () => {
      const src = d.portrait?.expressions?.[b.dataset.face];
      if (src) $(".wb-stage img", host).src = src;  // 点一下预览这个表情
    }));
    if ($("#wb-faces", host)) $("#wb-faces", host).onclick = faces;
  }

  async function generate(base) {
    const prompt = (d.prompt || "").trim();
    if (!prompt) { $("#wb-prompt", host).focus(); return toast(base ? "先写一句想怎么改" : "先写一句她长什么样"); }
    d.busy = t(base ? "正在修改，大约半分钟…" : "正在生成 4 张，大约半分钟…");
    render();
    try {
      const r = await api("/api/workbench/design", { body: { prompt, base, n: 4 } });
      info.used = r.used;
      d.candidates = [...r.images, ...d.candidates.filter((u) => !r.images.includes(u))].slice(0, 8);
      d.portrait = { kind: "image", src: r.images[0] };
      onChange?.();
    } catch (e) { fail(e); }
    d.busy = "";
    render();
  }

  async function faces() {
    d.busy = t("正在生成表情，大约一两分钟…");
    const had = d.portrait.expressions || {};
    info.expressions.forEach((e) => { if (!had[e] || info.expressions.every((x) => had[x])) d.pending.add(e); });
    render();
    try {
      const have = d.portrait.expressions || {};
      const all = info.expressions.every((e) => have[e]);
      const want = all ? info.expressions : info.expressions.filter((e) => !have[e]);  // 缺几张补几张，齐了就整套重来
      const r = await api("/api/workbench/expressions", { body: { base: d.portrait.src, expressions: want } });
      info.used = r.used;
      const src = d.portrait.src;
      d.faces[src] = { ...(d.faces[src] || {}), ...r.images };
      if (d.portrait.src === src) d.portrait = { ...d.portrait, expressions: { ...d.faces[src] } };
      const failed = Object.keys(r.errors || {});
      if (Object.keys(r.images).length) await keep();
      onChange?.();
      toast(failed.length ? t("有 {n} 个表情没生成出来，再点一次只补这几个", { n: failed.length })
        : t("整套表情生成好了，已经存进她的形象"), 5000);
    } catch (e) { fail(e); }
    d.pending.clear(); d.busy = "";
    render();
  }

  // 只把形象写进角色：用角色已保存的其他设置，右栏没保存的人设修改留在页面上，之后照常点“保存”
  async function keep() {
    try {
      const r = await api(`/api/characters/${c.id}`, { method: "PUT", body: { behavior: { ...c.behavior, portrait: d.portrait } } });
      c.version = r.version; c.behavior = r.behavior; d.version = r.version;
      S.chars = await api("/api/characters");
      bus.emit("character:changed");
    } catch (e) { fail(e); }
  }

  async function upload(file) {
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) return toast("立绘不能超过 3MB");
    const image = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(file); });
    try {
      const { src } = await api("/api/workbench/upload", { body: { image } });
      d.candidates = [src, ...d.candidates].slice(0, 8);
      d.portrait = { kind: "image", src };
      changed();
      toast("点“保存”生效");
    } catch (e) { fail(e); }
  }

  render();
}
