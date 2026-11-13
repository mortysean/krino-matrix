// 工作台的“肉体”半边：她的形象。嵌在 02 工作台页（persona.js）左栏，和右栏的“灵魂”一起点一次“保存”生效。
// 只在她自己的形象里挑，不混进别的角色的：
//   官方角色（KRINO、大肥鱼）：各自的 Q 版动图和立绘，两个里换；
//   自己创建的角色：创建时画的立绘、做的动图，加上在这里新画的、改过的、上传的。
// 一键原则：写一句 → “画新形象”（一张，画风参考官方角色）或“在这张上改”/“一键美化”；有立绘没动图的可以“做动图”。
// 生成的立绘先是草稿，点页面顶上的“保存”才写进角色。
import { $, $$, S, api, bus, confirmBox, esc, fail, t, toast } from "./core.js";
import { createChibi } from "./chibi.js";
import { motionStarted } from "./creating.js";

const BEAUTIFY = "保持同一个角色（长相、发型、服装、姿势）和纯白背景不变，只提升画面质量：线条更干净利落，上色更细腻有层次，"
  + "光影更好看，五官更精致，修正手指、脚、比例上不自然的地方";
const drafts = {};  // 每个角色一份草稿，切页面不丢：{ version, portrait, candidates, prompt, busy }
let info = null;
let live = null;  // 当前显示着的面板 { cid, render }：生成要半分钟，期间页面可能已经重画过（比如点了保存）

const same = (a = {}, b = {}) => Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k]);
const samePortrait = (a, b) => (!a && !b) || (!!a && !!b && a.kind === b.kind && a.src === b.src && same(a.expressions, b.expressions));

function draft(c) {
  let d = drafts[c.id];
  if (!d || c.version > d.version) {  // 保存过、还原过：按角色现在的形象重来，生成过的候选和描述留着（旧数据不会把草稿冲回去）
    d = drafts[c.id] = { version: c.version, portrait: c.behavior.portrait ? { ...c.behavior.portrait } : null,
      candidates: d?.candidates || [], prompt: d?.prompt || "", busy: "" };
  }
  return d;
}

// 给 persona.js 用：草稿里的形象、有没有改过、预填描述（一句话新建角色后接着生成形象）
export const bodyPortrait = (c) => draft(c).portrait;
export const bodyDirty = (c) => !samePortrait(draft(c).portrait, c.behavior.portrait || null);
// 保存时一起存的“她自己的形象”：原有的 + 现在选中的这张（新画的、上传的）。官方角色的形象是固定的，不存
export function bodyLooks(c) {
  if (c.official) return undefined;
  const p = draft(c).portrait, list = (c.looks || []).map(({ kind, src, still }) => ({ kind, src, ...(still ? { still } : {}) }));
  if (p && !list.some((x) => x.src === p.src)) list.unshift({ kind: p.kind, src: p.src, ...(p.still ? { still: p.still } : {}) });
  return list.slice(0, 8);
}
// 后台补好了新角色的形象（版本号没变）：丢掉旧草稿，按角色现在的样子重来，不然会误以为“改了没保存”
export function bodyForget(cid) { delete drafts[cid]; }
export function bodyPrompt(cid, text) { (drafts[cid] ||= { version: -1, candidates: [], prompt: "" }).prompt = text; }

const stillOf = (src) => src.replace(/chibi\.json$/, "still.webp");

