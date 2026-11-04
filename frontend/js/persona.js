// 02 人格编辑器：表单 / Markdown / JSON 三种编辑方式，版本、导入导出、描述生成、3D 形象选择、我的角色。
import { $, $$, S, api, avaHTML, bus, confirmBox, curChar, download, esc, fail, fmtTime, modal, toast } from "./core.js";

const P = { tab: "form", schema: null, char: null, dirty: false };

async function schema() {
  if (!P.schema) P.schema = await api("/api/persona-schema");
  return P.schema;
}

async function reloadChars(selectId) {
  S.chars = await api("/api/characters");
  bus.emit("chars", selectId);
}

// ---------- 表单 ----------
function formHTML(c, sc) {
  const p = c.persona, b = c.behavior;
  const f = (k, label, rows = 3) => `<label class="${rows > 3 ? "full" : ""}">${esc(label)}<textarea data-p="${k}" rows="${rows}">${esc(p[k] || "")}</textarea></label>`;
  const labels = Object.fromEntries(sc.fields.map((x) => [x.key, x.label]));
  return `<div class="editor-grid">
    <div class="panel">
      <div class="field-grid">
        <label>名称<input data-p="name" value="${esc(p.name)}" maxlength="40"></label>
        <label>主题色<input data-p="color" type="color" value="${esc(p.color || "#1414a8")}" style="height:40px;padding:2px"></label>
        <label class="full">简介<input data-p="tagline" value="${esc(p.tagline || "")}" maxlength="80"></label>
        ${f("background", labels.background, 4)}${f("personality", labels.personality)}${f("values", labels.values)}
        ${f("speech", labels.speech)}${f("interests", labels.interests)}${f("preferences", labels.preferences)}
        ${f("worldview", labels.worldview, 4)}${f("relationships", labels.relationships)}${f("boundaries", labels.boundaries)}
        ${f("greeting", labels.greeting, 2)}
        <label class="full">标签（逗号分隔）<input data-p="tags" value="${esc((p.tags || []).join("，"))}"></label>
      </div>
      <div class="section-title mono">LORE · 设定笔记</div>
      <div id="lore-list">${(c.lore || []).map(loreHTML).join("")}</div>
      <button class="ghost small" id="lore-add">新增一条设定</button>
    </div>
    <div>
      <div class="panel">
        <div class="section-title mono">BEHAVIOR · 互动风格</div>
        <label>风格预设<select data-b="style">${Object.keys(sc.styles).map((s) => `<option ${s === b.style ? "selected" : ""}>${s}</option>`).join("")}</select></label>
        ${Object.entries(sc.numeric).map(([k, label]) => `<div class="slider-row"><span>${esc(label)}</span><input type="range" min="0" max="1" step="0.05" data-b="${k}" value="${b[k]}"><span>${b[k]}</span></div>`).join("")}
        <label>默认表情<select data-b="default_expression">${sc.expressions.map((e) => `<option value="${e.id}" ${e.id === b.default_expression ? "selected" : ""}>${esc(e.label)}</option>`).join("")}</select></label>
        <div class="muted small">可以用的表情</div>
        <div class="pick-grid" id="pick-expr">${sc.expressions.map((e) => `<label><input type="checkbox" value="${e.id}" ${b.expressions.includes(e.id) ? "checked" : ""}>${esc(e.label)}</label>`).join("")}</div>
        <div class="muted small" style="margin-top:10px">可以做的预设动作</div>
        <div class="pick-grid" id="pick-anim">${sc.animations.map((a) => `<label><input type="checkbox" value="${a.id}" ${b.animations.includes(a.id) ? "checked" : ""}>${esc(a.label)}</label>`).join("")}</div>
        <div class="section-title mono">VOICE · 音色</div>
        <div class="slider-row"><span>语速</span><input type="range" min="0.5" max="2" step="0.05" data-v="rate" value="${b.voice.rate}"><span>${b.voice.rate}</span></div>
        <div class="slider-row"><span>音高</span><input type="range" min="0.5" max="2" step="0.05" data-v="pitch" value="${b.voice.pitch}"><span>${b.voice.pitch}</span></div>
        <label>音色名（服务端语音合成时使用，可留空）<input data-v="voice" value="${esc(b.voice.voice || "")}" maxlength="40"></label>
        <button class="ghost small" id="voice-try">试听</button>
      </div>
      <div class="panel" style="margin-top:14px" id="avatar-panel"></div>
    </div></div>`;
}

