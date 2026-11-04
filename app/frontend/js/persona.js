// 02 角色：上面是我的角色（点卡片 = 去聊天，点“编辑” = 在下面编辑）；下面是当前角色的编辑器。
// 一键原则：常用的（名字、简介、性格、说话方式、开场白、立绘、音色）直接摆出来；其余字段、互动参数、
// Markdown / JSON、历史版本、导入导出都收进“更多”，不用的人看不到。改完点一次“保存”就生效。
import { $, $$, S, api, avaHTML, bus, confirmBox, curChar, download, esc, fail, fmtTime, modal, toast } from "./core.js";
import { speak, voiceConfig } from "./voice.js";

const P = { schema: null, dirty: false, advanced: false };
// 对话示例最影响她怎么说话（开源角色卡的通行写法），所以和开场白一起放在最显眼的位置
const MAIN_FIELDS = [["tagline", "简介", 1], ["greeting", "开场白", 2], ["examples", "对话示例（一行一句：“用户：……”“她的名字：……”）", 6],
  ["personality", "性格", 3], ["speech", "说话方式", 3]];
const MORE_FIELDS = ["background", "values", "interests", "preferences", "worldview", "relationships", "boundaries"];
const PORTRAITS = [  // 内置可选的 2D 形象
  { kind: "image", src: "/static/assets/whale-girl.png", label: "大肥鱼立绘" },
  { kind: "image", src: "/static/assets/krino.png", label: "KRINO 立绘" },
  { kind: "live2d", src: "/models/live2d/hiyori/Hiyori.model3.json", label: "Live2D 示例（Hiyori）" },
];

const schema = async () => (P.schema ||= await api("/api/persona-schema"));
async function reloadChars(selectId) { S.chars = await api("/api/characters"); bus.emit("chars", selectId); }

