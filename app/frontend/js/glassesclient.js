// 眼镜客户端：浏览器里的眼镜模拟器（glasses.js）和 Windows 桌面测试版（device.js）共用。
// 通过 WebSocket 接入后端统一的 Device Adapter（app/backend/app/devices.py）：
//   输入  hello（当前角色）/ mic.text / mic.audio / camera.frame / imu.pose（头部姿态）/ anchor.set（把她放在你看着的地方）/ heartbeat
//   输出  delta（边生成边推的字幕）/ result（完整回复，自己朗读）/ ar（ar.avatar / ar.subtitle / ar.panel / ar.clear）
// 她待在世界里的一个位置（anchor，相对开机朝向的角度 + 距离），不随头转：头往右转，她在镜片里往左移；转出视野就看不到，
// 镜片边上一个箭头指着她在哪。她要开口时你没在看她，后端会让她走到你眼前（这里平滑地移过去）。
// 自己说的话她念出来（口型跟着声音），别处（手机、网页）聊天同步过来的只显示字幕，不重复出声。
import { S, api, curChar, esc, t, tr, url } from "./core.js";
import { createStage } from "./stage.js";
import { createSpeech, speak, speechLevel, stopSpeaking } from "./voice.js";

export const HALF_FOV_X = 35, HALF_FOV_Y = 25;  // 和后端 devices.VIEW_YAW / VIEW_PITCH 一致
const wrap = (d) => ((((d + 180) % 360) + 360) % 360) - 180;

