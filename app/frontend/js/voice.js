// 语音：识别（STT）和朗读（TTS）。服务端配置了就走服务端（密钥只在服务端），否则用浏览器自带的能力。
// 麦克风只在用户点了按钮、浏览器授权之后才会打开；停止后立即关闭。
import { api, S, t, toast } from "./core.js";
import { getLocale } from "./i18n.js";

// 语音的语言跟着站点版本：国内版中文，海外版英文
const speechLang = () => (getLocale() === "en" ? "en-US" : "zh-CN");

let cfg = null;
export async function voiceConfig() {
  if (!cfg) cfg = await api("/api/voice/config").catch(() => ({ stt: {}, tts: {}, vlm: {} }));
  return cfg;
}

const BrowserSR = window.SpeechRecognition || window.webkitSpeechRecognition;

function pref(kind) { return S.me?.settings?.voice?.[kind] || "auto"; }

async function useServer(kind) {
  const c = await voiceConfig();
  const p = pref(kind);
  if (p === "browser") return false;
  if (p === "server") return !!c[kind]?.server;
  return !!c[kind]?.server;
}

// 识别走哪：server = 服务端识别（录音上传），browser = 浏览器自带（边说边出字），off = 关了
export async function sttMode() {
  if (pref("stt") === "off") return "off";
  return (await useServer("stt")) ? "server" : "browser";
}

export async function sttAvailable() {
  if (pref("stt") === "off") return { ok: false, why: t("语音输入在设置里关闭了") };
  if (await useServer("stt")) return { ok: !!navigator.mediaDevices?.getUserMedia, why: t("浏览器不支持录音") };
  return { ok: !!BrowserSR, why: t("这个浏览器不支持语音识别，可以在设置里配置服务端识别，或换用 Chrome / Edge") };
}

// 开始听；返回 stop()，stop 后 resolve 识别出的文字
export async function listen({ onPartial } = {}) {
  if (await useServer("stt")) return recordAndTranscribe();
  const sr = new BrowserSR();
  sr.lang = speechLang(); sr.interimResults = true; sr.continuous = true;
  let finalText = "", resolveFn, rejectFn;
  const done = new Promise((res, rej) => { resolveFn = res; rejectFn = rej; });
  sr.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finalText += e.results[i][0].transcript; else interim += e.results[i][0].transcript;
    }
    onPartial?.(finalText + interim);
  };
  sr.onerror = (e) => rejectFn(new Error(t({ "not-allowed": "没有麦克风权限", "no-speech": "没有听到声音", network: "语音识别需要联网" }[e.error] || "") || t("语音识别出错：{code}", { code: e.error })));
  sr.onend = () => resolveFn(finalText.trim());
  sr.start();
  return { stop: () => { sr.stop(); return done; }, cancel: () => sr.abort() };
}

async function recordAndTranscribe() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = ["audio/webm", "audio/ogg", "audio/mp4"].find((m) => window.MediaRecorder?.isTypeSupported?.(m)) || "";
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.start();
  const release = () => stream.getTracks().forEach((t) => t.stop());
  return {
    stop: () => new Promise((resolve, reject) => {
      rec.onstop = async () => {
        release();
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const fd = new FormData(); fd.append("file", blob, "speech." + (blob.type.split("/")[1] || "webm").split(";")[0]);
        try { resolve((await api("/api/voice/stt", { body: fd })).text || ""); } catch (e) { reject(e); }
      };
      rec.stop();
    }),
    cancel: () => { rec.stop(); release(); },
  };
}

// 朗读。返回 { audio?, done } ；audio 给 3D 形象做口型（浏览器朗读拿不到音频流，口型改用程序化）
let current = null, gen = 0;  // gen：每次停止或开始新的一句都加一，还在合成中的旧句子回来后作废，不会两句叠着读
export function stopSpeaking() {
  gen += 1;
  if (current?.audio) { current.audio.pause(); current.audio.src = ""; }
  if (current?.pcm) current.pcm.stop();
  window.speechSynthesis?.cancel();
  current = null;
}

