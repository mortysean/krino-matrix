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

// 朗读。边生成边念（createSpeech）：回复一段段流过来，凑够一句就送去合成，声音接在上一句后面播，不用等整句生成完。
// speak(text) 是只有一段文字时的简写。gen：每次停止或开始新的朗读都加一，还在合成中的旧句子回来后作废，不会两段叠着读
let current = null, gen = 0;
export function stopSpeaking() {
  gen += 1;
  current?.stop?.();
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

// 她说话的声音都先经过一个音量节点（你插话时先把她压低，duck），再经过分析节点：形象拿它对口型（嘴张多大、Q 版小人什么时候停下说话的片段）。
// 没有在播、或者是浏览器朗读（拿不到声音）时 speechLevel() 返回 null，形象退回按时间做的口型
let out = null, lastLevel = 0, lastAt = 0;
function speechOut(ctx) {
  if (!out || out.ctx !== ctx) {
    const gain = ctx.createGain(), an = ctx.createAnalyser();
    an.fftSize = 512; an.smoothingTimeConstant = 0.2;
    gain.connect(an); an.connect(ctx.destination);
    out = { ctx, gain, an, buf: new Float32Array(an.fftSize) };
  }
  return out.gain;
}
export function speechLevel() {
  if (!out || !current || current.browser || out.ctx.state !== "running") return null;
  out.an.getFloatTimeDomainData(out.buf);
  let sum = 0; for (const v of out.buf) sum += v * v;
  const rms = Math.sqrt(sum / out.buf.length);
  // 说话的 RMS 大约 0.02~0.25：压到 0~1，起得快落得慢（按时间衰减，约 70 毫秒落一半），嘴不会一帧一帧地抖
  const lv = Math.min(1, Math.max(0, (rms - 0.012) * 6)), now = performance.now();
  const keep = Math.exp(-(now - lastAt) / 100); lastAt = now;
  lastLevel = lv > lastLevel ? lv : lastLevel * keep + lv * (1 - keep);
  return lastLevel;
}
// 你一开口她先把声音压低（像人被插话时会收一下），确认你只是“嗯”一声就恢复
export function duck(on) {
  if (!out) return;
  out.gain.gain.setTargetAtTime(on ? 0.3 : 1, out.ctx.currentTime, on ? 0.03 : 0.12);
}

// 语音压成 Opus 发过来，带宽只要原始 PCM 的约 1/12。流式的用 WebCodecs 边收边解（不支持的浏览器照旧要 PCM），整句的直接交给 <audio>
let opusStream = null;
function canOpusStream() {
  opusStream ??= window.AudioDecoder && window.EncodedAudioChunk
    ? AudioDecoder.isConfigSupported({ codec: "opus", sampleRate: 48000, numberOfChannels: 1 }).then((r) => !!r.supported).catch(() => false)
    : Promise.resolve(false);
  return opusStream;
}
const canOpusFile = () => { try { return !!new Audio().canPlayType('audio/ogg; codecs="opus"'); } catch { return false; } };

// 播放队列：解出来的声音一段段排进去（流式 PCM 和流式 Opus 共用，一次朗读里的几句也共用一个，句子之间不断）。
// gate：在它 resolve 之前只收不播（语音对话里先合成好，等确认你说完了再出声）；reject 就整段作废。
// mark(i)：后面收到的声音属于第 i 句；onMark(i, 开始播放的时刻) 告诉调用方每一句什么时候开始响
function queue(ctx, my, { gate = null, onMark = null } = {}) {
  // 小缓冲：攒够 0.25 秒的声音再开始播；中途断了（网络慢于播放）就再攒 0.15 秒，不让每个字之间“咔”一下。
  // 开播以后，手上排着的声音还多（超过 AHEAD 秒）就先攒着，攒够 MERGE 秒再拼成一整段排进去：段数少，接缝少
  const PREBUF = 0.25, REBUF = 0.15, MERGE = 0.6, AHEAD = 0.5;
  let at = 0, stopped = false, last = null, finish, pending = [], pendingDur = 0, pendingLen = 0, started = false;
  let open = !gate, ending = false, marks = [];  // marks：[句子编号, 在 pending 里从第几个采样开始]
  const done = new Promise((r) => (finish = r));
  const nodes = new Set();
  const off = () => stopped || my !== gen;
  function flush() {
    if (off()) { pending = []; pendingDur = 0; pendingLen = 0; marks = []; return; }
    if (!pending.length) return;
    const rate = pending[0].sampleRate;
    if (pending.length > 1) {  // 拼成一段
      const one = ctx.createBuffer(1, pendingLen, rate), o2 = one.getChannelData(0);
      let o = 0; for (const b of pending) { o2.set(b.getChannelData(0), o); o += b.length; }
      pending = [one];
    }
    const buf = pending[0], src = ctx.createBufferSource();
    src.buffer = buf; src.connect(speechOut(ctx));
    at = Math.max(at, ctx.currentTime + 0.03);  // 首尾相接；断过就从现在往后一点接上
    const wall = performance.now() + (at - ctx.currentTime) * 1000;
    for (const [i, off0] of marks) onMark?.(i, wall + (off0 / rate) * 1000);
    src.start(at); at += buf.duration;
    nodes.add(src); src.onended = () => nodes.delete(src);
    last = src; started = true;
    pending = []; pendingDur = 0; pendingLen = 0; marks = [];
  }
  function finishEnd() {  // 收完了（或断开）：剩下不足一个缓冲的也播掉，播完再算“读完了”
    flush();
    if (off() || !last) return finish();
    // 按排好的结束时间等，不靠最后一段的 onended（那一段可能已经播完，再挂上去就永远等不到，按钮一直亮着）
    const remain = Math.max(0, at - ctx.currentTime);
    setTimeout(() => { if (!stopped) finish(); }, remain * 1000 + 80);
  }
  const q = {
    done, off,
    mark(i) { marks.push([i, pendingLen]); },
    push(samples, rate) {
      if (off() || !samples.length) return;
      const buf = ctx.createBuffer(1, samples.length, rate);
      buf.getChannelData(0).set(samples);
      pending.push(buf); pendingDur += buf.duration; pendingLen += buf.length;
      if (!open) return;
      const underrun = started && at < ctx.currentTime + 0.02;  // 已经播完了手上的声音
      if (underrun) started = false;
      if (!started && pendingDur < (at ? REBUF : PREBUF)) return;
      if (started && pendingDur < MERGE && at - ctx.currentTime > AHEAD) return;  // 前面还够播：再攒一点，拼大一点
      flush();
    },
    end() { ending = true; if (open) finishEnd(); },
    stop() { stopped = true; nodes.forEach((n) => { try { n.stop(); } catch {} }); finish(); },
  };
  gate?.then(() => { open = true; if (ending) finishEnd(); else if (pendingDur >= PREBUF) flush(); }, () => q.stop());
  return q;
}

// 读一个流式 PCM 回复，排进队列；读完 resolve（不代表播完）
async function readPcm(res, q) {
  const rate = +(res.headers.get("x-sample-rate") || 24000);
  const reader = res.body.getReader();
  q.cancel = () => reader.cancel().catch(() => {});
  let left = null;  // 上一段末尾多出来的半个采样
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end || q.off()) break;
      let bytes = value;
      if (left) { const m = new Uint8Array(left.length + bytes.length); m.set(left); m.set(bytes, left.length); bytes = m; left = null; }
      if (bytes.length % 2) { left = bytes.slice(-1); bytes = bytes.slice(0, -1); }
      if (!bytes.length) continue;
      const i16 = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.length / 2);
      const f = new Float32Array(i16.length);
      for (let i = 0; i < i16.length; i++) f[i] = i16[i] / 32768;
      q.push(f, rate);
    }
  } catch { /* 断开：已经收到的照常播完 */ }
}

