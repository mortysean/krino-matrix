// 语音：识别（STT）和朗读（TTS）。服务端配置了就走服务端（密钥只在服务端），否则用浏览器自带的能力。
// 麦克风只在用户点了按钮、浏览器授权之后才会打开；停止后立即关闭。
import { api, S, t } from "./core.js";
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
      res = await api("/api/voice/tts", { body: { text: text.slice(0, 600), rate, voice: voiceParams.voice || null, style: voiceParams.style || null }, raw: true });
    } catch (e) {  // 服务端语音出问题时退回浏览器朗读，不让她“哑掉”
      console.warn("服务端语音失败，改用浏览器朗读：", e.message);
      if (my !== gen) return { done: Promise.resolve() };
      return browserSpeak(text, rate, pitch);
    }
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