export function createGlassesClient({ kind, lens, avatarEl, reconnect = false, onState, onLog, onTurn }) {
  const G = {
    ws: null, state: "disconnected", device: null, hb: 0, retry: 0, closing: false,
    pose: { yaw: 0, pitch: 0, roll: 0 }, anchor: { yaw: 20, pitch: -5, distance: 1.5 },
    pending: null, skip: 0, live: "", speakOn: true, char: null, poseT: 0,
  };
  const avatar = createStage(avatarEl, { level: speechLevel });
  const edge = document.createElement("div");
  edge.className = "ar-edge"; edge.hidden = true;
  lens.appendChild(edge);

  const log = (dir, text) => onLog?.(dir, text);
  const emit = () => onState?.({ state: G.state, device: G.device, busy: !!G.pending, pose: G.pose, anchor: G.anchor });

  // ---------- 连接 ----------
  function connect() {
    if (G.ws) return;
    G.closing = false;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}${url("/api/devices/ws")}?token=${encodeURIComponent(S.token || "")}&kind=${kind}`);
    G.ws = ws; G.state = "connecting"; emit();
    ws.onopen = () => {
      G.retry = 0;
      ws.send(JSON.stringify({ type: "hello", character_id: G.char?.id || S.charId }));
      ws.send(JSON.stringify({ type: "imu.pose", ...G.pose }));
    };
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    ws.onclose = () => {
      if (G.ws !== ws) return;
      G.ws = null; G.state = "disconnected"; clearInterval(G.hb);
      if (G.pending) { G.pending.done({ ok: false }); G.pending = null; }
      G.skip = 0;
      emit(); log("err", t("连接已断开"));
      if (reconnect && !G.closing) {  // 桌面版：断了自己重连（1、2、4……最多 30 秒）
        const wait = Math.min(30000, 1000 * 2 ** G.retry++);
        setTimeout(() => !G.closing && connect(), wait);
      }
    };
    ws.onerror = () => log("err", t("连接出错"));
    clearInterval(G.hb);
    G.hb = setInterval(() => G.ws?.readyState === 1 && G.ws.send(JSON.stringify({ type: "heartbeat" })), 3000);
  }
  function disconnect() { G.closing = true; G.ws?.close(); }

  function send(msg) {
    if (G.ws?.readyState !== 1) {  // 还没连上：连上再发
      if (!G.ws) connect();
      const ws = G.ws;
      const go = () => { ws.removeEventListener("open", go); setTimeout(() => G.ws === ws && ws.readyState === 1 && send(msg), 300); };
      ws.addEventListener("open", go);
      return;
    }
    G.ws.send(JSON.stringify(msg));
    log("in", msg.type + (msg.text ? " " + msg.text : "") + (msg.image ? " [" + t("画面") + "]" : msg.audio ? " [" + t("录音") + "]"
      : msg.type === "imu.pose" ? ` yaw=${msg.yaw} pitch=${msg.pitch}` : msg.type === "anchor.set" ? ` yaw=${msg.yaw} pitch=${msg.pitch} d=${msg.distance}` : ""));
  }

  // 说一句 / 给她看一眼：返回 { ok, reply, speaking }，speaking 是她念完的 promise（语音对话靠它决定什么时候接着听）。
  // 后端按顺序一条条处理：上一句还没回来就又说了（或语音对话撤回了这一轮），上一句的回复回来时作废，不会当成这一句的回答念出来
  function drop() { if (G.pending) { G.pending.done({ ok: false }); G.pending = null; G.skip++; } }
  // gate / onStart：语音对话用（见 voicemode.js）：先合成好、放行了才出声；第一个声音响起时告诉它
  function ask(msg, { signal, gate = null, onStart = null } = {}) {
    drop();
    stopSpeaking();
    return new Promise((done) => {
      const mine = { done, gate, onStart, speech: null };
      G.pending = mine; G.live = "";
      signal?.addEventListener("abort", () => { mine.speech?.stop(); if (G.pending === mine) { drop(); emit(); } }, { once: true });
      send(msg); emit();
    });
  }

  function onMessage(m) {
    if (m.type === "state") { G.state = m.state; G.device = m; if (m.anchor) G.anchor = m.anchor; place(); log("out", `state ${m.state} · ${tr(m.label)}`); }
    else if (m.type === "heartbeat") G.state = m.state;
    else if (m.type === "busy") avatar.play("think").catch(() => {});
    else if (m.type === "delta" || m.type === "filler") {  // 边生成边出字幕、边念（filler：要查一下，先说一声，不进字幕）
      if (G.skip) return;
      if (m.type === "delta") { G.live += m.text; subtitle(G.live, { live: true }); }
      const p = G.pending;
      if (p && G.speakOn) {
        p.speech ||= createSpeech(G.char?.voice || curChar()?.voice || {}, { gate: p.gate, onStart: () => { avatar.speaking(true); p.onStart?.(); } });
        p.speech.add(m.type === "filler" ? m.text + " " : m.text);
      }
    }
    else if (m.type === "ar") { m.events.forEach(applyAR); log("out", "ar " + m.events.map((e) => e.type).join(", ")); }
    else if ((m.type === "result" || m.type === "error") && G.skip) { G.skip--; log("out", t("（作废的上一轮）")); }
    else if (m.type === "result") {
      if (m.heard) log("in", t("她听到的：{text}", { text: m.heard }));
      log("out", `result [${m.decision.actions.join("+")}] ${m.reply || t("（安静）")}`);
      const p = G.pending; G.pending = null;
      let speaking = null;
      if (p?.speech && m.reply) { p.speech.end(); speaking = p.speech.done.then(() => avatar.speaking(false)); }
      else if (m.reply && G.speakOn) speaking = say(m.reply, p);
      else p?.speech?.stop();
      const sp = p?.speech;
      p?.done({ ok: true, reply: m.reply || "", speaking, speech: sp,
        interrupted: () => m.reply_id && api(`/api/sessions/${m.session_id}/messages/${m.reply_id}/heard`, { body: { heard: sp?.heard() || "" } }).catch(() => {}) });
      onTurn?.(m);
    }
    else if (m.type === "error") {
      log("err", tr(m.message));
      const p = G.pending; G.pending = null; p?.speech?.stop(); p?.done({ ok: false });
      subtitle("⚠ " + tr(m.message), { ttl: 5000, system: true });
    }
    emit();
  }

  // 朗读一整段（没有流式字幕时，比如固定的回答），嘴跟着声音动
  async function say(text, p = null) {
    try {
      const r = await speak(text, G.char?.voice || curChar()?.voice || {}, { gate: p?.gate, onStart: () => { avatar.speaking(true); p?.onStart?.(); } });
      await r.done;
    } catch (e) { log("err", e.message || String(e)); }
    avatar.speaking(false);
  }

  // ---------- AR 叠加层 ----------
  let subT = 0;
  function subtitle(text, { live = false, ttl = 0, speaker = G.char?.name || "", system = false } = {}) {
    let el = lens.querySelector(".ar-subtitle");
    if (!text) { el?.remove(); return; }
    if (!el) { el = document.createElement("div"); el.className = "ar-subtitle"; lens.appendChild(el); }
    el.classList.toggle("live", live); el.classList.toggle("system", system);
    el.innerHTML = (speaker && !system ? `<b>${esc(speaker)}</b>` : "") + esc(text.length > 160 ? "…" + text.slice(-158) : text);
    clearTimeout(subT);
    if (ttl) subT = setTimeout(() => el.remove(), ttl);
  }

  function applyAR(e) {
    if (e.type === "ar.clear") { subtitle(""); lens.querySelectorAll(".ar-panel").forEach((x) => x.remove()); return; }
    if (e.type === "ar.avatar") {
      const moved = Math.abs(wrap(e.anchor.yaw - G.anchor.yaw)) > 1 || Math.abs(e.anchor.pitch - G.anchor.pitch) > 1 || e.anchor.distance !== G.anchor.distance;
      G.anchor = e.anchor;
      place({ walk: moved });  // 位置变了（走到你眼前 / 被放到别处）：平滑地移过去
      if (e.expression) avatar.setExpression(e.expression);
      if (e.animation) avatar.play(e.animation).catch(() => {});
      return;
    }
    if (e.type === "ar.subtitle") {
      subtitle(e.text, { ttl: e.ttl_ms, speaker: e.speaker });
      if (!G.pending) {  // 别处聊天同步过来的：不出声，嘴按字数动一会儿
        avatar.speaking(true); setTimeout(() => avatar.speaking(false), Math.min(e.ttl_ms, 600 + e.text.length * 90));
      }
      return;
    }
    if (e.type === "ar.panel") {
      lens.querySelectorAll(".ar-panel").forEach((x) => x.remove());
      const el = document.createElement("div");
      el.className = "ar-panel"; el.dataset.kind = e.kind;
      el.innerHTML = `<b>${esc(tr(e.title))}</b>${esc(tr(e.body))}`;
      lens.appendChild(el);
      setTimeout(() => el.remove(), e.ttl_ms || 8000);
    }
  }

  // 她在镜片里的位置：相对头部朝向的角度 → 镜片里的百分比；离得越远越小；歪头时画面反向转
  function place({ walk = false } = {}) {
    const a = G.anchor, p = G.pose;
    const dx = wrap(a.yaw - p.yaw) / HALF_FOV_X, dy = (a.pitch - p.pitch) / HALF_FOV_Y;
    const scale = Math.max(0.45, Math.min(1.5, 1.5 / a.distance));
    avatarEl.classList.toggle("walk", walk);
    if (walk) setTimeout(() => avatarEl.classList.remove("walk"), 900);
    avatarEl.style.left = `${50 + dx * 50}%`;
    avatarEl.style.top = `${50 - dy * 50}%`;
    avatarEl.style.setProperty("--s", scale.toFixed(3));
    avatarEl.style.rotate = `${-p.roll}deg`;
    const out = Math.abs(dx) > 1.15 || Math.abs(dy) > 1.3;
    avatarEl.classList.toggle("out", out);
    // 看不到她时，镜片边上的箭头指向她
    edge.hidden = !out;
    if (out) {
      const ang = Math.atan2(-dy, dx);
      const ex = 50 + Math.cos(ang) * 46, ey = 50 + Math.sin(ang) * 42;
      edge.style.left = `${Math.max(4, Math.min(96, ex))}%`; edge.style.top = `${Math.max(6, Math.min(94, ey))}%`;
      edge.style.rotate = `${ang}rad`;
      edge.title = dx < 0 ? t("她在你左边") : dx > 0 ? t("她在你右边") : t("她在你身后");
    }
  }

  function setPose(next) {
    Object.assign(G.pose, next);
    G.pose.yaw = Math.round(wrap(G.pose.yaw));
    G.pose.pitch = Math.max(-45, Math.min(45, Math.round(G.pose.pitch)));
    G.pose.roll = Math.max(-30, Math.min(30, Math.round(G.pose.roll || 0)));
    place(); emit();
    clearTimeout(G.poseT);
    G.poseT = setTimeout(() => G.ws?.readyState === 1 && send({ type: "imu.pose", ...G.pose }), 150);
  }

  // 把她放在你正看着的地方（稍微低一点，像站在面前）
  function placeHere(distance = G.anchor.distance) {
    send({ type: "anchor.set", yaw: G.pose.yaw, pitch: Math.max(-45, G.pose.pitch - 5), distance });
  }

  async function setCharacter(c) {
    G.char = c;
    if (G.ws?.readyState === 1) G.ws.send(JSON.stringify({ type: "hello", character_id: c?.id }));
    await avatar.load(c?.portrait, { name: c?.name, color: c?.color }).catch(() => {});
    avatar.setExpression(c?.default_expression || "calm");
  }

  place();
  return {
    connect, disconnect, send, ask, setPose, placeHere, setCharacter, avatar,
    setSpeak(on) { G.speakOn = !!on; if (!on) { stopSpeaking(); avatar.speaking(false); } },
    get pose() { return { ...G.pose }; }, get anchor() { return { ...G.anchor }; },
    get connected() { return G.ws?.readyState === 1; }, get busy() { return !!G.pending; },
    destroy() { disconnect(); clearInterval(G.hb); stopSpeaking(); avatar.destroy(); edge.remove(); },
  };
}

// 摄像头一帧（JPEG data URL）。没有摄像头时画一张模拟场景，让流程能在没摄像头的机器上验证
export function frameFrom(video) {
  if (video?.videoWidth) {
    const c = document.createElement("canvas"); c.width = 480; c.height = Math.round(480 * video.videoHeight / video.videoWidth);
    c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
    return c.toDataURL("image/jpeg", 0.8);
  }
  const c = document.createElement("canvas"); c.width = 320; c.height = 200;
  const g = c.getContext("2d"), grd = g.createLinearGradient(0, 0, 0, 200);
  grd.addColorStop(0, "#3a5fcf"); grd.addColorStop(1, "#e3d6b0");
  g.fillStyle = grd; g.fillRect(0, 0, 320, 200);
  g.fillStyle = "#2b2b2b"; g.fillRect(40, 120, 90, 60); g.fillStyle = "#f4f4f4"; g.beginPath(); g.arc(250, 50, 22, 0, 7); g.fill();
  return c.toDataURL("image/jpeg", 0.85);
}
