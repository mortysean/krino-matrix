// KRINO GLASSES 桌面测试版（/device 页面）。Windows 应用（app/glasses-desktop）用一个透明、置顶的窗口加载它，
// 窗口就是镜片：她站在你的桌面上，字幕、面板浮在旁边；没画东西的地方鼠标能点穿到下面的程序。
//   说话   麦克风：点一下开始、再点一下说完（Ctrl+Alt+Space 全局可用）；声波：免按键的语音对话，随时开口打断她
//   看     眼睛：用电脑摄像头拍一帧给她看（要先在设置 → 隐私里允许摄像头）
//   转头   ← → ↑ ↓（全局 Ctrl+Alt+方向键），或在托盘菜单里打开“用鼠标位置当头部朝向”；0 回正
//   放置   定位针 / P：把她放在你正看着的地方
// 连接、AR 显示、朗读都在 glassesclient.js（和设置页里的浏览器模拟器共用），设备类型是 glasses-desktop。
import { $, S, api, curChar, esc, fail, storeGet, storeSet, t, toast, tr, url } from "./core.js";
import { setLocale } from "./i18n.js";
import { ICON } from "./icons.js";
import { canHear, hum, listen, record, sttAvailable, stopSpeaking, warmHum } from "./voice.js";
import { createVoiceMode } from "./voicemode.js";
import { createGlassesClient, frameFrom } from "./glassesclient.js";