export async function personaPage() {
  const root = $("#persona-page");
  const [c, sc, vc] = await Promise.all([api("/api/characters/" + S.charId), schema(), voiceConfig()]).catch((e) => (fail(e), []));
  if (!c) return;
  S.chars = await api("/api/characters");
  P.dirty = false;
  const p = c.persona, b = c.behavior, labels = Object.fromEntries(sc.fields.map((x) => [x.key, x.label]));
  const portraitKey = b.portrait ? JSON.stringify(b.portrait) : "";
  const custom = b.portrait && !PORTRAITS.some((x) => x.src === b.portrait.src) ? b.portrait : null;
  root.innerHTML = `
    <div class="cast-row">${S.chars.map((x) => `<div class="cast-card ${x.id === c.id ? "active" : ""}" data-use="${x.id}" style="--c:${esc(x.color)}">
        ${avaHTML(x, "lg")}<div><b>${esc(x.name)}</b>${x.official ? ' <span class="badge cobalt">官方</span>' : ""}<div class="muted small">${esc(x.tagline)}</div></div>
        <button class="link small" data-edit="${x.id}">编辑</button></div>`).join("")}
      <button class="cast-card add" id="c-add"><span>＋</span>新角色</button></div>

    <div class="editor">
      <div class="editor-head">
        <input data-p="name" class="name-input" value="${esc(p.name)}" maxlength="40" aria-label="名字">
        <span class="muted small mono">v${c.version}</span>
        <span class="grow"></span>
        <button id="p-more" class="ghost small">更多 ▾</button>
        <button id="p-save">保存</button>
      </div>
      <div class="editor-grid">
        <div>
          ${MAIN_FIELDS.map(([k, l, rows]) => rows === 1
            ? `<label>${l}<input data-p="${k}" value="${esc(p[k] || "")}" maxlength="80"></label>`
            : `<label>${l}<textarea data-p="${k}" rows="${rows}">${esc(p[k] || "")}</textarea></label>`).join("")}
          <details id="more-fields" ${P.advanced ? "open" : ""}><summary>更多设定（背景、价值倾向、兴趣、世界观、关系……）</summary>
            ${MORE_FIELDS.map((k) => `<label>${esc(labels[k])}<textarea data-p="${k}" rows="3">${esc(p[k] || "")}</textarea></label>`).join("")}
            <label>标签（逗号分隔）<input data-p="tags" value="${esc((p.tags || []).join("，"))}"></label>
            <div class="section-title mono">BEHAVIOR · 互动风格</div>
            <label>风格<select data-b="style">${Object.keys(sc.styles).map((s) => `<option ${s === b.style ? "selected" : ""}>${s}</option>`).join("")}</select></label>
            ${Object.entries(sc.numeric).map(([k, l]) => `<div class="slider-row"><span>${esc(l)}</span><input type="range" min="0" max="1" step="0.05" data-b="${k}" value="${b[k]}"><span>${b[k]}</span></div>`).join("")}
          </details>
        </div>
        <div>
          <div class="section-title mono">LOOK · 形象</div>
          <div class="pick-portrait">${PORTRAITS.map((x) => `<button class="portrait-opt ${JSON.stringify({ kind: x.kind, src: x.src }) === portraitKey ? "active" : ""}" data-portrait='${esc(JSON.stringify({ kind: x.kind, src: x.src }))}'>
              ${x.kind === "image" ? `<img src="${x.src}" alt="">` : '<span class="l2d-tag">Live2D</span>'}<em>${esc(x.label)}</em></button>`).join("")}
            ${custom ? `<button class="portrait-opt active" data-portrait='${esc(JSON.stringify(custom))}'><img src="${esc(custom.src)}" alt=""><em>我上传的</em></button>` : ""}
            <label class="portrait-opt upload"><input type="file" id="portrait-file" accept="image/png,image/webp,image/jpeg" hidden><span>＋</span><em>上传立绘</em></label></div>
          <p class="muted small">${b.portrait ? "" : "她还没有立绘，现在显示的是名字铭牌。"}上传透明背景的 PNG 效果最好（≤ 2MB）。Live2D 示例模型 © Live2D Inc.</p>
          <div class="section-title mono">VOICE · 声音</div>
          <div class="row">
            ${vc.tts.voices?.length ? `<select data-v="voice" style="flex:1">${vc.tts.voices.map((v) => `<option ${v === (b.voice.voice || vc.tts.default) ? "selected" : ""}>${v}</option>`).join("")}</select>`
              : `<input data-v="voice" value="${esc(b.voice.voice || "")}" placeholder="音色（服务端语音时用）" style="flex:1">`}
            <button class="ghost small" id="voice-try">▶ 试听</button>
          </div>
          <div class="slider-row"><span>语速</span><input type="range" min="0.6" max="1.6" step="0.05" data-v="rate" value="${b.voice.rate}"><span>${b.voice.rate}</span></div>
          <p class="muted small">${vc.tts.provider === "local" && vc.tts.server ? `本地语音（Kokoro 中文，${vc.tts.voices.length} 个音色）。zf 是女声、zm 是男声，挑一个最像她的。` : "现在用浏览器自带的朗读。"}</p>
        </div>
      </div>
    </div>`;

  $$("[data-use]", root).forEach((el) => (el.onclick = (e) => { if (!e.target.dataset.edit) bus.emit("select", { id: el.dataset.use, view: "chat" }); }));
  $$("[data-edit]", root).forEach((el) => (el.onclick = () => bus.emit("select", { id: el.dataset.edit, view: "persona" })));
  $("#c-add").onclick = addCharacter;
  root.addEventListener("input", () => (P.dirty = true));
  $$("input[type=range]", root).forEach((el) => (el.oninput = () => { el.nextElementSibling.textContent = el.value; P.dirty = true; }));
  $("#more-fields").ontoggle = (e) => (P.advanced = e.target.open);
  $$("[data-portrait]", root).forEach((el) => (el.onclick = () => {
    $$(".portrait-opt", root).forEach((x) => x.classList.remove("active")); el.classList.add("active"); P.dirty = true;
  }));
  $("#portrait-file").onchange = (e) => uploadPortrait(e.target.files[0], root);
  $("#voice-try").onclick = () => speak($("[data-p=greeting]", root).value || "你好，我在这里。", collect(root, c).behavior.voice).catch(fail);
  $("#p-save").onclick = () => save(root, c);
  $("#p-more").onclick = () => moreMenu(c);
}