// 朗读前去掉括号里的动作、*动作*、颜文字和 emoji（服务端也会再清理一遍）
// 颜文字连同括号外的装饰一起去掉：ヾ(≧▽≦*)o、m(_ _)m、٩(ˊᗜˋ)و、(￣▽￣)ゞ、(－ω－) zzZ；少了右括号的 (・_・ゞ 也算
const KAO_CLOSED = /[ヾヽ٩mｍo＼\\～~φΦ]{0,2}[（(]([^（()）\n]{0,40})[）)][ゞゝو*oｍm／/～~ﾉノ]{0,2}(?:\s?z+Z+)?/g;
const KAO_OPEN = /(?<![A-Za-z0-9_])[（(](?=[^\s（()）\u4e00-\u9fff]*[^A-Za-z0-9_\s（()）\u4e00-\u9fff])[^\s（()）\n\u4e00-\u9fffA-Za-z0-9]{1,12}/gu;
const WORDISH = /[\u4e00-\u9fff]|[A-Za-z]{3,}/;
export function speakable(text) {
  return (text || "")
    .replace(KAO_CLOSED, (m, inner) => (WORDISH.test(inner) ? m : ""))
    .replace(KAO_OPEN, "")
    .replace(/[（(][^（()）\n]{0,40}[）)]|\*[^*\n]{0,40}\*/g, "")
    .replace(/[\p{So}\p{Sm}\p{Sk}\p{Co}()（）・°ﾟ｡´｀`ω∀▽ᴗ˘◕‿╹ㅂ\uFE30-\uFE4F]/gu, "")
    .replace(/[ \t]{2,}/g, " ").trim();
}

export async function speak(text, voiceParams = {}) {
  stopSpeaking();
  text = speakable(text);
  if (pref("tts") === "off" || !text) return { done: Promise.resolve() };
  const my = gen;
  const rate = voiceParams.rate || 1, pitch = voiceParams.pitch || 1;
  if (await useServer("tts")) {
    let res;
    try {
      res = await api("/api/voice/tts", { body: { text: text.slice(0, 600), rate, voice: voiceParams.voice || null, style: voiceParams.style || null, stream: canStream() }, raw: true });
    } catch (e) {  // 只走自己的语音服务：出问题就如实报错，不偷偷换成浏览器朗读
      if (my !== gen) return { done: Promise.resolve() };
      throw e;
    }
    if ((res.headers.get("content-type") || "").startsWith("audio/pcm")) return playPcm(res, my);  // 边下边播
    const blob = await res.blob();
    if (my !== gen) return { done: Promise.resolve() };  // 合成期间又开始了新的一句（或被停止），这句不读了
    const audio = new Audio(URL.createObjectURL(blob));
    const done = new Promise((r) => { audio.onended = r; audio.onerror = r; });
    current = { audio };
    await audio.play().catch(() => {});
    return { audio, done };
  }
  return browserSpeak(text, rate, pitch);
}

// ---------- 流式朗读：服务端边合成边发 16-bit PCM，这里收到一段就排进播放队列 ----------
let actx = null;
const AC = window.AudioContext || window.webkitAudioContext;
function audioCtx() {
  if (!AC) return null;
  // 朗读的声音都是 24kHz：播放器也开在 24kHz，每一小段不用各自重采样（各自重采样，段和段接缝处会有细小的“咔”，听着不连贯）
  if (!actx) { try { actx = new AC({ sampleRate: 24000, latencyHint: "playback" }); } catch { actx = new AC(); } }
  if (actx.state === "suspended") actx.resume().catch(() => {});
  return actx;
}
// 浏览器要求用户先点过、按过键才能出声：每次点击、按键、触摸都确认一下播放器是开着的。
// 只在第一次交互时准备一次不够：那一下如果不算“用户操作”（比如输入法的按键），播放器会一直是暂停的，之后永远没声音
["pointerdown", "keydown", "touchend", "click"].forEach((ev) => addEventListener(ev, () => audioCtx(), { capture: true, passive: true }));
let warned = false;
function blocked(ctx) {  // 浏览器还不让出声：提示一次，点一下页面就好（resume 是异步的，稍等一下再看）
  if (!ctx || warned) return;
  setTimeout(() => {
    if (ctx.state === "running" || warned) return;
    warned = true;
    toast(t("浏览器还没允许播放声音：点一下页面就能听到"), 5000);
  }, 400);
}
const canStream = () => !!AC && !!window.ReadableStream;

function playPcm(res, my) {
  const ctx = audioCtx();
  blocked(ctx);
  const rate = +(res.headers.get("x-sample-rate") || 24000);
  const reader = res.body.getReader();
  // 小缓冲：攒够 0.25 秒的声音再开始播；中途断了（网络慢于播放）就再攒 0.15 秒，不让每个字之间“咔”一下。
  // 开播以后，手上排着的声音还多（超过 AHEAD 秒）就先攒着，攒够 MERGE 秒再拼成一整段排进去：段数少，接缝少
  const PREBUF = 0.25, REBUF = 0.15, MERGE = 0.6, AHEAD = 0.5;
  let at = 0, left = null, stopped = false, last = null, finish, pending = [], pendingDur = 0, started = false;
  const done = new Promise((r) => (finish = r));
  const nodes = new Set();
  function flush() {
    if (stopped || my !== gen) { pending = []; pendingDur = 0; return; }
    if (pending.length > 1) {  // 拼成一段
      const n = pending.reduce((k, b) => k + b.length, 0), one = ctx.createBuffer(1, n, pending[0].sampleRate), out = one.getChannelData(0);
      let o = 0; for (const b of pending) { out.set(b.getChannelData(0), o); o += b.length; }
      pending = [one];
    }
    for (const buf of pending) {
      const src = ctx.createBufferSource();
      src.buffer = buf; src.connect(ctx.destination);
      at = Math.max(at, ctx.currentTime + 0.03);  // 首尾相接；断过就从现在往后一点接上
      src.start(at); at += buf.duration;
      nodes.add(src); src.onended = () => nodes.delete(src);
      last = src;
    }
    if (pending.length) started = true;
    pending = []; pendingDur = 0;
  }
  const pcm = { stop() { stopped = true; reader.cancel().catch(() => {}); nodes.forEach((n) => { try { n.stop(); } catch {} }); finish(); } };
  current = { pcm };
  (async () => {
    try {
      for (;;) {
        const { value, done: end } = await reader.read();
        if (end || stopped || my !== gen) break;
        let bytes = value;
        if (left) { const m = new Uint8Array(left.length + bytes.length); m.set(left); m.set(bytes, left.length); bytes = m; left = null; }
        if (bytes.length % 2) { left = bytes.slice(-1); bytes = bytes.slice(0, -1); }
        if (!bytes.length) continue;
        const i16 = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.length / 2);
        const buf = ctx.createBuffer(1, i16.length, rate);
        const ch = buf.getChannelData(0);
        for (let i = 0; i < i16.length; i++) ch[i] = i16[i] / 32768;
        pending.push(buf); pendingDur += buf.duration;
        const underrun = started && at < ctx.currentTime + 0.02;  // 已经播完了手上的声音
        if (underrun) started = false;
        if (!started && pendingDur < (at ? REBUF : PREBUF)) continue;
        if (started && pendingDur < MERGE && at - ctx.currentTime > AHEAD) continue;  // 前面还够播：再攒一点，拼大一点
        flush();
      }
      flush();  // 结束：剩下不足一个缓冲的也播掉
    } catch { flush(); /* 断开：已经收到的照常播完 */ }
    if (stopped || my !== gen) return finish();
    if (!last) return finish();
    // 播完再算“读完了”：按排好的结束时间等，不靠最后一段的 onended（那一段可能已经播完，再挂上去就永远等不到，按钮一直亮着）
    const remain = Math.max(0, at - ctx.currentTime);  // 别叫 left：外面的 left 存着半个采样，同名会让整段报错、一个字都不播
    setTimeout(() => { if (!stopped) finish(); }, remain * 1000 + 80);
  })();
  return { done };
}

function browserSpeak(text, rate, pitch) {
  if (!window.speechSynthesis) return { done: Promise.resolve() };
  const u = new SpeechSynthesisUtterance(text);
  u.lang = speechLang(); u.rate = rate; u.pitch = pitch;
  const prefix = getLocale() === "en" ? "en" : "zh";
  const v = speechSynthesis.getVoices().find((x) => x.lang.startsWith(prefix));
  if (v) u.voice = v;
  const done = new Promise((r) => { u.onend = r; u.onerror = r; });
  current = { utterance: u };
  speechSynthesis.speak(u);
  return { done };
}

// ---------- 直接听：录下你的声音（16kHz 单声道 WAV），整段交给她，不先转成文字 ----------
export async function canHear() {
  if (pref("stt") === "off") return false;
  return !!(await voiceConfig()).hear && !!navigator.mediaDevices?.getUserMedia && !!(window.AudioContext || window.webkitAudioContext);
}

// 开始录音；返回 { stop() → data URL, cancel(), level() → 0~1 的音量（给按钮做动画） }
export async function record({ maxSeconds = 60, onLimit } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const AC = window.AudioContext || window.webkitAudioContext;
  const ac = new AC();
  const src = ac.createMediaStreamSource(stream);
  const node = ac.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  let level = 0, total = 0, done = false;
  node.onaudioprocess = (e) => {
    if (done) return;
    const d = e.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(d));
    total += d.length;
    let peak = 0; for (let i = 0; i < d.length; i += 64) peak = Math.max(peak, Math.abs(d[i]));
    level = level * 0.6 + peak * 0.4;
    if (total / ac.sampleRate >= maxSeconds) onLimit?.();
  };
  src.connect(node); node.connect(ac.destination);
  const close = () => { done = true; node.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop()); ac.close().catch(() => {}); };
  return {
    level: () => Math.min(1, level * 3),
    cancel: close,
    stop() {
      const rate = ac.sampleRate;
      close();
      if (total < rate * 0.4) return null;  // 不到半秒：当作没说
      const all = new Float32Array(total); let o = 0;
      for (const c of chunks) { all.set(c, o); o += c.length; }
      return toWav(downsample(all, rate, 16000), 16000);
    },
  };
}

// ---------- 语音对话用：一直开着的麦克风，一帧一帧交给调用方（自己判断什么时候开口、什么时候说完） ----------
// 返回 { rate, onFrame(cb), close() }；cb(Float32Array 一帧, rms 音量)。一帧 2048 个采样，约 43 毫秒
export async function openMic() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  const AC = window.AudioContext || window.webkitAudioContext;
  const ac = new AC();
  if (ac.state === "suspended") await ac.resume().catch(() => {});
  const src = ac.createMediaStreamSource(stream);
  const node = ac.createScriptProcessor(2048, 1, 1);
  let cb = null, closed = false;
  node.onaudioprocess = (e) => {
    if (closed || !cb) return;
    const d = new Float32Array(e.inputBuffer.getChannelData(0));
    let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i] * d[i];
    cb(d, Math.sqrt(s / (d.length / 4)));
  };
  src.connect(node); node.connect(ac.destination);
  return {
    rate: ac.sampleRate,
    onFrame(f) { cb = f; },
    close() { if (closed) return; closed = true; node.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop()); ac.close().catch(() => {}); },
  };
}

// 把几帧拼起来，转成 16kHz WAV 的 data URL（直接交给她听，或者先送去识别）
export function framesToWav(frames, rate) {
  const total = frames.reduce((n, f) => n + f.length, 0);
  const all = new Float32Array(total); let o = 0;
  for (const f of frames) { all.set(f, o); o += f.length; }
  return toWav(downsample(all, rate, 16000), 16000);
}

// WAV data URL → 服务端识别 → 文字
export async function transcribeWav(dataUrl) {
  const blob = await (await fetch(dataUrl)).blob();
  const fd = new FormData(); fd.append("file", blob, "speech.wav");
  return ((await api("/api/voice/stt", { body: fd })).text || "").trim();
}

function downsample(buf, from, to) {
  if (from === to) return buf;
  const ratio = from / to, out = new Float32Array(Math.floor(buf.length / ratio));
  for (let i = 0; i < out.length; i++) {  // 简单的区间平均，够说话用
    const a = Math.floor(i * ratio), b = Math.min(buf.length, Math.floor((i + 1) * ratio));
    let s = 0; for (let j = a; j < b; j++) s += buf[j];
    out[i] = s / Math.max(1, b - a);
  }
  return out;
}

function toWav(samples, rate) {
  const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
  let bin = ""; const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return "data:audio/wav;base64," + btoa(bin);
}
