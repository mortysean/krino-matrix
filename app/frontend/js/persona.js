// 02 工作台：灵魂和肉体在一页。上面是我的角色（点卡片 = 去聊天，点“编辑” = 在下面编辑）；
// 下面左栏是肉体（形象：修改 / 整套表情，见 workbench.js；声音），可以改，点一次“保存”生效；
// 右栏是灵魂的神经网络视图（soulgraph.js），只看不改：改灵魂就不是她了（OOC）。灵魂只在“新角色”里设计。
// “导出”得到一个文件（灵魂 + 肉体，图片内嵌），可以直接上传工坊；不常用的（历史版本、还原、告别）收进“更多”。
import { $, $$, S, api, avaHTML, bus, confirmBox, curChar, download, esc, fail, fmtTime, modal, t, toast, tr } from "./core.js";
import { speak, voiceConfig } from "./voice.js";
import { bodyDirty, bodyForget, bodyPanel, bodyPortrait, bodyPrompt } from "./workbench.js";
import { soulGraph } from "./soulgraph.js";

const P = { schema: null, dirty: false, advanced: false };
// 对话示例最影响她怎么说话（开源角色卡的通行写法），所以和开场白一起放在最显眼的位置
const MORE_FIELDS = ["background", "values", "interests", "preferences", "worldview", "relationships", "boundaries"];
const schema = async () => (P.schema ||= await api("/api/persona-schema"));
async function reloadChars(selectId) { S.chars = await api("/api/characters"); bus.emit("chars", selectId); }

