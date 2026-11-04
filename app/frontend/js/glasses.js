// KRINO GLASSES 模拟器（在“设置 → 高级”里）。浏览器当作一副眼镜，通过 WebSocket 接入后端统一的 Device Adapter：
//   输入  camera.frame（摄像头一帧）/ mic.text（说的话）/ imu.pose（头部姿态，这里用滑杆或鼠标拖动模拟）/ heartbeat
//   输出  ar.avatar / ar.subtitle / ar.panel / ar.clear —— 结构化事件，画在“镜片”叠加层上
// 摄像头和麦克风只在你点了按钮、浏览器授权后才打开；离开这个页面或断开时立即关闭。
import { $, $$, S, api, curChar, esc, fail, toast } from "./core.js";
import { listen, sttAvailable } from "./voice.js";
import { createStage } from "./stage.js";

const G = { ws: null, state: "disconnected", stream: null, pose: { yaw: 0, pitch: 0, roll: 0 }, log: [], hb: null, ar: {}, busy: false, listening: null };

function log(dir, text) {
  G.log.unshift({ dir, text, at: new Date().toLocaleTimeString() });
  G.log = G.log.slice(0, 80);
  const box = $("#ev-log");
  if (box) box.innerHTML = G.log.map((x) => `<div class="${x.dir}">${x.at} ${x.dir === "in" ? "→" : x.dir === "out" ? "←" : "!"} ${esc(x.text)}</div>`).join("");
}

function send(msg) {
  if (G.ws?.readyState !== 1) return toast("先连接模拟器");
  G.ws.send(JSON.stringify(msg));
  log("in", msg.type + (msg.text ? " " + msg.text : "") + (msg.image ? " [画面]" : msg.type === "imu.pose" ? ` yaw=${msg.yaw} pitch=${msg.pitch}` : ""));
}

