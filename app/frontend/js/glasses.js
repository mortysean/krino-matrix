// KRINO GLASSES 模拟器（在“设置 → 高级”里）。浏览器当作一副眼镜，连接、AR 显示、朗读都在 glassesclient.js（和 Windows 桌面测试版共用）。
// 这里是模拟器页面：镜片、滑杆和鼠标拖动模拟转头、“把她放在这里”、文字 / 麦克风 / 摄像头输入、事件日志。
// 摄像头和麦克风只在你点了按钮、浏览器授权后才打开；离开这个页面或断开时立即关闭。
import { $, $$, S, api, bus, curChar, esc, fail, t, toast, tr } from "./core.js";
import { canHear, listen, record, sttAvailable } from "./voice.js";
import { createGlassesClient, frameFrom } from "./glassesclient.js";
import { getLocale } from "./i18n.js";

const G = { client: null, stream: null, log: [], listening: null, st: { state: "disconnected" } };

function log(dir, text) {
  G.log.unshift({ dir, text, at: new Date().toLocaleTimeString(getLocale() === "en" ? "en-US" : "zh-CN") });
  G.log = G.log.slice(0, 80);
  const box = $("#ev-log");
  if (box) box.innerHTML = G.log.map((x) => `<div class="${x.dir}">${x.at} ${x.dir === "in" ? "→" : x.dir === "out" ? "←" : "!"} ${esc(x.text)}</div>`).join("");
}

// ---------- 摄像头 ----------
async function startCamera() {
  if (!S.me?.settings?.privacy?.camera) {
    toast("请先在“设置 → 隐私”里允许摄像头", 4000);
    return;
  }
  try {
    G.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 400 }, audio: false });
    const v = $("#lens-video");
    v.srcObject = G.stream; v.classList.remove("hidden"); await v.play();
    log("in", "camera on");
    renderState();
  } catch (e) { fail(e.name === "NotAllowedError" ? new Error(t("没有摄像头权限：请在浏览器地址栏允许")) : e); }
}

function stopCamera() {
  G.stream?.getTracks().forEach((x) => x.stop());
  G.stream = null;
  const v = $("#lens-video"); if (v) { v.srcObject = null; v.classList.add("hidden"); }
  renderState();
}

// ---------- 页面 ----------
function renderState() {
  const st = $("#g-state");
  if (!st) return;
  const s = G.st, state = s.state;
  const label = t({ connected: "已连接", connecting: "连接中…", stale: "心跳超时", disconnected: "未连接" }[state] || state);
  st.innerHTML = `<span class="${state === "connected" ? "ok-txt" : state === "disconnected" ? "err-txt" : "warn-txt"}">● ${label}</span>${s.busy ? ` <span class="muted">· ${t("她在想…")}</span>` : ""}`;
  $("#g-connect").textContent = G.client?.connected || state === "connecting" ? t("断开") : t("连接模拟器");
  $("#g-cam").textContent = G.stream ? t("关闭摄像头") : t("打开摄像头");
  const p = s.pose || { yaw: 0, pitch: 0 };
  $("#lens-hud").textContent = `KRINO GLASSES SIM · ${state.toUpperCase()} · CAM ${G.stream ? "ON" : "SIM"} · YAW ${p.yaw}° PITCH ${p.pitch}°`;
  $$("[data-pose]").forEach((el) => { const v = p[el.dataset.pose] ?? 0; if (+el.value !== v) el.value = v; el.nextElementSibling.textContent = v + "°"; });
  const caps = s.device?.capabilities || {};
  $("#g-caps").innerHTML = [["camera", "摄像头"], ["microphone", "麦克风"], ["speaker", "扬声器"], ["ar_display", "AR 显示"], ["imu", "头部姿态"]]
    .map(([k, l]) => `<span class="${caps[k] ? "on" : ""}">${caps[k] ? "✓" : "·"} ${t(l)}</span>`).join("") + `<span class="${state === "connected" ? "on" : ""}">${state === "connected" ? "✓" : "·"} ${t("连接状态")}</span>`;
}