export async function personaPage() {
  const root = $("#persona-page");
  const [c, sc, vc] = await Promise.all([api("/api/characters/" + S.charId), schema(), voiceConfig()]).catch((e) => (fail(e), []));
  if (!c) return;
  VOICE_LABELS = vc.tts.labels || {};
  S.chars = await api("/api/characters");
  P.dirty = false;
  P.c = c;
  const p = c.persona, b = c.behavior;
  root.innerHTML = `
    <div class="cast-row">${S.chars.map((x) => `<div class="cast-card ${x.id === c.id ? "active" : ""}" data-use="${x.id}" style="--c:${esc(x.color)}">
        ${avaHTML(x, "lg")}<div><b>${esc(x.name)}</b>${x.official ? ` <span class="badge cobalt">${t("官方")}</span>` : ""}<div class="muted small">${esc(x.tagline)}</div></div>
        <button class="link small" data-edit="${x.id}">${t("编辑")}</button></div>`).join("")}
      <button class="cast-card add" id="c-add"><span>＋</span>${t("新角色")}</button></div>

    <div class="editor">
      <div class="editor-head">
        <h2 class="name-title">${esc(p.name)}</h2>
        <span class="muted small mono">v${c.version}</span>
        <span class="grow"></span>
        <button id="p-more" class="ghost small">${t("更多")} ▾</button>
        <button id="p-export" class="ghost small" title="${t("灵魂 + 肉体打包成一个文件，可以直接上传工坊")}">${t("导出")}</button>
        <button id="p-publish" class="ghost small">${t("发布到工坊")}</button>
        <button id="p-save">${t("保存")}</button>
      </div>
      <div class="studio">
        <div class="studio-body">
          <div class="section-title mono">${t("BODY · 肉体")}</div>
          <div id="body-host"></div>
          <div class="section-title mono">${t("VOICE · 声音")}</div>
          <div class="row">
            ${vc.tts.voices?.length ? `<select data-v="voice" style="flex:1">${voiceOptions(vc.tts, b.voice.voice)}</select>`
              : `<input data-v="voice" value="${esc(b.voice.voice || "")}" placeholder="${t("音色（服务端语音时用）")}" style="flex:1">`}
            <button class="ghost small" id="voice-try">▶ ${t("试听")}</button>
          </div>
          ${vc.tts.design ? `<div class="voice-design">
            <textarea data-v="style" rows="2" placeholder="${t("描述想要的声音：性别年龄、音色、语速、情绪……例如：低沉沙哑的老年巫师，慢条斯理")}">${esc(b.voice.style || "")}</textarea>
            <button class="ghost small" id="voice-redesign">${t("按描述设计新声音")}</button>
          </div>` : ""}
          <div class="slider-row"><span>${t("语速")}</span><input type="range" min="0.6" max="1.6" step="0.05" data-v="rate" value="${b.voice.rate}"><span>${b.voice.rate}</span></div>
          <p class="muted small">${voiceNote(vc.tts)}</p>
        </div>
        <div class="studio-soul">
          <div class="section-title mono">${t("SOUL · 灵魂")}</div>
          <div id="soul-host"></div>
        </div>
      </div>
    </div>`;

  $$("[data-use]", root).forEach((el) => (el.onclick = (e) => { if (!e.target.dataset.edit) bus.emit("select", { id: el.dataset.use, view: "chat" }); }));
  $$("[data-edit]", root).forEach((el) => (el.onclick = () => bus.emit("select", { id: el.dataset.edit, view: "persona" })));
  $("#c-add").onclick = addCharacter;
  $$("input[type=range]", root).forEach((el) => (el.oninput = () => { el.nextElementSibling.textContent = el.value; markDirty(true); }));
  soulGraph($("#soul-host", root), c, { onNew: addCharacter });
  root.oninput = (e) => { if (!e.target.closest("#body-host")) markDirty(true); };  // 每次重画都覆盖，不会越绑越多
  bodyPanel($("#body-host", root), c, { onChange: markDirty }).then(() => markDirty()).catch(fail);
  $("#voice-try").onclick = () => speak(p.greeting || t("你好，我在这里。"), collect(root, c).behavior.voice).catch(fail);
  $("#voice-redesign", root)?.addEventListener("click", async (e) => {  // 设计好就选上并试听；点“保存”才算数
    const style = $("[data-v=style]", root).value.trim();
    if (!style) return $("[data-v=style]", root).focus();
    const btn = e.currentTarget; btn.disabled = true; btn.textContent = t("正在设计，几秒…");
    try {
      const res = await api("/api/voice/design", { body: { description: style, sample: p.greeting || "" }, raw: true });
      const id = res.headers.get("x-voice-id"), sel = $("[data-v=voice]", root);
      sel.insertAdjacentHTML("afterbegin", `<option value="${esc(id)}">${esc(t("专属声音（刚设计的）"))}</option>`);
      sel.value = id; markDirty(true);
      new Audio(URL.createObjectURL(await res.blob())).play().catch(() => {});
      toast("设计好了，点“保存”就换成这个声音");
    } catch (err) { fail(err); }
    finally { btn.disabled = false; btn.textContent = t("按描述设计新声音"); }
  });
  $("#p-save").onclick = () => save(root, c);
  $("#p-more").onclick = () => moreMenu(c);
  $("#p-export").onclick = async () => {  // 先存再导出：导出的就是现在看到的样子
    if (personaDirty() && !(await save(root, c, { quiet: true }))) return;
    download(`/api/characters/${c.id}/export?format=json`, `${c.slug}.krino.json`);
  };
  $("#p-publish").onclick = async () => {
    if (personaDirty() && !(await save(root, c, { quiet: true }))) return;
    bus.emit("publish", c.id);
  };
}

function collect(root, c) {  // 只有肉体：形象和声音。灵魂不在这里改
  const behavior = { ...c.behavior };
  behavior.voice = { ...c.behavior.voice, voice: $("[data-v=voice]", root).value, rate: +$("[data-v=rate]", root).value };
  const st = $("[data-v=style]", root);
  if (st) behavior.voice.style = st.value.trim();
  behavior.portrait = bodyPortrait(c);
  return { behavior };
}

function markDirty(soul = false) {
  if (soul === true) P.dirty = true;
  $("#p-save")?.classList.toggle("dirty", personaDirty());
}

async function save(root, c, { quiet = false } = {}) {
  try {
    const r = await api(`/api/characters/${c.id}`, { method: "PUT", body: collect(root, c) });
    P.dirty = false; P.c = null;  // 重画之前不再拿旧数据判断“有没有没保存的修改”
    if (!quiet) toast(r.version === c.version ? "没有改动" : "保存好了，下一句话起生效");
    await reloadChars(); bus.emit("character:changed"); await personaPage();
    return true;
  } catch (e) { fail(e); return false; }
}