// 工具栏图标：icons.js 里有的直接用，其余按同样的线条风格画
const svg = (d) => `<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const IC = {
  mic: ICON.mic, speaker: ICON.speaker, mute: ICON.mute,
  talk: svg('<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>'),
  look: svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  place: svg('<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>'),
};
const desk = window.krinoDesktop || null;  // Windows 应用的 preload 提供；浏览器里没有
const D = { client: null, vm: null, listening: null, st: { state: "disconnected" } };
const siteRoot = () => location.pathname.replace(/device\/?$/, "");

async function main() {
  S.site = await fetch(url("/api/site")).then((r) => r.json()).catch(() => ({}));
  await setLocale(S.site.locale);
  document.title = "KRINO GLASSES";
  if (desk) document.body.classList.add("in-app");
  // 在网站或登录窗口里登录 / 退出：这里跟着刷新
  addEventListener("storage", (e) => { if (e.key?.endsWith("krino_token")) location.reload(); });
  if (!S.token) return showLogin();
  try { S.me = await api("/api/me"); } catch (e) { return showLogin(e.status === 0 ? t("连不上服务器，请稍后刷新") : ""); }
  S.chars = await api("/api/characters").catch(() => []);
  S.charId = S.chars.find((c) => c.id === S.charId)?.id || S.chars[0]?.id;
  start();
}

function showLogin(why = "") {
  const box = $("#dev-login");
  box.classList.remove("hidden");
  box.innerHTML = `<b>KRINO GLASSES</b><p>${esc(why || t("先登录 KRINO WORLD 账号，眼镜才能连上她。"))}</p>
    <button id="dev-login-btn">${t("登录")}</button>
    <p class="muted small">${t("登录后这里会自动刷新。")}</p>`;
  $("#dev-login-btn").onclick = () => (desk ? desk.openLogin() : window.open(siteRoot(), "_blank"));
  $("#dev-bar").innerHTML = "";
  interactive(true);
}

function start() {
  const bar = $("#dev-bar");
  bar.innerHTML = `
    <span class="dev-grip" title="${t("拖动窗口")}">⋮⋮</span>
    <span class="dev-dot" id="dev-dot" title="${t("未连接")}">●</span>
    <select id="dev-char" title="${t("换一位角色")}">${S.chars.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")}</select>
    <input id="dev-text" placeholder="${t("对她说…")}" autocomplete="off">
    <button class="dev-btn" id="dev-mic" title="${t("说一句（Ctrl+Alt+Space）")}">${IC.mic}</button>
    <button class="dev-btn" id="dev-vm" title="${t("语音对话：说完她自动回答，可以随时打断（Ctrl+Alt+V）")}">${IC.talk}</button>
    <button class="dev-btn" id="dev-look" title="${t("让她看看摄像头画面")}">${IC.look}</button>
    <button class="dev-btn" id="dev-place" title="${t("把她放在我正看着的地方（P）")}">${IC.place}</button>
    <button class="dev-btn" id="dev-speak" title="${t("眼镜扬声器朗读")}"></button>`;
  $("#dev-char").value = S.charId || "";
  D.client = createGlassesClient({
    kind: "glasses-desktop", lens: $("#lens"), avatarEl: $("#ar-avatar"), reconnect: true,
    onState: (s) => { D.st = s; render(); },
    onLog: (dir, text) => { if (dir === "err") console.warn("[glasses]", text); },
  });
  D.client.setCharacter(curChar());
  D.client.connect();
  D.vm = createVoiceMode({
    host: $(".dev-voice"),
    submit: ({ text, audio, signal, gate, onStart }) => D.client.ask(audio ? { type: "mic.audio", audio } : { type: "mic.text", text }, { signal, gate, onStart }),
    onExit: () => { $("#dev-vm").classList.remove("on"); D.client.avatar.speaking(false); },
    onState: (s) => D.client.avatar.listening(s === "hearing"),
    onHum: () => { D.client.avatar.play("nod").catch(() => {}); return hum(curChar()?.voice || {}); },
  });

  $("#dev-char").onchange = (e) => { S.charId = e.target.value; storeSet("krino_char", S.charId); D.vm.stop(); stopSpeaking(); D.client.setCharacter(curChar()); };
  $("#dev-text").onkeydown = (e) => {
    if (e.key !== "Enter" || e.isComposing) return;
    const said = e.target.value.trim(); if (!said) return;
    D.client.ask({ type: "mic.text", text: said }); e.target.value = "";
  };
  $("#dev-mic").onclick = toggleMic;
  $("#dev-vm").onclick = toggleVoice;
  $("#dev-look").onclick = look;
  $("#dev-place").onclick = () => D.client.placeHere();
  let speakOn = storeGet("krino_glasses_speak") !== "0";
  const setSpeak = (on) => { speakOn = on; storeSet("krino_glasses_speak", on ? "1" : "0"); D.client.setSpeak(on); $("#dev-speak").innerHTML = on ? IC.speaker : IC.mute; };
  $("#dev-speak").onclick = () => setSpeak(!speakOn);
  setSpeak(speakOn);

  addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, textarea")) return;
    const cmd = { ArrowLeft: "turn-left", ArrowRight: "turn-right", ArrowUp: "look-up", ArrowDown: "look-down", 0: "center", p: "place", P: "place", " ": "mic" }[e.key];
    if (cmd) { e.preventDefault(); command(cmd); }
  });
  desk?.onCommand(command);
  desk?.onCursorPose((p) => D.client.setPose(p));
  // 点穿：鼠标在没画东西的地方时，窗口不接鼠标，点到下面的程序
  addEventListener("mousemove", (e) => interactive(!!e.target.closest?.(".dev-bar, .dev-voice, .dev-login, .ar-panel, .ar-subtitle")));
  render();
}

function command(cmd) {
  const c = D.client; if (!c) return;
  const p = c.pose;
  if (cmd === "turn-left") c.setPose({ yaw: p.yaw - 10 });
  else if (cmd === "turn-right") c.setPose({ yaw: p.yaw + 10 });
  else if (cmd === "look-up") c.setPose({ pitch: p.pitch + 5 });
  else if (cmd === "look-down") c.setPose({ pitch: p.pitch - 5 });
  else if (cmd === "center") c.setPose({ yaw: 0, pitch: 0, roll: 0 });
  else if (cmd === "place") c.placeHere();
  else if (cmd === "mic") toggleMic();
  else if (cmd === "voice") toggleVoice();
}

let lastInteractive = null;
function interactive(on) {
  if (on === lastInteractive) return;
  lastInteractive = on;
  desk?.setInteractive(on);
}

function render() {
  const s = D.st, dot = $("#dev-dot");
  if (!dot) return;
  const label = t({ connected: "已连接", connecting: "连接中…", stale: "心跳超时", disconnected: "未连接" }[s.state] || s.state);
  dot.className = "dev-dot " + s.state; dot.title = label + (s.busy ? " · " + t("她在想…") : "");
  const p = s.pose || { yaw: 0, pitch: 0 };
  $("#dev-hud").textContent = `${s.state === "connected" ? "●" : "○"} YAW ${p.yaw}° · PITCH ${p.pitch}°${s.busy ? " · " + t("她在想…") : ""}`;
}

async function toggleMic() {
  const btn = $("#dev-mic");
  if (D.vm?.active) return;  // 语音对话进行中：直接说就行
  if (D.listening) {
    const l = D.listening; D.listening = null; btn.classList.remove("on");
    if (l.hear) { const audio = l.stop(); if (audio) D.client.ask({ type: "mic.audio", audio }); else toast("没听清，再说一次？"); return; }
    try { const said = await l.stop(); if (said) D.client.ask({ type: "mic.text", text: said }); } catch (e) { fail(e); }
    return;
  }
  stopSpeaking();
  try {
    if (await canHear()) { const rec = await record({ maxSeconds: 60 }); D.listening = { hear: true, stop: rec.stop, cancel: rec.cancel }; }
    else {
      const a = await sttAvailable();
      if (!a.ok) return toast(a.why, 5000);
      D.listening = await listen({ onPartial: (x) => ($("#dev-text").value = x) });
    }
    btn.classList.add("on");
    D.client.avatar.listening(true);
    setTimeout(() => D.client?.avatar.listening(false), 60000);
  } catch (e) { fail(e.name === "NotAllowedError" ? new Error(t("没有麦克风权限：请在系统设置里允许 KRINO GLASSES 使用麦克风")) : e); }
}

function toggleVoice() {
  if (D.vm.active) { D.vm.stop(); return; }
  if (D.listening) { D.listening.cancel?.(); D.listening = null; $("#dev-mic").classList.remove("on"); }
  $("#dev-vm").classList.add("on");
  warmHum(curChar()?.voice || {});
  D.vm.start();
}

// 用电脑摄像头拍一帧给她看：只拍这一帧，拍完马上关掉摄像头
async function look() {
  if (!S.me?.settings?.privacy?.camera) return toast("请先在网站的“设置 → 隐私”里允许摄像头", 5000);
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false });
    const v = document.createElement("video");
    v.muted = true; v.playsInline = true; v.srcObject = stream;
    await v.play();
    await new Promise((r) => setTimeout(r, 400));  // 让摄像头自动曝光一下
    const image = frameFrom(v);
    D.client.ask({ type: "camera.frame", image, question: $("#dev-text").value.trim() });
    $("#dev-text").value = "";
  } catch (e) { fail(e.name === "NotAllowedError" ? new Error(t("没有摄像头权限：请在系统设置里允许")) : e); }
  finally { stream?.getTracks().forEach((x) => x.stop()); }
}

main().catch((e) => toast("✕ " + tr(e.message || String(e)), 6000));