export async function glassesPanel(host) {
  leaveGlasses();
  const c = curChar();
  const st = await api("/api/devices").catch(() => ({ adapters: [] }));
  host.innerHTML = `<div class="glasses">
    <div>
      <div class="lens" id="lens" title="${t("拖动画面 = 转头")}">
        <div class="lens-bg"></div><video id="lens-video" class="hidden" muted playsinline></video>
        <div class="ar-avatar" id="ar-avatar"></div>
        <div class="reticle"></div><div class="hud" id="lens-hud"></div>
      </div>
      <input id="g-text" class="g-text" placeholder="${t("对着眼镜说一句话，回车发送")}">
      <div class="row">
        <button class="ghost" id="g-mic">${t("用麦克风说")}</button><button id="g-say">${t("发送")}</button>
        <label class="small muted" style="margin-left:auto"><input type="checkbox" id="g-speak" checked> ${t("眼镜扬声器朗读")}</label>
      </div>
      <div class="row">
        <button class="ghost" id="g-cam">${t("打开摄像头")}</button>
        <input id="g-q" placeholder="${t("想问她看到了什么（可选）")}" style="flex:1"><button id="g-frame">${t("分享眼前的画面")}</button>
      </div>
      <div class="panel" style="margin-top:12px">
        <div class="section-title mono">HEAD POSE · ${t("头部姿态（模拟 IMU）")}</div>
        <div class="slider-row"><span>${t("左右转头")} yaw</span><input type="range" min="-180" max="180" value="0" data-pose="yaw"><span>0°</span></div>
        <div class="slider-row"><span>${t("抬头低头")} pitch</span><input type="range" min="-45" max="45" value="0" data-pose="pitch"><span>0°</span></div>
        <div class="slider-row"><span>${t("歪头")} roll</span><input type="range" min="-30" max="30" value="0" data-pose="roll"><span>0°</span></div>
        <div class="row"><button class="ghost small" id="g-place">${t("把她放在我正看着的地方")}</button><button class="ghost small" id="g-center">${t("回正")}</button></div>
        <p class="muted small">${t("她待在房间里的一个位置上，不跟着你的头转：转头时她在镜片里反向移动，转出视野就只剩边上的箭头。她要说话时你没在看她，会走到你眼前。也可以直接拖动镜片画面来转头。")}</p>
      </div>
    </div>
    <div>
      <div class="panel">
        <div class="section-title mono">${t("DEVICE · 设备")}</div>
        <div id="g-state"></div>
        <p class="small muted">${t("当前角色：{name}（AI）。设备输入会进入和她的当前会话。", { name: esc(c?.name || "") })}</p>
        <div class="row"><button id="g-connect">${t("连接模拟器")}</button><button class="ghost small" id="g-test">${t("发送测试 AR 事件")}</button></div>
        <div class="section-title mono">CAPABILITIES</div><div class="cap-grid" id="g-caps"></div>
        <div class="section-title mono">ADAPTERS</div>
        ${st.adapters.map((a) => `<div class="svc"><b>${a.available ? `<span class="ok-txt">${t("可用")}</span>` : `<span class="muted">${t("预留")}</span>`}</b><span>${esc(tr(a.label))}</span><span class="muted small">${esc(tr(a.note) || a.kind)}</span></div>`).join("")}
      </div>
      <div class="panel" style="margin-top:14px"><div class="section-title mono">EVENTS · ${t("输入 → / ← 输出")}</div><div class="ev-log" id="ev-log"></div></div>
    </div></div>`;
  G.client = createGlassesClient({
    kind: "glasses-sim", lens: $("#lens"), avatarEl: $("#ar-avatar"),
    onState: (s) => { G.st = s; renderState(); }, onLog: log,
  });
  G.client.setCharacter(c);
  const client = G.client;
  $("#g-connect").onclick = () => (client.connected ? client.disconnect() : client.connect());
  $("#g-cam").onclick = () => (G.stream ? stopCamera() : startCamera());
  $("#g-speak").onchange = (e) => client.setSpeak(e.target.checked);
  $("#g-say").onclick = () => {
    const said = $("#g-text").value.trim();
    if (!said) { $("#g-text").focus(); return toast("先在上面写一句话，或者点“用麦克风说”"); }
    client.ask({ type: "mic.text", text: said }); $("#g-text").value = "";
  };
  $("#g-text").onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) $("#g-say").click(); };
  $("#g-frame").onclick = () => client.ask({ type: "camera.frame", image: frameFrom(G.stream ? $("#lens-video") : null), question: $("#g-q").value.trim() });
  $("#g-test").onclick = () => api("/api/devices/test-ar", { body: {} }).then((r) => !r.sent && toast("先连接模拟器")).catch(fail);
  $("#g-place").onclick = () => client.placeHere();
  $("#g-center").onclick = () => client.setPose({ yaw: 0, pitch: 0, roll: 0 });
  $("#g-mic").onclick = () => toggleMic(client);
  $$("[data-pose]").forEach((el) => (el.oninput = () => client.setPose({ [el.dataset.pose]: +el.value })));
  // 拖动镜片画面 = 转头（往右拖 = 往左看，和拖动全景图一样）
  const lens = $("#lens");
  lens.onpointerdown = (e) => {
    const start = { x: e.clientX, y: e.clientY, ...client.pose }, w = lens.clientWidth, h = lens.clientHeight;
    lens.setPointerCapture(e.pointerId);
    lens.onpointermove = (m) => client.setPose({ yaw: start.yaw - ((m.clientX - start.x) / w) * 70, pitch: start.pitch + ((m.clientY - start.y) / h) * 50 });
    lens.onpointerup = lens.onpointercancel = () => { lens.onpointermove = null; };
  };
  renderState();
  log("in", t("模拟器页面就绪"));
}