// ---------- 新角色：唯一能设计灵魂的地方 ----------
// 一句话 → 写出一份灵魂草稿（性格、说话方式、开场白、对话样例、外貌、声音）→ 在这里随便改 → “创建角色”（顺便画形象、设计声音）。
// 一句话可以是原创，也可以是已有作品里的角色（“哈利·波特里的马尔福”）：后端会先联网查设定。角色不一定是“她”，称呼跟着设定走。
// 也可以从空白开始自己写，或者导入文件、去工坊挑。建好之后灵魂就固定了，工作台里只看不改。
const D = { draft: null, prompt: "", voice: null };  // voice：试听时设计出来的声音 { id, style }，描述没改就直接用
const DRAFT_FIELDS = [["name", "名字", 1], ["tagline", "简介", 1], ["greeting", "开场白", 2], ["personality", "性格", 3], ["speech", "说话方式（口头禅写在这里）", 3],
  ["examples", "对话示例（一行一句：“用户：……”“角色名：……”）", 5]];
const PRONOUNS = [["她", "她"], ["他", "他"], ["它", "它（非人类）"], ["TA", "TA（不确定 / 不区分）"]];

export async function addCharacter() {
  if (S.chars.length >= (S.me?.companion_limit || 8)) return toast(t("最多 {n} 位角色，先和一位告别吧", { n: S.me.companion_limit }));
  const saved = D.saved;  // 写好的草稿还没创建就关了窗口（或者写的时候就关了）：留着，再点“新角色”接着改
  D.draft = null; D.prompt = saved?.prompt || ""; D.voice = null;
  const p = modal("新角色", `
    <label>${t("用一句话描述你想要的角色：原创的，或者书、动漫、游戏里已有的都行")}<textarea id="gen-prompt" rows="2" maxlength="500" placeholder="${t("例如：哈利·波特里的德拉科·马尔福；或者：在海边书店打工的抹香鲸，话少，打烊后给我念书")}"></textarea></label>
    <div class="row"><button id="gen-go">${t("写出灵魂")}</button><button class="ghost small" id="gen-blank">${t("从空白开始自己写")}</button>
      <span class="grow"></span>
      <label class="ghost-btn">${t("导入文件")}<input type="file" id="imp-file" accept=".json,.md,.png,.charx,.zip" hidden></label>
      <button class="link small" id="go-ws">${t("去工坊挑一个 →")}</button></div>
    <div id="gen-out"></div>`, null, { okText: "关闭", cancel: false, wide: true });
  if (saved) { $("#gen-prompt").value = saved.prompt; await draftForm(saved.draft); }
  if (D.writing) { $("#gen-prompt").value = D.writing; $("#gen-out").innerHTML = `<p class="muted small">${t("还在写，写好了会显示在这里…")}</p>`; }
  await p;
}

// 新角色的形象和声音在后台做：每隔几秒看一眼，做好了换上并告诉一声。刷新页面也会接着看（角色带着 pending）
const watching = new Set();
function watchPending() {
  for (const c of S.chars || []) {
    if (!c.pending || watching.has(c.id)) continue;
    watching.add(c.id);
    (async () => {
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => setTimeout(r, 4000));
        const x = await api("/api/characters/" + c.id).catch((e) => (e.status === 404 ? { gone: true } : null));
        if (x?.gone) break;
        if (x && !x.pending) {
          bodyForget(c.id);
          await reloadChars();
          if (S.charId === c.id) bus.emit("character:changed");
          toast(x.behavior?.portrait ? t("{name} 的形象和声音好了", { name: x.name }) : t("{name} 的形象没画出来，可以在工作台里再画一次", { name: x.name }), 5000);
          break;
        }
      }
      watching.delete(c.id);
    })();
  }
}
bus.on("chars", watchPending);
bus.on("chars:loaded", watchPending);