const loreHTML = (x) => `<div class="lore-item"><div class="row" style="margin-top:0"><input data-l="name" value="${esc(x.name)}" placeholder="名称" style="flex:1"><button class="link small danger-link" data-l-del>删除</button></div>
  <textarea data-l="content" rows="2" placeholder="设定内容">${esc(x.content)}</textarea></div>`;

function collectForm(root) {
  const persona = {};
  $$("[data-p]", root).forEach((el) => (persona[el.dataset.p] = el.value));
  persona.tags = persona.tags.split(/[,，\s]+/).filter(Boolean).slice(0, 8);
  const behavior = { style: $("[data-b=style]", root).value, default_expression: $("[data-b=default_expression]", root).value,
    expressions: $$("#pick-expr input:checked", root).map((x) => x.value), animations: $$("#pick-anim input:checked", root).map((x) => x.value),
    voice: { rate: +$("[data-v=rate]", root).value, pitch: +$("[data-v=pitch]", root).value, voice: $("[data-v=voice]", root).value } };
  $$("[data-b][type=range]", root).forEach((el) => (behavior[el.dataset.b] = +el.value));
  const lore = $$(".lore-item", root).map((el) => ({ name: $("[data-l=name]", el).value.trim(), content: $("[data-l=content]", el).value.trim() }))
    .filter((x) => x.name && x.content);
  return { persona, behavior, lore };
}

function bindForm(root, c, sc) {
  $$("input[type=range]", root).forEach((el) => (el.oninput = () => { el.nextElementSibling.textContent = el.value; P.dirty = true; }));
  root.addEventListener("input", () => (P.dirty = true));
  $("[data-b=style]", root).onchange = (e) => {  // 换风格时套用预设数值（之后还可以单独调）
    const preset = sc.styles[e.target.value];
    Object.keys(sc.numeric).forEach((k) => { const el = $(`[data-b=${k}]`, root); el.value = preset[k]; el.nextElementSibling.textContent = preset[k]; });
    $("[data-v=rate]", root).value = preset.voice.rate; $("[data-v=pitch]", root).value = preset.voice.pitch;
    P.dirty = true;
  };
  const bindLore = () => $$("[data-l-del]", root).forEach((b) => (b.onclick = () => { b.closest(".lore-item").remove(); P.dirty = true; }));
  bindLore();
  $("#lore-add", root).onclick = () => { $("#lore-list", root).insertAdjacentHTML("beforeend", loreHTML({ name: "", content: "" })); bindLore(); };
  $("#voice-try", root).onclick = async () => {
    const { speak } = await import("./voice.js");
    const v = collectForm(root).behavior.voice;
    speak($("[data-p=greeting]", root).value || "你好，我在这里。", v).catch(fail);
  };
  avatarPanel($("#avatar-panel", root), c);
}

// ---------- 3D 形象 ----------
async function avatarPanel(box, c) {
  const models = await api("/api/avatars").catch(() => []);
  box.innerHTML = `<div class="section-title mono">AVATAR · 3D 形象</div>
    <label>给 ${esc(c.name)} 用的模型<select id="av-pick"><option value="">默认形象（VRM 示例模型）</option>
      ${models.map((m) => `<option value="${m.id}" ${m.id === c.avatar_model_id ? "selected" : ""}>${esc(m.name)} · VRM ${esc(m.vrm_version)} · ${(m.size / 1048576).toFixed(1)}MB</option>`).join("")}</select></label>
    <div class="row"><input type="file" id="av-file" accept=".vrm" style="flex:1"><button class="ghost small" id="av-up">上传 VRM</button></div>
    <p class="muted small">只接受 .vrm（VRM 0.x / 1.0），不超过 40MB。请只上传你有权使用的模型；模型自带的作者和许可信息会显示在这里。</p>
    <div id="av-meta" class="small muted"></div>`;
  const showMeta = () => {
    const m = models.find((x) => x.id === $("#av-pick", box).value);
    $("#av-meta", box).innerHTML = m ? `作者：${esc((m.meta.authors || []).join("、") || "未知")} · 许可：${esc(m.meta.license || "未注明")}` : "默认形象：pixiv Inc. 的 VRM 示例模型（VRM Public License 1.0），模型加载失败时使用内置形象。";
  };
  showMeta();
  $("#av-pick", box).onchange = async (e) => {
    try { await api(`/api/characters/${c.id}/avatar`, { method: "PUT", body: { model_id: e.target.value || null } }); await reloadChars(); bus.emit("character:changed"); toast("换好了"); showMeta(); }
    catch (err) { fail(err); }
  };
  $("#av-up", box).onclick = async () => {
    const f = $("#av-file", box).files[0];
    if (!f) return toast("先选一个 .vrm 文件");
    const fd = new FormData(); fd.append("file", f);
    try {
      const m = await api("/api/avatars", { body: fd });
      await api(`/api/characters/${c.id}/avatar`, { method: "PUT", body: { model_id: m.id } });
      await reloadChars(); bus.emit("character:changed"); toast("上传好了：" + m.name); avatarPanel(box, curChar());
    } catch (e) { fail(e); }
  };
}