async function toggleMic(client) {
  // 不另设开关：第一次用时浏览器会问你允不允许用麦克风（和聊天页的麦克风一样）
  const btn = $("#g-mic");
  if (G.listening?.hear) {  // 直接听：整段录音交给她
    const l = G.listening; G.listening = null; btn.textContent = t("用麦克风说");
    const audio = l.stop();
    if (audio) client.ask({ type: "mic.audio", audio }); else toast("没听清，再说一次？");
    return;
  }
  if (!G.listening && await canHear()) {
    try {
      const rec = await record({ maxSeconds: 60 });
      G.listening = { hear: true, stop: rec.stop, cancel: rec.cancel };
      btn.textContent = t("说完了");
    } catch (e) { fail(e.name === "NotAllowedError" ? new Error(t("没有麦克风权限：请在浏览器地址栏允许麦克风")) : e); }
    return;
  }
  if (G.listening) {
    const l = G.listening; G.listening = null; btn.textContent = t("用麦克风说");
    try { const said = await l.stop(); if (said) client.ask({ type: "mic.text", text: said }); } catch (e) { fail(e); }
    return;
  }
  const a = await sttAvailable();
  if (!a.ok) return toast(a.why, 5000);
  try { G.listening = await listen({ onPartial: (x) => ($("#g-text").value = x) }); btn.textContent = t("说完了"); } catch (e) { fail(e); }
}

export function leaveGlasses() {
  stopCamera();
  G.listening?.cancel(); G.listening = null;
  G.client?.destroy(); G.client = null;
  G.st = { state: "disconnected" };
}
export function initGlasses() {
  window.addEventListener("beforeunload", () => G.client?.disconnect());
  bus.on("character", () => G.client?.setCharacter(curChar()));  // 换了角色：告诉眼镜现在是谁，镜片里也换人
}