async function draftForm(d) {
  const sc = await schema();
  const labels = Object.fromEntries(sc.fields.map((x) => [x.key, x.label]));
  const vc = await voiceConfig().catch(() => ({ tts: {} }));
  D.draft = d; D.voice = null; D.design = !!vc.tts?.design;
  const p = d.persona || {};
  const pron = p.pronoun || "TA";
  $("#gen-out").innerHTML = `
    <div class="draft-form">
      <p class="muted small">${t("这是角色的灵魂。建好之后就固定了（改了就不像本人了），所以现在想清楚、随便改。")}</p>
      ${d.sources?.length ? `<p class="muted small">${t("参考了这些资料：")}${d.sources.map((x) => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title || new URL(x.url).hostname)}</a>`).join("、")}</p>` : ""}
      ${DRAFT_FIELDS.map(([k, l, rows]) => rows === 1
        ? `<label>${t(l)}<input data-d="${k}" value="${esc(p[k] || "")}" maxlength="${k === "name" ? 40 : 80}"></label>`
        : `<label>${t(l)}<textarea data-d="${k}" rows="${rows}">${esc(p[k] || "")}</textarea></label>`).join("")}
      <label>${t("称呼")}<select data-d-pron>${PRONOUNS.map(([v, l]) => `<option value="${v}" ${v === pron ? "selected" : ""}>${esc(t(l))}</option>`).join("")}</select></label>
      <label>${t("外貌（用来画形象）")}<textarea data-d="appearance" rows="2">${esc(d.appearance || "")}</textarea></label>
      <label>${t("声音（描述想要的声音：性别年龄、音色、语速、情绪……）")}<textarea data-d-voice rows="2" placeholder="${t("例如：年轻男性，冷淡傲慢，语速偏慢，咬字清晰")}">${esc(d.behavior?.voice?.style || "")}</textarea></label>
      ${vc.tts?.design ? `<div class="row"><button class="ghost small" id="voice-design">▶ ${t("试听这个声音")}</button><span class="muted small" id="voice-design-note">${t("不满意就改描述再听一次；不试听也会按描述设计")}</span></div>` : ""}
      <details><summary>${t("更多设定（背景、价值观、兴趣、世界观、关系……）")}</summary>
        ${MORE_FIELDS.map((k) => `<label>${esc(tr(labels[k]))}<textarea data-d="${k}" rows="2">${esc(p[k] || "")}</textarea></label>`).join("")}
        <label>${t("风格")}<select data-d-style>${Object.keys(sc.styles).map((x) => `<option value="${esc(x)}" ${x === (d.behavior?.style || "温柔") ? "selected" : ""}>${esc(tr(x))}</option>`).join("")}</select></label>
      </details>
      <div class="row"><button id="draft-go">${t("创建角色")}</button><span class="muted small">${t("马上就能聊；形象和声音在后台做，大约一分钟，可以关掉窗口")}</span></div>
    </div>`;
}

document.addEventListener("click", async (e) => {  // 弹窗里的按钮（弹窗内容每次重画，用事件委托）
  if (e.target.id === "gen-go") {
    const prompt = $("#gen-prompt").value.trim();
    if (!prompt) return $("#gen-prompt").focus();
    e.target.disabled = true; $("#gen-out").innerHTML = `<p class="muted small">${t("正在查资料、写灵魂，十几秒到半分钟。可以先关掉这个窗口，写好了会告诉你")}</p>`;
    D.writing = prompt;
    try {
      const d = await api("/api/characters/generate", { body: { prompt } });
      const open = !$("#modal").classList.contains("hidden") && $("#gen-out");
      D.saved = { draft: d, prompt };
      if (open) { D.prompt = prompt; await draftForm(d); }
      else { toast(t("{name} 的灵魂写好了，点“新角色”接着看", { name: d.persona?.name || "" }), 6000); }
    } catch (err) {
      if ($("#gen-out") && !$("#modal").classList.contains("hidden")) $("#gen-out").innerHTML = `<p class="error">${esc(err.message)}</p>`; else fail(err);
    } finally { D.writing = ""; e.target.disabled = false; }
  }
  if (e.target.id === "gen-blank") { D.prompt = ""; await draftForm({ persona: {}, behavior: {}, lore: [], appearance: "" }); $("[data-d=name]")?.focus(); }
  if (e.target.id === "voice-design") {
    const style = $("[data-d-voice]").value.trim();
    if (!style) return $("[data-d-voice]").focus();
    const btn = e.target, note = $("#voice-design-note");
    btn.disabled = true; note.textContent = t("正在设计声音，几秒…");
    try {
      const res = await api("/api/voice/design", { body: { description: style, sample: $("[data-d=greeting]")?.value.trim() || "" }, raw: true });
      D.voice = { id: res.headers.get("x-voice-id"), style };
      const audio = new Audio(URL.createObjectURL(await res.blob()));
      note.textContent = t("这就是创建后的声音。不满意就改描述再听一次");
      audio.play().catch(() => {});
    } catch (err) { note.textContent = ""; fail(err); }
    finally { btn.disabled = false; }
  }
  if (e.target.id === "draft-go") {
    const d = D.draft || { persona: {}, behavior: {}, lore: [] };
    const persona = { ...(d.persona || {}) };
    $$("[data-d]").forEach((el) => { if (el.dataset.d !== "appearance") persona[el.dataset.d] = el.value.trim(); });
    if (!persona.name) { toast("先起个名字吧"); return $("[data-d=name]")?.focus(); }
    persona.pronoun = $("[data-d-pron]")?.value || "TA";
    const behavior = { ...(d.behavior || {}), style: $("[data-d-style]")?.value || d.behavior?.style || "温柔" };
    const vstyle = $("[data-d-voice]")?.value.trim() || "";
    behavior.voice = { ...(behavior.voice || {}), style: vstyle };
    if (D.voice && D.voice.style === vstyle) behavior.voice.voice = D.voice.id;  // 试听过、描述没改：就用这个声音，不再设计一次
    else if (vstyle && D.design) behavior.voice.voice = "";  // 描述改过：创建时按新描述设计
    const body = { draft: { persona, behavior, lore: d.lore || [], appearance: $("[data-d=appearance]").value.trim() }, prompt: D.prompt || "" };
    e.target.disabled = true; e.target.textContent = t("创建中…");
    try {  // 角色马上建好、窗口马上关；形象和声音在后台做，大约一分钟，好了会告诉你
      const { character: c } = await api("/api/workbench/character", { body });
      D.saved = null;
      $("#modal").classList.add("hidden");
      toast(c.pending ? t("{name} 建好了，可以先聊着。形象和声音在后台做，大约一分钟", { name: c.name }) : t("欢迎 {name}！", { name: c.name }), 5000);
      await reloadChars(c.id); bus.emit("select", { id: c.id, view: "chat" });
    } catch (err) { fail(err); e.target.disabled = false; e.target.textContent = t("创建角色"); }
  }
  if (e.target.id === "go-ws") { $("#modal").classList.add("hidden"); bus.emit("goto", "workshop"); }
});
document.addEventListener("change", async (e) => {
  if (e.target.id !== "imp-file" || !e.target.files[0]) return;
  const fd = new FormData(); fd.append("file", e.target.files[0]);
  try {
    const c = await api("/api/characters/import", { body: fd });
    $("#modal").classList.add("hidden"); toast(t("导入了：{name}", { name: c.name }));
    await reloadChars(c.id); bus.emit("select", { id: c.id, view: "persona" });
  } catch (err) { fail(err); }
});

// ---------- 更多：不常用的都在这里 ----------
async function moreMenu(c) {
  const v = await api(`/api/characters/${c.id}/versions`).catch(() => ({ versions: [] }));
  const p = modal("更多", `
    <div class="menu-list">
      <button data-m="exp-json">${t("导出人设（JSON）")}</button>
      <button data-m="exp-md">${t("导出人设（Markdown）")}</button>
      <button data-m="publish">${t("发布到工坊")}</button>
      ${v.versions.length ? `<button data-m="versions">${t("历史版本（{n}）", { n: v.versions.length })}</button>` : ""}
      ${c.official ? `<button data-m="reset">${t("还原为官方设定")}</button>` : ""}
      ${S.chars.length > 1 ? `<button data-m="bye" class="danger-link">${t("和她告别")}</button>` : ""}
    </div>
    <p class="muted small">${t("导出和发布都只包含人格设定，不含你们的私人记忆。")}</p>`, null, { okText: "关闭", cancel: false });
  $$("[data-m]", $("#modal-body")).forEach((b) => (b.onclick = async () => {
    const m = b.dataset.m;
    $("#modal").classList.add("hidden");
    try {
      if (m === "exp-json") return download(`/api/characters/${c.id}/export?format=json`, `${c.slug}.krino.json`);
      if (m === "exp-md") return download(`/api/characters/${c.id}/export?format=md`, `${c.slug}.md`);
      if (m === "publish") return bus.emit("publish", c.id);
      if (m === "versions") return versions(c, v);
      if (m === "reset" && await confirmBox("还原为官方设定", `<p>${t("当前版本会先存一份，可以在历史版本里找回。你们的记忆不受影响。")}</p>`, "还原")) {
        await api(`/api/characters/${c.id}/reset`, { method: "POST" }); toast("还原了");
      }
      if (m === "bye" && await confirmBox(t("和 {name} 告别", { name: c.name }), `<p>${t("她的设定、你们的记忆和聊天都会删除，不能恢复。想留着的话先导出。")}</p>`, "告别")) {
        await api(`/api/characters/${c.id}`, { method: "DELETE" }); await reloadChars(); return bus.emit("select", { id: S.chars[0].id, view: "persona" });
      }
      await reloadChars(); bus.emit("character:changed"); personaPage();
    } catch (e) { fail(e); }
  }));
  return p;
}

async function versions(c, v) {
  modal("历史版本", v.versions.map((x) => `<div class="ver"><b class="mono">v${x.version}</b> <span class="muted small">${fmtTime(x.saved_at)} · ${esc(tr(x.note))}</span>
      <button class="link small" data-ver="${x.version}">${t("恢复到这版")}</button></div>`).join(""), null, { okText: "关闭", cancel: false });
  $$("[data-ver]", $("#modal-body")).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/characters/${c.id}/versions/${b.dataset.ver}/restore`, { method: "POST" }); $("#modal").classList.add("hidden"); toast(t("恢复了 v{n}", { n: b.dataset.ver })); await reloadChars(); bus.emit("character:changed"); personaPage(); }
    catch (e) { fail(e); }
  }));
}

