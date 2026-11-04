// 04 设置：常用的只有几个开关，改了立刻生效（不用点保存）。技术细节都收在“高级”里。
import { $, $$, S, api, esc, fail, modal, t, toast, tr } from "./core.js";
import { glassesPanel } from "./glasses.js";

async function save(patch) {
  try { S.me = await api("/api/me", { method: "PATCH", body: patch }); toast("已保存", 1200); }
  catch (e) { fail(e); }
}

export async function settingsPage() {
  const s = S.me.settings;
  const sw = (group, key, label, hint = "") => `<label class="switch"><input type="checkbox" data-g="${group}" data-k="${key}" ${s[group]?.[key] ? "checked" : ""}>
    <span>${t(label)}${hint ? `<small>${t(hint)}</small>` : ""}</span></label>`;
  $("#settings-page").innerHTML = `<div class="settings-simple">
    <label>${t("显示名")}<input id="s-name" value="${esc(S.me.display_name || "")}" maxlength="32"></label>
    ${sw("voice", "autoplay", "语音输入后自动朗读她的回复")}
    ${sw("interaction", "proactive", "你安静时，她偶尔会主动一下", "多数时候只是一个小动作；开口至少隔 5 分钟")}
    ${sw("interaction", "animations", "允许她做动作（挥手、点头……）")}
    ${sw("interaction", "stories", "允许她讲幻想故事")}
    ${sw("privacy", "camera", "允许她看摄像头画面", "每次仍需浏览器授权，画面不保存")}
    <label class="switch"><input type="checkbox" id="s-sens" ${s.save_sensitive ? "checked" : ""}><span>${t("允许她记住私密的事")}<small>${t("健康、财务等总会先问你")}</small></span></label>
    <details id="adv"><summary>${t("高级")}</summary><div id="adv-body"><p class="muted small">${t("加载中…")}</p></div></details>
    <div class="row"><button class="link small danger-link" id="s-delete">${t("注销账号")}</button></div></div>`;
  let timer; $("#s-name").oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => save({ display_name: e.target.value }).then(() => ($("#me-name").textContent = S.me.display_name)), 600); };
  $$("[data-g]").forEach((el) => (el.onchange = () => save({ [el.dataset.g]: { [el.dataset.k]: el.checked } })));
  $("#s-sens").onchange = (e) => save({ save_sensitive: e.target.checked });
  $("#adv").ontoggle = (e) => e.target.open && advanced();
  $("#s-delete").onclick = deleteAccount;
}

async function advanced() {
  const [svc, status] = await Promise.all([api("/api/services"), api("/api/status")]).catch((e) => (fail(e), []));
  if (!svc) return;
  const pol = svc.policy;
  $("#adv-body").innerHTML = `
    <div class="section-title mono">MODEL SERVICES</div>
    ${["llm", "vlm", "stt", "tts"].map((k) => { const x = svc[k]; return `<div class="svc"><b>${k.toUpperCase()}</b><span>${esc(x.provider)}${x.model ? " · " + esc(tr(x.model)) : ""}<br><span class="muted small">${esc(tr(x.note))}</span></span>
      <span class="${x.ready ? "ok-txt" : "err-txt"} small">${x.ready ? t("就绪") : t("未配置")}</span></div>`; }).join("")}
    <p class="muted small">${t("地址和密钥在服务器的 .env 里配置，浏览器拿不到密钥。")}</p>

    <div class="section-title mono">KRINO EVALUATOR · ${t("互动策略")}</div>
    <div class="row"><select id="s-pol" style="width:auto">${[[null, t("跟随服务器（{mode}）", { mode: pol.server_default })], ["rules", t("规则策略")], ["matrix", t("Matrix 模型（实验）")], ["off", t("关闭")]]
      .map(([v, l]) => `<option value="${v ?? ""}" ${(S.me.settings.evaluator.mode ?? "") === (v ?? "") ? "selected" : ""}>${l}</option>`).join("")}</select>
      <button class="ghost small" id="s-test">${t("测试")}</button></div>
    <p class="muted small">${esc(tr(pol.label))}. Matrix: ${pol.matrix.available ? t("可用") : esc(tr(pol.matrix.reason))}（${esc(tr(pol.matrix.note))}）</p>
    <div id="s-test-out"></div>

    <div class="section-title mono">KRINO GLASSES · ${t("眼镜模拟器")}</div>
    <div id="glasses-panel"></div>

    <div class="section-title mono">STATUS</div>
    <table class="res"><tr><th>${t("接口")}</th><th>${t("次数")}</th><th>P50</th><th>P95</th></tr>
      ${status.latency.slice(0, 6).map((r) => `<tr><td class="mono">${esc(r.route)}</td><td>${r.count}</td><td>${r.p50_ms}ms</td><td>${r.p95_ms}ms</td></tr>`).join("")}</table>
    ${status.errors.length ? `<div class="ev-log">${status.errors.map((e) => `<div class="err">${esc(e.at)} ${esc(e.where)} ${esc(e.message)}</div>`).join("")}</div>` : `<p class="muted small">${t("最近没有服务错误。")}</p>`}
    <label class="switch"><input type="checkbox" id="s-dev" ${S.me.dev ? "checked" : ""}><span>${t("开发者视图")}<small>${t("每条回复下显示策略打分")}</small></span></label>`;
  $("#s-pol").onchange = (e) => save({ evaluator: { mode: e.target.value || null } });
  $("#s-dev").onchange = (e) => { S.me.dev = e.target.checked; try { localStorage.setItem("krino_dev", e.target.checked ? "1" : ""); } catch { /* */ } };
  $("#s-test").onclick = async () => {
    $("#s-test-out").innerHTML = `<p class="muted small">${t("测试中…")}</p>`;
    try {
      const r = await api("/api/policy/test", { body: { character_id: S.charId } });
      $("#s-test-out").innerHTML = `<table class="res"><tr><th>${t("场景")}</th><th>${t("选择")}</th><th>${t("原因")}</th></tr>
        ${r.results.map((x) => `<tr><td>${esc(tr(x.scenario))}</td><td class="mono">${esc(x.actions.join(" + "))}</td><td class="muted">${esc(tr(x.primary_reason))}${x.note ? " · " + esc(tr(x.note)) : ""}</td></tr>`).join("")}</table>`;
    } catch (e) { $("#s-test-out").innerHTML = `<p class="error small">${esc(tr(e.message))}</p>`; }
  };
  glassesPanel($("#glasses-panel"));
}

async function deleteAccount() {
  const pw = await modal("注销账号", `<p>${t("你的角色、记忆、聊天和发布的作品都会删除，不能恢复。")}</p><label>${t("输入密码确认")}<input type="password" id="del-pw"></label>`,
    (b) => $("#del-pw", b).value || false, { okText: "注销" });
  if (!pw) return;
  try { await api("/api/me", { method: "DELETE", body: { password: pw } }); toast("账号已注销"); location.reload(); }
  catch (e) { fail(e); }
}