function collect(root, c) {
  const persona = {};
  $$("[data-p]", root).forEach((el) => (persona[el.dataset.p] = el.value));
  persona.tags = persona.tags.split(/[,，\s]+/).filter(Boolean).slice(0, 8);
  const behavior = { ...c.behavior, style: $("[data-b=style]", root).value };
  $$("[data-b][type=range]", root).forEach((el) => (behavior[el.dataset.b] = +el.value));
  behavior.voice = { ...c.behavior.voice, voice: $("[data-v=voice]", root).value, rate: +$("[data-v=rate]", root).value };
  const pick = $(".portrait-opt.active[data-portrait]", root);
  if (pick) behavior.portrait = JSON.parse(pick.dataset.portrait);
  return { persona, behavior };
}

async function save(root, c) {
  try {
    const r = await api(`/api/characters/${c.id}`, { method: "PUT", body: collect(root, c) });
    P.dirty = false;
    toast(r.version === c.version ? "没有改动" : "保存好了，下一句话起生效");
    await reloadChars(); bus.emit("character:changed"); personaPage();
  } catch (e) { fail(e); }
}

async function uploadPortrait(file, root) {
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) return toast("立绘不能超过 2MB");
  const src = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(file); });
  const box = $(".pick-portrait", root);
  $$(".portrait-opt", box).forEach((x) => x.classList.remove("active"));
  const el = document.createElement("button");
  el.className = "portrait-opt active"; el.dataset.portrait = JSON.stringify({ kind: "image", src });
  el.innerHTML = `<img src="${src}" alt=""><em>我上传的</em>`;
  box.insertBefore(el, box.lastElementChild);
  P.dirty = true;
  toast("点“保存”生效");
}

// ---------- 新角色：一个弹窗，三种方式 ----------
async function addCharacter() {
  if (S.chars.length >= (S.me?.companion_limit || 8)) return toast(`最多 ${S.me.companion_limit} 位角色，先和一位告别吧`);
  await modal("新角色", `
    <label>用一句话描述她<textarea id="gen-prompt" rows="3" maxlength="800" placeholder="例如：在海边书店打工的抹香鲸娘，话少，喜欢在打烊后给我念书"></textarea></label>
    <div class="row"><button id="gen-go">生成</button><span class="muted small">或者</span>
      <label class="ghost-btn">导入文件<input type="file" id="imp-file" accept=".json,.md,.png,.charx,.zip" hidden></label>
      <button class="link small" id="go-ws">去工坊挑一个 →</button></div>
    <p class="muted small">导入支持 KRINO 人设包、Markdown、SillyTavern 角色卡（.json / .png）、RisuAI .charx。文件内容只当资料，不会被执行。</p>
    <div id="gen-out"></div>`, null, { okText: "关闭", cancel: false });
}
document.addEventListener("click", async (e) => {  // 弹窗里的按钮（弹窗内容每次重画，用事件委托）
  if (e.target.id === "gen-go") {
    const prompt = $("#gen-prompt").value.trim();
    if (!prompt) return $("#gen-prompt").focus();
    e.target.disabled = true; $("#gen-out").innerHTML = '<p class="muted small mono">DRAWING…</p>';
    try {
      const d = await api("/api/characters/generate", { body: { prompt } });
      const c = await api("/api/characters", { body: d });
      $("#modal").classList.add("hidden"); toast("欢迎 " + c.name + "，可以在这里继续改她");
      await reloadChars(c.id); bus.emit("select", { id: c.id, view: "persona" });
    } catch (err) { $("#gen-out").innerHTML = `<p class="error">${esc(err.message)}</p>`; }
    finally { e.target.disabled = false; }
  }
  if (e.target.id === "go-ws") { $("#modal").classList.add("hidden"); bus.emit("goto", "workshop"); }
});
document.addEventListener("change", async (e) => {
  if (e.target.id !== "imp-file" || !e.target.files[0]) return;
  const fd = new FormData(); fd.append("file", e.target.files[0]);
  try {
    const c = await api("/api/characters/import", { body: fd });
    $("#modal").classList.add("hidden"); toast("导入了：" + c.name);
    await reloadChars(c.id); bus.emit("select", { id: c.id, view: "persona" });
  } catch (err) { fail(err); }
});