// ---------- 源文件编辑 ----------
async function sourceHTML(fmt) {
  const src = await api(`/api/characters/${S.charId}/source?format=${fmt}`);
  return `<div class="panel"><p class="muted small">${fmt === "md"
    ? "frontmatter 里是名称、标签和互动风格（behavior）；“## 小标题”分段对应各个字段；“## 设定笔记 · 名称”是设定笔记。"
    : "krino-persona/1 人设包：persona 是人格字段，behavior 是互动风格，lore 是设定笔记。"} 保存前会校验，格式不对不会覆盖。</p>
    <textarea id="src" class="source-editor" spellcheck="false">${esc(src.text)}</textarea></div>`;
}

// ---------- 页面 ----------
export async function personaPage() {
  const body = $("#persona-body");
  $$("#persona-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.ptab === P.tab));
  if (P.tab === "cast") return castPage(body);
  const [c, sc] = await Promise.all([api("/api/characters/" + S.charId), schema()]).catch((e) => (fail(e), []));
  if (!c) return;
  P.char = c; P.dirty = false;
  $("#persona-ver").textContent = `v${c.version}${c.official ? " · 官方" : ""}`;
  body.innerHTML = (P.tab === "form" ? formHTML(c, sc) : await sourceHTML(P.tab)) + `
    <div class="sticky-bar">
      <button id="p-save">保存</button>
      <button class="ghost" id="p-versions">历史版本</button>
      ${c.official ? '<button class="ghost" id="p-reset">还原为官方设定</button>' : ""}
      <span class="grow"></span>
      <button class="ghost small" data-exp="json">导出 JSON</button><button class="ghost small" data-exp="md">导出 Markdown</button>
      <span id="p-msg" class="muted small"></span>
    </div>`;
  if (P.tab === "form") bindForm(body, c, sc);
  else $("#src").oninput = () => (P.dirty = true);
  $("#p-save").onclick = save;
  $("#p-versions").onclick = versions;
  if ($("#p-reset")) $("#p-reset").onclick = async () => {
    if (!(await confirmBox("还原为官方设定", "<p>当前版本会先存一份，之后可以从历史版本恢复。你们的记忆不受影响。</p>", "还原"))) return;
    await api(`/api/characters/${c.id}/reset`, { method: "POST" }).catch(fail);
    await reloadChars(); personaPage();
  };
  $$("[data-exp]").forEach((b) => (b.onclick = () => download(`/api/characters/${c.id}/export?format=${b.dataset.exp}`,
    `${c.slug}.${b.dataset.exp === "md" ? "md" : "krino.json"}`)));
}

async function save() {
  const msg = $("#p-msg");
  try {
    let c;
    if (P.tab === "form") c = await api(`/api/characters/${S.charId}`, { method: "PUT", body: collectForm($("#persona-body")) });
    else c = await api(`/api/characters/${S.charId}/source`, { method: "PUT", body: { format: P.tab, text: $("#src").value } });
    P.dirty = false;
    toast(c.version === P.char.version ? "没有改动" : `已保存为 v${c.version}，下一句话起生效`);
    await reloadChars(); bus.emit("character:changed"); personaPage();
  } catch (e) { msg.textContent = e.message; msg.className = "error small"; }
}

async function versions() {
  const v = await api(`/api/characters/${S.charId}/versions`).catch(fail);
  if (!v) return;
  const html = v.versions.length ? v.versions.map((x) => `<div class="ver"><b class="mono">v${x.version}</b> <span class="muted small">${fmtTime(x.saved_at)} · ${esc(x.note)}</span>
      <button class="link small" data-ver="${x.version}">恢复到这版</button>
      <details><summary class="small muted">看内容</summary><pre class="small">${esc(x.preview)}</pre></details></div>`).join("")
    : '<p class="muted">还没有历史版本。</p>';
  modal("历史版本", `<p class="muted small">当前是 v${v.current}。恢复也会先把现在的版本存一份。</p>${html}`, null, { okText: "关闭", cancel: false, wide: true });
  $$("[data-ver]", $("#modal-body")).forEach((b) => (b.onclick = async () => {
    try { await api(`/api/characters/${S.charId}/versions/${b.dataset.ver}/restore`, { method: "POST" }); toast("恢复了 v" + b.dataset.ver); $("#modal-ok").click(); await reloadChars(); bus.emit("character:changed"); personaPage(); }
    catch (e) { fail(e); }
  }));
}

// ---------- 我的角色：列表、新建（描述生成 / 空白）、导入 ----------
async function castPage(body) {
  S.chars = await api("/api/characters");
  body.innerHTML = `<div class="char-cards">${S.chars.map((c) => `<div class="lib-card" style="--c:${esc(c.color)}">
      ${avaHTML(c, "lg")}<h3>${esc(c.name)} <span class="ai-badge">AI</span> ${c.official ? '<span class="badge cobalt">官方</span>' : ""}</h3>
      <p class="muted">${esc(c.tagline)}</p>
      <p class="small muted mono">${esc(c.style)} · v${c.version}${c.workshop ? (c.workshop.own ? " · 已发布" : " · 来自工坊") : ""}</p>
      <div class="row"><button class="small" data-use="${c.id}">和她互动</button><button class="ghost small" data-edit="${c.id}">编辑</button>
        ${S.chars.length > 1 ? `<button class="link small danger-link" data-bye="${c.id}">告别</button>` : ""}</div></div>`).join("")}
    ${S.chars.length < (S.me?.companion_limit || 8) ? `<button class="lib-card adopt-card" id="c-new"><span>＋</span>新建角色<em class="mono">${S.chars.length} / ${S.me?.companion_limit}</em></button>` : ""}</div>
    <div class="editor-grid">
      <div class="panel"><div class="section-title mono">CREATE · 描述生成</div>
        <label>描述你想要的角色<textarea id="gen-prompt" rows="4" maxlength="800" placeholder="身份、外貌、性格、你们怎么相处……例如：在海边书店打工的抹香鲸娘，话少，喜欢在打烊后给我念书。"></textarea></label>
        <div class="row"><select id="gen-style" style="width:auto"><option value="">风格交给她</option>${Object.keys((await schema()).styles).map((s) => `<option>${s}</option>`).join("")}</select>
          <span class="grow"></span><button id="gen-go">生成草稿</button></div>
        <div id="gen-out"></div></div>
      <div class="panel"><div class="section-title mono">IMPORT · 导入人设</div>
        <form id="import-form" class="dropzone"><input type="file" id="import-file" accept=".json,.md,.png,.charx,.zip">
          <div class="dz-inner"><div class="dz-title">把人设文件拖到这里</div><div class="muted small">.krino.json / .md / SillyTavern 角色卡（.json / .png）/ RisuAI .charx / 旧版鲸鱼娘人设包 .zip</div><div id="import-name" class="mono small"></div></div></form>
        <p class="muted small">导入前会先给你看字段怎么对应。文件里的内容只当作资料，不会被当成指令或脚本执行；卡里的系统指令不会导入。不支持露骨内容和真实人物。</p></div>
    </div>`;
  $$("[data-use]", body).forEach((b) => (b.onclick = () => bus.emit("select", { id: b.dataset.use, view: "chat" })));
  $$("[data-edit]", body).forEach((b) => (b.onclick = () => { P.tab = "form"; bus.emit("select", { id: b.dataset.edit, view: "persona" }); }));
  $$("[data-bye]", body).forEach((b) => (b.onclick = async () => {
    const c = S.chars.find((x) => x.id === b.dataset.bye);
    if (!(await confirmBox(`和 ${c.name} 告别`, "<p>她的人格配置、你们之间的记忆、聊天记录和关系都会删除，不能恢复。</p><p class='muted small'>想留着的话，先在“编辑”里导出人设，在“记忆”里导出你们的记忆。</p>", "告别"))) return;
    try { await api(`/api/characters/${c.id}`, { method: "DELETE" }); await reloadChars(); castPage(body); } catch (e) { fail(e); }
  }));
  const nb = $("#c-new", body);
  if (nb) nb.onclick = () => $("#gen-prompt").focus();
  $("#gen-go").onclick = () => generate();
  const dz = $("#import-form");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.add("over")));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, () => dz.classList.remove("over")));
  $("#import-file").onchange = (e) => { const f = e.target.files[0]; if (f) importFile(f); e.target.value = ""; };
}