function connect() {
  if (G.ws) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/devices/ws?token=${encodeURIComponent(S.token)}&kind=glasses-sim`);
  G.ws = ws; G.state = "connecting"; renderState();
  ws.onopen = () => ws.send(JSON.stringify({ type: "hello", character_id: S.charId }));
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => { G.ws = null; G.state = "disconnected"; clearInterval(G.hb); renderState(); log("err", "连接已断开"); };
  ws.onerror = () => log("err", "连接出错");
  G.hb = setInterval(() => G.ws?.readyState === 1 && G.ws.send(JSON.stringify({ type: "heartbeat" })), 3000);
}

function disconnect() {
  G.ws?.close();
  stopCamera();
  G.listening?.cancel(); G.listening = null;
}

function onMessage(m) {
  if (m.type === "state") { G.state = m.state; G.device = m; renderState(); log("out", `state ${m.state} · ${m.label}`); }
  else if (m.type === "heartbeat") { G.state = m.state; renderState(); }
  else if (m.type === "busy") { G.busy = true; renderState(); }
  else if (m.type === "ar") { m.events.forEach(applyAR); log("out", "ar " + m.events.map((e) => e.type).join(", ")); }
  else if (m.type === "result") { G.busy = false; renderState(); log("out", `result [${m.decision.actions.join("+")}] ${m.reply || "（安静）"}`); }
  else if (m.type === "error") { G.busy = false; renderState(); log("err", m.message); toast(m.message, 4000); }
}

// ---------- AR 叠加层 ----------
function applyAR(e) {
  const lens = $("#lens");
  if (!lens) return;
  if (e.type === "ar.clear") { $$(".ar-subtitle, .ar-panel", lens).forEach((x) => x.remove()); return; }
  if (e.type === "ar.avatar") {
    G.ar.anchor = e.anchor;
    placeAvatar();
    if (e.expression) G.avatar?.setExpression(e.expression);
    if (e.animation) G.avatar?.play(e.animation).catch(() => {});
    return;
  }
  const el = document.createElement("div");
  if (e.type === "ar.subtitle") {
    $$(".ar-subtitle", lens).forEach((x) => x.remove());
    el.className = "ar-subtitle"; el.innerHTML = `<b>${esc(e.speaker)}</b>${esc(e.text)}`;
    G.avatar?.speaking(true); setTimeout(() => G.avatar?.speaking(false), Math.min(e.ttl_ms, 600 + e.text.length * 90));
  } else if (e.type === "ar.panel") {
    $$(".ar-panel", lens).forEach((x) => x.remove());
    el.className = "ar-panel"; el.innerHTML = `<b>${esc(e.title)}</b>${esc(e.body)}`;
  }
  lens.appendChild(el);
  setTimeout(() => el.remove(), e.ttl_ms || 6000);
}

// 角色锚在世界坐标里：头转向右（yaw 变大），她在镜片里就往左移；离开视野（±45°）就看不到
function placeAvatar() {
  const a = G.ar.anchor || { yaw: 20, pitch: -5, distance: 1.5 }, el = $("#ar-avatar");
  if (!el) return;
  const fov = 45, dx = (a.yaw - G.pose.yaw) / fov, dy = (a.pitch - G.pose.pitch) / 30;
  const scale = Math.max(0.5, Math.min(1.4, 1.5 / a.distance));
  el.style.left = `${50 + dx * 50 - 17}%`;
  el.style.top = `${48 - dy * 50 - 20}%`;
  el.style.transform = `scale(${scale}) rotate(${-G.pose.roll}deg)`;
  el.style.opacity = Math.abs(dx) > 1.1 ? 0 : 1;
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
  } catch (e) { fail(e.name === "NotAllowedError" ? new Error("没有摄像头权限：请在浏览器地址栏允许") : e); }
}

function stopCamera() {
  G.stream?.getTracks().forEach((t) => t.stop());
  G.stream = null;
  const v = $("#lens-video"); if (v) { v.srcObject = null; v.classList.add("hidden"); }
  renderState();
}

function grabFrame() {
  const v = $("#lens-video");
  if (G.stream && v?.videoWidth) {
    const c = document.createElement("canvas"); c.width = 480; c.height = Math.round(480 * v.videoHeight / v.videoWidth);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.8);
  }
  // 没开摄像头：用模拟场景画一帧（让流程可以在没有摄像头的机器上验证）
  const c = document.createElement("canvas"); c.width = 320; c.height = 200;
  const g = c.getContext("2d"), grd = g.createLinearGradient(0, 0, 0, 200);
  grd.addColorStop(0, "#3a5fcf"); grd.addColorStop(1, "#e3d6b0");
  g.fillStyle = grd; g.fillRect(0, 0, 320, 200);
  g.fillStyle = "#2b2b2b"; g.fillRect(40, 120, 90, 60); g.fillStyle = "#f4f4f4"; g.beginPath(); g.arc(250, 50, 22, 0, 7); g.fill();
  return c.toDataURL("image/jpeg", 0.85);
}

// ---------- 页面 ----------
function renderState() {
  const st = $("#g-state");
  if (!st) return;
  const label = { connected: "已连接", connecting: "连接中…", stale: "心跳超时", disconnected: "未连接" }[G.state] || G.state;
  st.innerHTML = `<span class="${G.state === "connected" ? "ok-txt" : G.state === "disconnected" ? "err-txt" : "warn-txt"}">● ${label}</span>${G.busy ? ' <span class="muted">· 她在想…</span>' : ""}`;
  $("#g-connect").textContent = G.ws ? "断开" : "连接模拟器";
  $("#g-cam").textContent = G.stream ? "关闭摄像头" : "打开摄像头";
  $("#lens-hud").textContent = `KRINO GLASSES SIM · ${G.state.toUpperCase()} · CAM ${G.stream ? "ON" : "SIM"} · YAW ${G.pose.yaw}° PITCH ${G.pose.pitch}°`;
  const caps = G.device?.capabilities || {};
  $("#g-caps").innerHTML = [["camera", "摄像头"], ["microphone", "麦克风"], ["speaker", "扬声器"], ["ar_display", "AR 显示"], ["imu", "头部姿态"]]
    .map(([k, l]) => `<span class="${caps[k] ? "on" : ""}">${caps[k] ? "✓" : "·"} ${l}</span>`).join("") + `<span class="${G.state === "connected" ? "on" : ""}">${G.state === "connected" ? "✓" : "·"} 连接状态</span>`;
}

export async function glassesPanel(host) {
  const c = curChar();
  const st = await api("/api/devices").catch(() => ({ adapters: [] }));
  host.innerHTML = `<div class="glasses">
    <div>
      <div class="lens" id="lens">
        <div class="lens-bg"></div><video id="lens-video" class="hidden" muted playsinline></video>
        <div class="ar-avatar" id="ar-avatar"></div>
        <div class="reticle"></div><div class="hud" id="lens-hud"></div>
      </div>
      <div class="row">
        <input id="g-text" placeholder="对着眼镜说一句话（模拟麦克风输入）" style="flex:1">
        <button class="ghost" id="g-mic">用麦克风说</button><button id="g-say">发送</button>
      </div>
      <div class="row">
        <button class="ghost" id="g-cam">打开摄像头</button>
        <input id="g-q" placeholder="想问她看到了什么（可选）" style="flex:1"><button id="g-frame">分享眼前的画面</button>
      </div>
      <div class="panel" style="margin-top:12px">
        <div class="section-title mono">HEAD POSE · 头部姿态（模拟 IMU）</div>
        <div class="slider-row"><span>左右转头 yaw</span><input type="range" min="-90" max="90" value="0" data-pose="yaw"><span>0°</span></div>
        <div class="slider-row"><span>抬头低头 pitch</span><input type="range" min="-45" max="45" value="0" data-pose="pitch"><span>0°</span></div>
        <div class="slider-row"><span>歪头 roll</span><input type="range" min="-30" max="30" value="0" data-pose="roll"><span>0°</span></div>
        <p class="muted small">角色锚定在你右前方 1.5 米处。转头时她在镜片里的位置会跟着变，转得太多就会离开视野——AR 输出是结构化的位置和行为事件，不是让模型直接画画面。</p>
      </div>
    </div>
    <div>
      <div class="panel">
        <div class="section-title mono">DEVICE · 设备</div>
        <div id="g-state"></div>
        <p class="small muted">当前角色：${esc(c?.name || "")}（AI）。设备输入会进入和她的当前会话。</p>
        <div class="row"><button id="g-connect">连接模拟器</button><button class="ghost small" id="g-test">发送测试 AR 事件</button></div>
        <div class="section-title mono">CAPABILITIES</div><div class="cap-grid" id="g-caps"></div>
        <div class="section-title mono">ADAPTERS</div>
        ${st.adapters.map((a) => `<div class="svc"><b>${a.available ? '<span class="ok-txt">可用</span>' : '<span class="muted">预留</span>'}</b><span>${esc(a.label)}</span><span class="muted small">${esc(a.note || a.kind)}</span></div>`).join("")}
      </div>
      <div class="panel" style="margin-top:14px"><div class="section-title mono">EVENTS · 输入 → / ← 输出</div><div class="ev-log" id="ev-log"></div></div>
    </div></div>`;
  // 镜片里的角色：同一个 2D 形象组件
  G.avatar = createStage($("#ar-avatar"));
  G.avatar.load(c?.portrait, { name: c?.name, color: c?.color }).catch(() => {});
  placeAvatar();
  $("#g-connect").onclick = () => (G.ws ? disconnect() : connect());
  $("#g-cam").onclick = () => (G.stream ? stopCamera() : startCamera());
  $("#g-say").onclick = () => { const t = $("#g-text").value.trim(); if (t) { send({ type: "mic.text", text: t }); $("#g-text").value = ""; } };
  $("#g-text").onkeydown = (e) => { if (e.key === "Enter" && !e.isComposing) $("#g-say").click(); };
  $("#g-frame").onclick = () => send({ type: "camera.frame", image: grabFrame(), question: $("#g-q").value.trim() });
  $("#g-test").onclick = () => api("/api/devices/test-ar", { body: {} }).then((r) => !r.sent && toast("先连接模拟器")).catch(fail);
  $("#g-mic").onclick = async () => {
    if (!S.me?.settings?.privacy?.microphone) return toast("请先在“设置 → 隐私”里允许麦克风", 4000);
    if (G.listening) {
      const l = G.listening; G.listening = null; $("#g-mic").textContent = "用麦克风说";
      try { const t = await l.stop(); if (t) send({ type: "mic.text", text: t }); } catch (e) { fail(e); }
      return;
    }
    const a = await sttAvailable();
    if (!a.ok) return toast(a.why, 5000);
    try { G.listening = await listen({ onPartial: (t) => ($("#g-text").value = t) }); $("#g-mic").textContent = "说完了"; } catch (e) { fail(e); }
  };
  let poseT;
  $$("[data-pose]").forEach((el) => (el.oninput = () => {
    G.pose[el.dataset.pose] = +el.value; el.nextElementSibling.textContent = el.value + "°";
    placeAvatar(); renderState();
    clearTimeout(poseT); poseT = setTimeout(() => G.ws?.readyState === 1 && send({ type: "imu.pose", ...G.pose }), 150);
  }));
  renderState();
  log("in", "模拟器页面就绪");
}

export function leaveGlasses() { stopCamera(); G.listening?.cancel(); G.listening = null; }
export function initGlasses() { window.addEventListener("beforeunload", disconnect); }