export const personaDirty = () => P.dirty || (!!P.c && S.view === "persona" && bodyDirty(P.c));
export function initPersona() {}


// 按人设设计的音色显示角色名；Kokoro 编号原样显示
const ROLE_VOICES = { dafeiyu: "大肥鱼的声音", krino: "KRINO 的声音" };
let VOICE_LABELS = {};  // 生成角色可选的音色说明（服务端给）
function voiceLabel(v) {
  const role = ROLE_VOICES[v.replace(/-(zh|en)$/, "")];
  return role ? t(role) : VOICE_LABELS[v] || v;
}

// 声音下拉：大家共用的音色 + 这个角色自己的专属声音（按描述设计的，只有它有）
function voiceOptions(tts, current) {
  const list = [...tts.voices];
  if (current && !list.includes(current) && /^v[0-9a-f]{10}-(zh|en)$/.test(current)) list.unshift(current);
  const cur = current || tts.default;
  return list.map((v) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(/^v[0-9a-f]{10}-/.test(v) ? t("专属声音（按描述设计）") : voiceLabel(v))}</option>`).join("");
}

function voiceNote(tts) {
  if (!tts.server) return t("现在用浏览器自带的朗读。");
  if (tts.provider === "local") return t("本地语音（Kokoro，{n} 个音色）。挑一个最像的。", { n: tts.voices.length });
  if (tts.design) return t("可以挑一个现成的声音，也可以写一句描述，设计一个只属于这个角色的声音。");
  return t("按人设描述生成的声音。");
}