// Ogg 拆包：收到多少喂多少，吐出完整的包（第一个是 OpusHead，第二个是 OpusTags，之后是声音）
function oggPackets() {
  let buf = new Uint8Array(0), part = [];
  const join = (xs) => { if (xs.length === 1) return xs[0]; const out = new Uint8Array(xs.reduce((k, x) => k + x.length, 0)); let o = 0; for (const x of xs) { out.set(x, o); o += x.length; } return out; };
  return (chunk) => {
    const m = new Uint8Array(buf.length + chunk.length); m.set(buf); m.set(chunk, buf.length); buf = m;
    const out = [];
    let o = 0;
    while (buf.length - o >= 27) {
      const nseg = buf[o + 26], body = o + 27 + nseg;
      if (buf.length < body) break;
      let size = 0; for (let i = o + 27; i < body; i++) size += buf[i];
      if (buf.length < body + size) break;
      let p = body;
      for (let i = o + 27; i < body; i++) {
        const l = buf[i];
        part.push(buf.slice(p, p + l)); p += l;
        if (l < 255) { out.push(join(part)); part = []; }
      }
      o = p;
    }
    buf = buf.slice(o);
    return out;
  };
}

// 读一个流式 Ogg Opus 回复，用 WebCodecs 边收边解，排进队列
async function readOpus(res, q, ctx) {
  const reader = res.body.getReader();
  let dec = null;
  q.cancel = () => { reader.cancel().catch(() => {}); try { dec?.close(); } catch {} };
  const out = (d) => {
    const f = new Float32Array(d.numberOfFrames);
    d.copyTo(f, { planeIndex: 0, format: "f32-planar" });
    const r = d.sampleRate; d.close();
    // 解码器一般出 48kHz；播放器开在 24kHz（见 audioCtx）：两两取平均降回去，免得每段各自重采样、接缝处“咔”
    if (r === ctx.sampleRate * 2) {
      const h = new Float32Array(f.length >> 1);
      for (let i = 0; i < h.length; i++) h[i] = (f[2 * i] + f[2 * i + 1]) / 2;
      q.push(h, ctx.sampleRate);
    } else q.push(f, r);
  };
  const split = oggPackets();
  let n = 0, ts = 0;
  try {
    for (;;) {
      const { value, done: end } = await reader.read();
      if (end || q.off()) break;
      for (const pkt of split(value)) {
        n++;
        if (n === 1) {
          dec = new AudioDecoder({ output: out, error: () => {} });
          dec.configure({ codec: "opus", sampleRate: 48000, numberOfChannels: 1, description: pkt });
        } else if (n > 2) {
          dec.decode(new EncodedAudioChunk({ type: "key", timestamp: ts, data: pkt }));
          ts += 20000;
        }
      }
    }
    if (dec?.state === "configured") await dec.flush();
  } catch { /* 断开：已经解出来的照常播完 */ }
  try { dec?.close(); } catch {}
}