async function generate() {
  const prompt = $("#gen-prompt").value.trim();
  if (!prompt) return $("#gen-prompt").focus();
  $("#gen-go").disabled = true;
  $("#gen-out").innerHTML = '<p class="muted small mono">DRAWING…</p>';
  try {
    const d = await api("/api/characters/generate", { body: { prompt, style: $("#gen-style").value || null } });
    $("#gen-out").innerHTML = `<div class="ver"><b>${esc(d.persona.name)}</b> <span class="badge">${esc(d.behavior.style)}</span><p class="muted">${esc(d.persona.tagline)}</p>
      <details><summary class="small muted">看草稿</summary><pre class="small">${esc(JSON.stringify(d.persona, null, 1))}</pre></details>
      <div class="row"><button id="gen-save">收下这位角色</button><button class="ghost" id="gen-retry">重新生成</button></div><p class="muted small">收下后可以在编辑器里继续改。</p></div>`;
    $("#gen-retry").onclick = generate;
    $("#gen-save").onclick = async () => {
      try { const c = await api("/api/characters", { body: d }); toast("欢迎 " + c.name); await reloadChars(); bus.emit("select", { id: c.id, view: "persona" }); }
      catch (e) { fail(e); }
    };
  } catch (e) { $("#gen-out").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  finally { $("#gen-go").disabled = false; }
}

async function importFile(file) {
  const fd = new FormData(); fd.append("file", file);
  let pv;
  try { pv = await api("/api/characters/import/preview", { body: fd }); } catch (e) { return fail(e); }
  const rows = pv.fields.map((f) => `<tr><td class="mono small">${esc(f.source)}</td><td>→ ${esc(f.label)}</td><td class="muted small">${esc(f.preview)}</td></tr>`).join("");
  const html = `<p><b>${esc(pv.name)}</b> <span class="badge">${esc(pv.format)}</span></p>
    <table class="map">${rows}</table>
    ${pv.missing.length ? `<p class="muted small">没有对应内容：${esc(pv.missing.join("、"))}（之后可以补）</p>` : ""}
    ${pv.unknown.length ? `<p class="small">没认出来的：</p><ul class="small">${pv.unknown.map((u) => `<li>${esc(u.field)} — ${esc(u.action)}</li>`).join("")}</ul>` : ""}
    ${pv.warnings.length ? `<ul class="small warn-list">${pv.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
    ${pv.lore.length ? `<p class="muted small">设定笔记：${esc(pv.lore.join("、"))}</p>` : ""}`;
  await modal("导入人设", html, async () => {
    const f2 = new FormData(); f2.append("file", file);
    const c = await api("/api/characters/import", { body: f2 });
    toast("导入了：" + c.name); await reloadChars(); bus.emit("select", { id: c.id, view: "persona" });
    return true;
  }, { okText: "导入", wide: true });
}

export function initPersona() {
  $$("#persona-tabs button").forEach((b) => (b.onclick = async () => {
    if (P.dirty && !(await confirmBox("还没保存", "<p>切换会丢掉没保存的修改。</p>", "不要了"))) return;
    P.tab = b.dataset.ptab; personaPage();
  }));
}
export const personaDirty = () => P.dirty;