export async function bodyPanel(host, c, { onChange } = {}) {
  info ||= await api("/api/workbench").catch(() => ({ ready: false, limit: 0, used: 0, motion: { ready: false } }));
  const d = draft(c);
  const changed = () => { onChange?.(); render(); };
  // 等结果回来时，草稿和面板可能都已经换成新的了：写进当前的草稿、画到当前的面板
  const cur = () => drafts[c.id] || d;
  const redraw = () => (live?.cid === c.id && live.render !== render ? live.render() : render());
  live = { cid: c.id, render: () => render() };

  function render() {
    if (!host.isConnected) return;  // 生成期间切走了页面
    const p = d.portrait, img = p?.kind === "image", own = !c.official;
    const left = Math.max(0, info.limit - info.used);
    // 只有她自己的：保存过的形象（官方角色是她的立绘和动图）+ 这次新画的、上传的
    const tiles = [...(c.looks || []).map((x) => ({ ...x }))];
    for (const src of d.candidates) if (!tiles.some((x) => x.src === src)) tiles.push({ kind: "image", src, fresh: true });
    if (p && !tiles.some((x) => x.src === p.src)) tiles.unshift({ ...p });
    const off = d.busy || !info.ready ? "disabled" : "";
    const hasMotion = tiles.some((x) => x.kind === "chibi"), working = c.motion_job || c.pending;
    const savedSrc = c.behavior.portrait?.src;  // 正在用的那个不能删：先换上别的、保存，再删
    const motionBase = img && p.src.startsWith("/media/") ? p : tiles.find((x) => x.kind === "image" && x.src.startsWith("/media/"));
    host.innerHTML = `
      <div class="wb-stage">
        ${img ? `<img src="${esc(p.src)}" alt="">` : p?.kind === "chibi" ? `<div class="wb-chibi"></div>` : p ? `<span class="l2d-tag">Live2D</span>` : `<div class="wb-empty">${t("还没有形象：在下面写一句描述，点“生成新形象”")}</div>`}
        ${d.busy ? `<div class="wb-busy"><i></i>${esc(d.busy)}</div>` : ""}
      </div>
      <div class="section-title mono">${t("她的形象 · 点一个换上")}</div>
      <div class="pick-portrait">${tiles.map((x) => `<div class="portrait-cell"><button class="portrait-opt ${p?.src === x.src ? "active" : ""}" data-portrait='${esc(JSON.stringify({ kind: x.kind, src: x.src, ...(x.still ? { still: x.still } : {}) }))}'>
          ${x.kind === "image" ? `<img src="${esc(x.src)}" alt=""><em>${t(x.fresh ? "新画的" : "立绘")}</em>` : x.kind === "chibi" ? `<img src="${esc(x.still || stillOf(x.src))}" alt=""><i class="chibi-tag">${t("会动")}</i><em>${t("动图")}</em>` : '<span class="l2d-tag">Live2D</span>'}</button>
          ${own && x.src !== savedSrc ? `<button class="look-del" data-del-look="${esc(x.src)}" title="${esc(t("删除这个形象"))}" aria-label="${esc(t("删除这个形象"))}">✕</button>` : ""}</div>`).join("")}
        ${own ? `<label class="portrait-opt upload"><input type="file" id="portrait-file" accept="image/png,image/webp,image/jpeg" hidden><span>＋</span><em>${t("上传立绘")}</em></label>` : ""}</div>
      ${own ? `
      <label>${t("想换个样子？写一句她的样子，或者想改哪里")}
        <textarea id="wb-prompt" rows="3" maxlength="500" placeholder="${t("比如：蓝色长发、鲸鱼发饰、蓝白连帽卫衣、抱着一碗白米饭、傲娇的表情")}">${esc(d.prompt || "")}</textarea></label>
      <div class="row wb-actions">
        <button id="wb-new" ${off} title="${esc(t("画风参考官方角色；只换样子，她还是她。画好后点“保存”生效"))}">${t("画新形象")}</button>
        ${img ? `<button class="ghost" id="wb-edit" ${off}>${t("在这张上改")}</button><button class="ghost" id="wb-beauty" ${off} title="${esc(t("线条、上色、光影更精致，修正手指和比例"))}">✦ ${t("一键美化")}</button>` : ""}
        <span class="grow"></span>
        <span class="muted small">${info.ready ? (info.credit_limited ? "" : t("今天还能生成 {n} 张", { n: left })) : t("图像服务没有配置（需要 DASHSCOPE_API_KEY）")}</span>
      </div>
      ${motionBase && !hasMotion && info.motion?.ready ? `<div class="row wb-motion"><button class="ghost" id="wb-motion" ${working ? "disabled" : ""}>${t(c.motion_job ? "动图做着呢…" : "用这张立绘做动图")}</button>
        <span class="muted small">${t("会做挥手、点头、害羞等动作的 Q 版小人。约 {p} 积分，{m} 分钟，做的时候照常能聊", { p: Math.round(info.motion.points), m: info.motion.minutes })}</span></div>` : ""}`
      : `<p class="muted small">${t("官方角色的形象是固定的：会动的 Q 版和立绘，可以在这两个里换。")}</p>`}`;

    // Q 版小人：预览区里直接动起来，每隔几秒演一个它会的动作
    const box = $(".wb-chibi", host);
    if (box) {
      const ch = createChibi(box);
      ch.load(p.src).then(() => {
        const moves = ch.moves();
        const tick = setInterval(() => { if (!box.isConnected) { clearInterval(tick); ch.destroy(); return; } ch.play(moves[Math.floor(Math.random() * moves.length)]); }, 5200);
      }).catch(() => { box.textContent = t("Q 版小人加载失败"); });
    }
    if ($("#wb-prompt", host)) $("#wb-prompt", host).oninput = (e) => (d.prompt = e.target.value);
    if ($("#wb-new", host)) $("#wb-new", host).onclick = () => generate(null);
    if ($("#wb-edit", host)) $("#wb-edit", host).onclick = () => generate(p.src);
    if ($("#wb-beauty", host)) $("#wb-beauty", host).onclick = () => generate(p.src, t(BEAUTIFY));
    if ($("#wb-motion", host)) $("#wb-motion", host).onclick = () => makeMotion(motionBase);
    $$("[data-portrait]", host).forEach((b) => (b.onclick = () => {
      const pick = JSON.parse(b.dataset.portrait);
      if (pick.src === d.portrait?.src) return;
      d.portrait = pick;
      changed();
    }));
    if ($("#portrait-file", host)) $("#portrait-file", host).onchange = (e) => upload(e.target.files[0]);
    $$("[data-del-look]", host).forEach((b) => (b.onclick = () => removeLook(b.dataset.delLook)));
  }

  // 删除一个形象（先确认）。没保存过的新画的：只从这次的草稿里拿掉；保存过的：从她的形象里删掉，马上生效
  async function removeLook(src) {
    const kept = (c.looks || []).some((x) => x.src === src);
    if (!(await confirmBox(t("删除这个形象"), `<p>${t(kept ? "删掉之后就不在她的形象里了，不能恢复。" : "这张还没保存，删掉就没了。")}</p>`, "删除"))) return;
    const x = cur();
    x.candidates = x.candidates.filter((u) => u !== src);
    if (x.portrait?.src === src) x.portrait = c.behavior.portrait ? { ...c.behavior.portrait } : null;  // 草稿里选着它：退回已保存的那个
    if (kept) {
      try {
        const fresh = await api(`/api/characters/${c.id}`);  // 只改形象列表，右栏没保存的修改不受影响
        const looks = (fresh.looks || []).filter((l) => l.src !== src).map(({ kind, src: s2, still }) => ({ kind, src: s2, ...(still ? { still } : {}) }));
        const r = await api(`/api/characters/${c.id}`, { method: "PUT", body: { behavior: { ...fresh.behavior, looks } } });
        c.behavior = r.behavior; c.looks = r.looks ?? looks; c.version = r.version; x.version = r.version;
        S.chars = await api("/api/characters");
        toast("删掉了");
      } catch (e) { fail(e); }
    }
    onChange?.(); render();
  }

  async function generate(base, preset) {
    const prompt = preset || (d.prompt || "").trim();
    if (!prompt) { $("#wb-prompt", host).focus(); return toast(base ? "先写一句想怎么改" : "先写一句她的样子"); }
    d.busy = t(preset ? "正在美化，大约半分钟…" : base ? "正在修改，大约半分钟…" : "正在画她，大约半分钟…");
    render();
    try {
      const r = await api("/api/workbench/design", { body: { prompt, base, n: 1 } });
      info.used = r.used;
      const x = cur();
      x.candidates = [...r.images, ...x.candidates.filter((u) => !r.images.includes(u))].slice(0, 8);
      x.portrait = { kind: "image", src: r.images[0] };
    } catch (e) { fail(e); }
    d.busy = cur().busy = "";
    redraw();
    onChange?.();
  }

  // 做动图：用的是已经存在服务器上的立绘（新画的要先“保存”）。后台做，进度在右上角的卡片里
  async function makeMotion(base) {
    if (d.candidates.includes(base.src) && !(c.looks || []).some((x) => x.src === base.src)) return toast("先点“保存”把这张立绘存下来，再做动图");
    try {
      await api("/api/workbench/motion", { body: { character_id: c.id } });
      c.motion_job = { done: 0, total: 0 };
      motionStarted(c);
      render();
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
