// 06 设置：模型服务状态（只显示配没配，不显示密钥）、语音与互动偏好、隐私、KRINO Evaluator、眼镜连接、运行状态。
import { $, $$, S, api, esc, fail, toast } from "./core.js";

const SVC_NAME = { llm: "LLM", vlm: "VLM", stt: "STT", tts: "TTS" };

async function save(patch) {
  try { S.me = await api("/api/me", { method: "PATCH", body: patch }); toast("已保存"); }
  catch (e) { fail(e); }
}

export async function settingsPage() {
  const [svc, status] = await Promise.all([api("/api/services"), api("/api/status")]).catch((e) => (fail(e), []));
  if (!svc) return;
  const s = S.me.settings, pol = svc.policy;
  const chk = (group, key, label, hint = "") => `<label class="inline"><input type="checkbox" data-g="${group}" data-k="${key}" ${s[group]?.[key] ? "checked" : ""}> ${label}</label>${hint ? `<p class="muted small" style="margin:0 0 6px 24px">${hint}</p>` : ""}`;
  const sel = (group, key, opts) => `<select data-g="${group}" data-k="${key}" style="width:auto">${opts.map(([v, l]) => `<option value="${v ?? ""}" ${(s[group]?.[key] ?? "") === (v ?? "") ? "selected" : ""}>${l}</option>`).join("")}</select>`;
  $("#settings-page").innerHTML = `<div class="settings-grid">
    <div class="panel"><div class="section-title mono">PROFILE</div>
      <label>显示名<input id="s-name" value="${esc(S.me.display_name || "")}" maxlength="32"></label>
      <div class="row"><button class="small" id="s-name-save">保存</button></div></div>

    <div class="panel"><div class="section-title mono">MODEL SERVICES · 模型服务</div>
      ${Object.entries(SVC_NAME).map(([k, n]) => { const x = svc[k]; return `<div class="svc"><b>${n}</b><span>${esc(x.provider)}${x.model ? " · " + esc(x.model) : ""}<br><span class="muted small">${esc(x.note)}</span></span>
        <span class="${x.ready ? "ok-txt" : "err-txt"} small">${x.ready ? "就绪" : "未配置"}</span></div>`; }).join("")}
      <p class="muted small">服务地址和密钥在服务器的 .env 里配置（见 .env.example），浏览器拿不到密钥。</p></div>

    <div class="panel"><div class="section-title mono">VOICE · 语音</div>
      <label>语音识别 ${sel("voice", "stt", [["auto", "自动（服务端优先）"], ["browser", "浏览器自带"], ["server", "服务端"], ["off", "关闭"]])}</label>
      <label>语音朗读 ${sel("voice", "tts", [["auto", "自动（服务端优先）"], ["browser", "浏览器自带"], ["server", "服务端"], ["off", "关闭"]])}</label>
      ${chk("voice", "autoplay", "语音模式下自动朗读她的回复")}
      <p class="muted small">角色的音色（语速、音高、音色名）在“人格 → 表单 → 音色”里按角色设置。</p></div>

    <div class="panel"><div class="section-title mono">INTERACTION · 互动偏好</div>
      ${chk("interaction", "proactive", "允许她在你安静时偶尔主动一下", "多数时候只是一个小动作；主动开口至少隔 5 分钟。")}
      <label>多久没动静算“安静”（秒）<input type="number" min="10" max="3600" data-g="interaction" data-k="idle_seconds" value="${s.interaction.idle_seconds}" style="width:120px"></label>
      ${chk("interaction", "animations", "允许预设动作（挥手、点头……）")}
      ${chk("interaction", "stories", "允许幻想剧情")}</div>

    <div class="panel"><div class="section-title mono">PRIVACY · 数据与隐私</div>
      ${chk("privacy", "camera", "允许角色请求摄像头画面", "每次打开摄像头仍需要浏览器授权；画面只用于这一轮理解，不保存。")}
      ${chk("privacy", "microphone", "允许眼镜模拟器使用麦克风")}
      <label class="inline"><input type="checkbox" id="s-sens" ${s.save_sensitive ? "checked" : ""}> 允许把我确认过的私密记忆用于聊天</label>
      <p class="muted small" style="margin:0 0 6px 24px">健康、财务、证件、联系方式等私密信息总是先放进“想问你的”，你点头才会记。</p>
      <p class="muted small">所有数据保存在这台服务器的数据库里。每个角色的私人记忆互相隔离；导出人设、发布到创意工坊都不包含私人记忆。你可以在“记忆”里随时导出或删除。</p></div>

    <div class="panel"><div class="section-title mono">KRINO EVALUATOR · 互动策略</div>
      <label>策略 ${sel("evaluator", "mode", [[null, `跟随服务器（${pol.server_default}）`], ["rules", "规则策略"], ["matrix", "Matrix 3-Head 模型（实验）"], ["off", "关闭：只回应，不做额外动作"]])}</label>
      <div class="kv"><span>当前</span><span>${esc(pol.label)}</span>
        <span>Matrix 模型</span><span class="${pol.matrix.available ? "ok-txt" : "warn-txt"}">${pol.matrix.available ? `可用 · ${esc(pol.matrix.checkpoint)}${pol.matrix.loaded ? " · 已加载" : ""}` : esc(pol.matrix.reason)}</span></div>
      <p class="muted small">${esc(pol.matrix.note)}。规则策略的输出标注为“规则策略（非模型输出）”。</p>
      <div class="row"><button class="ghost small" id="s-test">测试当前策略</button></div><div id="s-test-out"></div></div>

    <div class="panel"><div class="section-title mono">KRINO GLASSES</div>
      ${(status.device.adapters || []).map((a) => `<div class="svc"><b>${a.available ? '<span class="ok-txt">可用</span>' : '<span class="muted">预留</span>'}</b><span>${esc(a.label)}</span><span class="muted small">${esc(a.note || "")}</span></div>`).join("")}
      <p class="small">连接中的设备：${status.device.devices.length ? status.device.devices.map((d) => `${esc(d.label)}（${esc(d.state)}）`).join("、") : "无"}</p>
      <p class="muted small">真机 SDK 接入前，请用“眼镜”页的模拟器验证摄像头 / 麦克风输入和 AR 输出。</p></div>

    <div class="panel"><div class="section-title mono">STATUS · 运行状态</div>
      <div class="kv"><span>运行</span><span>${Math.round(status.uptime_s / 60)} 分钟</span>
        <span>24 小时事件</span><span>${Object.entries(status.events_24h).map(([k, v]) => `${esc(k)} ${v}`).join(" · ") || "—"}</span></div>
      <table class="res" style="margin-top:8px"><tr><th>接口</th><th>次数</th><th>P50</th><th>P95</th></tr>
        ${status.latency.slice(0, 8).map((r) => `<tr><td class="mono">${esc(r.route)}</td><td>${r.count}</td><td>${r.p50_ms}ms</td><td>${r.p95_ms}ms</td></tr>`).join("")}</table>
      ${status.errors.length ? `<div class="section-title mono">ERRORS</div><div class="ev-log">${status.errors.map((e) => `<div class="err">${esc(e.at)} ${esc(e.where)} ${esc(e.message)}</div>`).join("")}</div>` : '<p class="muted small">最近没有服务错误。</p>'}
      <label class="inline" style="margin-top:10px"><input type="checkbox" id="s-dev" ${S.me.dev ? "checked" : ""}> 开发者视图：每条回复下显示策略的候选与打分、用到的记忆</label></div>
  </div>`;

  $("#s-name-save").onclick = () => save({ display_name: $("#s-name").value }).then(() => ($("#me-name").textContent = S.me.display_name));
  $$("[data-g]").forEach((el) => (el.onchange = () => {
    const v = el.type === "checkbox" ? el.checked : el.type === "number" ? +el.value : (el.value || null);
    save({ [el.dataset.g]: { [el.dataset.k]: v } }).then(() => el.dataset.g === "evaluator" && settingsPage());
  }));
  $("#s-sens").onchange = (e) => save({ save_sensitive: e.target.checked });
  $("#s-dev").onchange = (e) => { S.me.dev = e.target.checked; try { localStorage.setItem("krino_dev", e.target.checked ? "1" : ""); } catch { /* */ } toast(e.target.checked ? "开发者视图已打开" : "已关闭"); };
  $("#s-test").onclick = async () => {
    $("#s-test-out").innerHTML = '<p class="muted small">测试中…（第一次用 Matrix 模型需要加载，可能要十几秒）</p>';
    try {
      const r = await api("/api/policy/test", { body: { character_id: S.charId } });
      $("#s-test-out").innerHTML = `<p class="small">${esc(r.label)}${r.experimental ? " · 实验输出，不代表效果" : ""}</p><table class="res"><tr><th>场景</th><th>选择</th><th>原因 / 被挡住的</th><th>耗时</th></tr>
        ${r.results.map((x) => `<tr><td>${esc(x.scenario)}</td><td class="mono">${esc(x.actions.join(" + "))}</td><td class="muted">${esc(x.primary_reason)}${Object.keys(x.blocked).length ? " · ✗ " + esc(Object.entries(x.blocked).map(([k, v]) => `${k}：${v}`).join("；")) : ""}${x.note ? " · " + esc(x.note) : ""}</td><td>${x.latency_ms}ms</td></tr>`).join("")}</table>`;
    } catch (e) { $("#s-test-out").innerHTML = `<p class="error small">${esc(e.message)}</p>`; }
  };
}