// ---------- 更多：不常用的都在这里 ----------
async function moreMenu(c) {
  const v = await api(`/api/characters/${c.id}/versions`).catch(() => ({ versions: [] }));
  const p = modal("更多", `
    <div class="menu-list">
      <button data-m="md">用 Markdown 编辑</button>
      <button data-m="json">用 JSON 编辑</button>
      <button data-m="exp-json">导出人设（JSON）</button>
      <button data-m="exp-md">导出人设（Markdown）</button>
      <button data-m="publish">发布到工坊</button>
      ${v.versions.length ? `<button data-m="versions">历史版本（${v.versions.length}）</button>` : ""}
      ${c.official ? '<button data-m="reset">还原为官方设定</button>' : ""}
      ${S.chars.length > 1 ? '<button data-m="bye" class="danger-link">和她告别</button>' : ""}
    </div>
    <p class="muted small">导出和发布都只包含人格设定，不含你们的私人记忆。</p>`, null, { okText: "关闭", cancel: false });
  $$("[data-m]", $("#modal-body")).forEach((b) => (b.onclick = async () => {
    const m = b.dataset.m;
    $("#modal").classList.add("hidden");
    try {
      if (m === "md" || m === "json") return sourceEditor(c, m);
      if (m === "exp-json") return download(`/api/characters/${c.id}/export?format=json`, `${c.slug}.krino.json`);
      if (m === "exp-md") return download(`/api/characters/${c.id}/export?format=md`, `${c.slug}.md`);
      if (m === "publish") return bus.emit("publish", c.id);
      if (m === "versions") return versions(c, v);
      if (m === "reset" && await confirmBox("还原为官方设定", "<p>当前版本会先存一份，可以在历史版本里找回。你们的记忆不受影响。</p>", "还原")) {
        await api(`/api/characters/${c.id}/reset`, { method: "POST" }); toast("还原了");
      }
      if (m === "bye" && await confirmBox(`和 ${c.name} 告别`, "<p>她的设定、你们的记忆和聊天都会删除，不能恢复。想留着的话先导出。</p>", "告别")) {
        await api(`/api/characters/${c.id}`, { method: "DELETE" }); await reloadChars(); return bus.emit("select", { id: S.chars[0].id, view: "persona" });
      }
      await reloadChars(); bus.emit("character:changed"); personaPage();
    } catch (e) { fail(e); }
  }));
  return p;
}

async function sourceEditor(c, fmt) {
  const src = await api(`/api/characters/${c.id}/source?format=${fmt}`);
  await modal(fmt === "md" ? "用 Markdown 编辑" : "用 JSON 编辑", `<textarea id="src" class="source-editor" spellcheck="false">${esc(src.text)}</textarea>
    <p class="muted small">保存前会检查格式，不对不会覆盖。</p>`, async (body) => {
    await api(`/api/characters/${c.id}/source`, { method: "PUT", body: { format: fmt, text: $("#src", body).value } });
    toast("保存好了"); await reloadChars(); bus.emit("character:changed"); personaPage();
  }, { okText: "保存", wide: true });
}

async function versions(c, v) {
  modal("历史版本", v.versions.map((x) => `<div class="ver"><b class="mono">v${x.version}</b> <span class="muted small">${fmtTime(x.saved_at)} · ${esc(x.note)}</span>
      <button class="link small" data-ver="${x.version}">恢复到这版</button></div>`).join(""), null, { okText: "关闭", cancel: false });
  $$("[data-ver]", $("#modal-body")).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/characters/${c.id}/versions/${b.dataset.ver}/restore`, { method: "POST" }); $("#modal").classList.add("hidden"); toast("恢复了 v" + b.dataset.ver); await reloadChars(); bus.emit("character:changed"); personaPage(); }
    catch (e) { fail(e); }
  }));
}

export const personaDirty = () => P.dirty;
export function initPersona() {}