// 回复里哪里可以断句：句末标点；英文的句点要后面跟空格。第一句太长、迟迟没有句号时，在逗号处先断，早点开口
const END = /[。！？!?…~～\n]+|[.](?=\s)|[;；]/g;
function cutPoint(buf, first) {
  let k = -1;
  for (const m of buf.matchAll(END)) k = m.index + m[0].length;
  if (k < 0 && first && buf.length >= 16) {
    const c = Math.max(buf.lastIndexOf("，"), buf.lastIndexOf(","), buf.lastIndexOf("、"));
    if (c >= 6) k = c + 1;
  }
  return k;
}

// 边生成边念。add(文字片段) / end() / stop()；
//   done   念完（或被停止）时 resolve
//   ready  第一句合成成功时 resolve，出错时 reject（只走自己的语音服务：出问题就如实报错，不偷偷换成浏览器朗读）
//   heard()  已经开始念出来的那几句（被打断时告诉后端她说到哪了）
// gate：先合成、等它 resolve 才出声；onStart：第一个声音真正开始播放时
export function createSpeech(voiceParams = {}, { gate = null, onStart = null } = {}) {
  stopSpeaking();
  const my = gen;
  const rate = voiceParams.rate || 1, pitch = voiceParams.pitch || 1;
  const said = [];  // [{ text, at }]：at = 开始响的时刻（performance.now），还没响是 null
  let buf = "", ended = false, stopped = false, stoppedAt = 0, busy = false, kind = null, q = null, audio = null, chain = Promise.resolve();
  let finish, okReady, badReady, started = false;
  const done = new Promise((r) => (finish = r));
  const ready = new Promise((a, b) => { okReady = a; badReady = b; });
  ready.catch(() => {});
  const off = () => stopped || my !== gen;
  const mark = (i, t) => {
    said[i].at = t;
    if (!started) { started = true; setTimeout(() => !off() && onStart?.(), Math.max(0, t - performance.now())); }
  };
  const me = {
    done, ready,
    add(text) {
      if (off() || ended || !text) return;
      buf += text;
      pump();
    },
    end() { if (ended || off()) return; ended = true; pump(); },
    stop() {
      if (stopped) return;
      stopped = true; stoppedAt = performance.now();
      q?.stop(); q?.cancel?.();
      if (audio) { audio.pause(); audio.src = ""; }
      if (kind === "browser") window.speechSynthesis?.cancel();
      okReady(); finish();
    },
    heard() {  // 已经开始响的那几句（停下之后排在后面、还没响的不算）
      const t = stoppedAt || performance.now();
      return said.filter((x) => x.at != null && x.at <= t).map((x) => x.text).join("");
    },
    get started() { return started; },
  };
  current = me;
  if (out) out.gain.gain.value = 1;  // 上一次被压低过：新的一段恢复正常音量

  // 取出能念的一段：合成空闲时把攒到的整句一次拿走（第一句尽快拿，后面的几句合在一起，请求少、接缝少）
  function take() {
    const k = ended ? buf.length : cutPoint(buf, !said.length);
    if (k <= 0) return null;
    const text = buf.slice(0, k); buf = buf.slice(k);
    const clean = speakable(text);
    if (!clean) return take();
    said.push({ text: clean, at: null });
    return { text: clean, i: said.length - 1 };
  }

  async function pump() {
    if (busy || off()) return;
    busy = true;
    try {
      kind ||= pref("tts") === "off" ? "off" : (await useServer("tts")) ? "server" : "browser";
      for (let one; !off() && (one = take());) {
        if (kind === "off") continue;
        if (kind === "browser") { browserSay(one); continue; }
        await serverSay(one);
      }
    } catch (e) {
      if (!off()) { badReady(e); me.stop(); }
      return;
    } finally { busy = false; }
    if (off()) return;
    if (buf && !ended) return;  // 还有半句在等后文
    if (ended && !buf) wrapUp();
  }

  let wrapped = false;
  function wrapUp() {
    if (wrapped) return;
    wrapped = true;
    okReady();
    if (kind === "off" || !said.length) return finish();
    if (q) { q.end(); q.done.then(finish); return; }
    if (kind === "browser") { chain.then(finish); return; }
    chain.then(finish);
  }

  async function serverSay({ text, i }) {
    const stream = canStream();
    const res = await api("/api/voice/tts", { body: { text: text.slice(0, 600), rate, voice: voiceParams.voice || null, style: voiceParams.style || null, stream,
      opus_stream: stream && await canOpusStream(), opus_file: canOpusFile() }, raw: true });
    okReady();
    if (off()) return;
    const opus = res.headers.get("x-audio-stream") === "opus";
    if (opus || (res.headers.get("content-type") || "").startsWith("audio/pcm")) {  // 边下边播：几句接在同一个队列里
      const ctx = audioCtx();
      blocked(ctx);
      q ||= queue(ctx, my, { gate, onMark: mark });
      q.mark(i);
      await (opus ? readOpus(res, q, ctx) : readPcm(res, q));
      return;
    }
    const blob = await res.blob();  // 整段的音频文件：下一句先合成好，等这句放完接着放
    if (off()) return;
    chain = chain.then(() => playFile(blob, i));
  }

  async function playFile(blob, i) {
    if (gate) await gate.catch(() => me.stop());
    if (off()) return;
    const a = new Audio(URL.createObjectURL(blob));
    audio = a;
    const ctx = audioCtx();
    // 也接进音量和分析节点给口型用；播放器还没被允许出声时不接（接了会没声音），口型退回按时间做
    if (ctx?.state === "running") { try { ctx.createMediaElementSource(a).connect(speechOut(ctx)); } catch { /* 已经接过 */ } }
    const ended = new Promise((r) => { a.onended = r; a.onerror = r; a.onpause = r; });
    a.onplaying = () => mark(i, performance.now());
    await a.play().catch(() => {});
    await ended;
    URL.revokeObjectURL(a.src);
  }

  function browserSay({ text, i }) {  // 浏览器自带朗读：拿不到声音，口型按时间做
    current = Object.assign(me, { browser: true });
    if (!window.speechSynthesis) return;
    chain = chain.then(async () => {
      if (gate) await gate.catch(() => me.stop());
      if (off()) return;
      const u = new SpeechSynthesisUtterance(text);
      u.lang = speechLang(); u.rate = rate; u.pitch = pitch;
      const prefix = getLocale() === "en" ? "en" : "zh";
      const v = speechSynthesis.getVoices().find((x) => x.lang.startsWith(prefix));
      if (v) u.voice = v;
      u.onstart = () => mark(i, performance.now());
      const fin = new Promise((r) => { u.onend = r; u.onerror = r; });
      speechSynthesis.speak(u);
      await fin;
    });
  }

  return me;
}

// 附和：你说了很久、停下喘口气时，她用自己的声音轻轻“嗯”一声（音量压低，不打断你，也不算她在说话）。
// 每个音色只合成一次，之后直接播；合成不了就算了
const hums = new Map();
export async function hum(voiceParams = {}, { text = getLocale() === "en" ? "Mm-hm." : "嗯。", play = true } = {}) {
  const ctx = audioCtx();
  if (!ctx || ctx.state !== "running" || pref("tts") === "off" || !(await useServer("tts"))) return 0;
  const key = (voiceParams.voice || "") + "|" + text;
  if (!hums.has(key)) {
    hums.set(key, api("/api/voice/tts", { body: { text, voice: voiceParams.voice || null, style: voiceParams.style || null }, raw: true })
      .then((r) => r.arrayBuffer()).then((b) => ctx.decodeAudioData(b)).catch(() => null));
  }
  const buf = await hums.get(key);
  if (!buf || !play) return 0;
  const src = ctx.createBufferSource(), g = ctx.createGain();
  g.gain.value = 0.45;
  src.buffer = buf; src.connect(g); g.connect(ctx.destination);
  src.start();
  return buf.duration;
}
// 提前合成好“嗯”，第一次用时不用等
export function warmHum(voiceParams = {}) { hum(voiceParams, { play: false }).catch(() => {}); }

// 念一段完整的文字：返回 { done }；合成失败时抛出（第一句出错就报，不偷偷换成浏览器朗读）
export async function speak(text, voiceParams = {}, opts = {}) {
  const s = createSpeech(voiceParams, opts);
  s.add(text); s.end();
  await s.ready;
  return { done: s.done, speech: s };
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
