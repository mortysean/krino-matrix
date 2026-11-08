// 语音对话（边听边回）：参照 ChatGPT 的语音模式。点一下进来就能说，不用再按任何键：
//   听你说 → 你停下约 0.9 秒就算说完 → 交给她 → 她边合成边念 → 念完自动接着听。
//   她说话时你一开口就打断她（或者点一下中间的光球）；“静音”只是暂时不听，“结束”回到打字。
// 判断开口 / 说完用的是音量（自适应环境噪声），不依赖任何服务。能“直接听”的就把录音整段交给她，
// 否则先在服务端识别成文字再发；两样都没有时退回浏览器自带识别（这种情况不能打断，只能点光球）。
import { esc, fail, t, toast } from "./core.js";
import { ICON } from "./icons.js";
import { canHear, framesToWav, listen, openMic, speakable, sttMode, stopSpeaking, transcribeWav } from "./voice.js";

const SILENCE_MS = 900;    // 停这么久算说完
const MIN_SPEECH_MS = 350; // 比这短的声音（咳嗽、碰桌子）不算
const MAX_TURN_S = 30;     // 一口气最多说这么久
const PREROLL = 8;         // 开口前多留几帧（约 0.35 秒），不吃掉第一个字

export function createVoiceMode({ host, submit, onExit }) {
  let el = null, mic = null, state = "off", muted = false, how = "hear", ended = false;
  let frames = [], pre = [], loud = 0, quiet = 0, voiced = 0, floor = 0, echo = 0, level = 0;
  let speaking = null, sr = null, srTimer = 0, raf = 0;

  // ---------- 界面 ----------
  const STATUS = {
    listening: () => t("在听……"),
    hearing: () => t("在听……"),
    thinking: () => t("她在想……"),
    speaking: () => (how === "browser" ? t("她在说话，点一下光球可以打断") : t("她在说话，直接开口就能打断")),
    muted: () => t("麦克风已静音"),
  };
  function build() {
    el = document.createElement("div");
    el.className = "vm";
    el.innerHTML = `
      <div class="vm-stage">
        <button class="vm-orb" type="button" title="${esc(t("点一下：打断她，或者表示你说完了"))}"><i></i><i></i><i></i></button>
        <div class="vm-status" aria-live="polite"></div>
        <div class="vm-caption"></div>
      </div>
      <div class="vm-bar">
        <button class="vm-btn vm-mute" type="button"></button>
        <button class="vm-btn vm-end" type="button">✕ <span>${esc(t("结束"))}</span></button>
      </div>`;
    host.appendChild(el);
    el.querySelector(".vm-orb").onclick = tapOrb;
    el.querySelector(".vm-mute").onclick = () => setMuted(!muted);
    el.querySelector(".vm-end").onclick = () => stop();
    requestAnimationFrame(() => el.classList.add("in"));
  }
  function render() {
    if (!el) return;
    const s = muted && state !== "thinking" && state !== "speaking" ? "muted" : state;
    el.dataset.state = s;
    el.querySelector(".vm-status").textContent = STATUS[s]?.() || "";
    const m = el.querySelector(".vm-mute");
    m.classList.toggle("on", muted);
    m.innerHTML = `${ICON.mic} <span>${esc(muted ? t("取消静音") : t("静音"))}</span>`;
  }
  function caption(text, who) {
    const c = el?.querySelector(".vm-caption");
    if (!c) return;
    c.className = "vm-caption " + (who || "");
    c.textContent = text ? (text.length > 120 ? text.slice(0, 118) + "…" : text) : "";
  }
  function animate() {  // 光球跟着音量放大：你说话时看你的声音，她说话时看她的（拿不到她的音量，就做呼吸）
    raf = requestAnimationFrame(animate);
    if (!el) return;
    const lv = state === "hearing" || state === "listening" ? Math.min(1, level * 9) : 0;
    el.style.setProperty("--lv", lv.toFixed(3));
  }

  // ---------- 状态 ----------
  function set(s) { state = s; render(); }
  function setMuted(on) {
    muted = on;
    if (on && state === "hearing") resetTurn();
    if (on && sr) { sr.cancel(); sr = null; }
    if (!on && state === "listening" && how === "browser") browserTurn();
    render();
  }
  function resetTurn() { frames = []; loud = 0; quiet = 0; voiced = 0; if (state === "hearing") set("listening"); }

  function tapOrb() {
    if (state === "speaking") return interrupt();
    if (state === "hearing") return finishTurn();
    if (state === "listening" && muted) setMuted(false);
  }
  function interrupt() {
    stopSpeaking();
    speaking = null;
    set("listening");
    if (how === "browser") browserTurn();
  }

  // ---------- 判断开口 / 说完（音量 + 自适应噪声底） ----------
  function onFrame(f, rms) {
    level = rms;
    if (ended) return;
    const ms = (f.length / mic.rate) * 1000;
    // 噪声底：安静时慢慢跟上，有声音时几乎不动
    floor = floor ? (rms < floor * 1.5 ? floor * 0.95 + rms * 0.05 : floor * 0.998 + rms * 0.002) : rms;
    const on = Math.max(0.012, floor * 3), off = Math.max(0.008, floor * 2);
    pre.push(f); if (pre.length > PREROLL) pre.shift();

    if (state === "speaking" && how !== "browser" && !muted) {
      // 她在说话：音箱的声音会漏进麦克风，门槛抬高到漏音的两倍多，还要持续 0.2 秒以上才算你在插话
      const bar = Math.max(on * 2.5, echo * 2.2);
      if (rms < bar) { echo = echo ? echo * 0.97 + rms * 0.03 : rms; loud = 0; return; }
      loud += ms;
      if (loud >= 200) { interrupt(); frames = [...pre]; voiced = loud; quiet = 0; set("hearing"); }
      return;
    }
    if (muted || how === "browser") return;
    if (state === "listening") {
      if (rms > on) { loud += ms; if (loud >= 130) { frames = [...pre]; voiced = loud; quiet = 0; set("hearing"); } }
      else loud = 0;
      return;
    }
    if (state === "hearing") {
      frames.push(f);
      if (rms > off) { voiced += ms; quiet = 0; } else quiet += ms;
      const len = frames.length * ms;
      if (quiet >= SILENCE_MS || len >= MAX_TURN_S * 1000) finishTurn();
    }
  }

  async function finishTurn() {
    if (state !== "hearing") return;
    const got = frames; frames = []; loud = 0; quiet = 0;
    if (voiced < MIN_SPEECH_MS) { voiced = 0; return set("listening"); }
    voiced = 0;
    set("thinking");
    const wav = framesToWav(got, mic.rate);
    try {
      if (how === "hear") await reply({ audio: wav });
      else {
        const text = await transcribeWav(wav);
        if (ended) return;
        if (!text) { toast("没听清，再说一次？"); return set("listening"); }
        caption(text, "you");
        await reply({ text });
      }
    } catch (e) { if (!ended) { fail(e); set("listening"); } }
  }

  // 交给她，等她念完再接着听
  async function reply(payload) {
    const r = await submit(payload);
    if (ended) return;
    if (!r?.ok) return set("listening");
    caption(speakable(r.reply || ""), "her");  // 字幕跟她念的一样：不带动作描写和颜文字
    if (!r.speaking) return set("listening");
    set("speaking"); echo = 0; loud = 0;
    const mine = (speaking = r.speaking);
    await mine;
    if (ended || speaking !== mine) return;  // 被打断了：打断时已经切到“在听”
    speaking = null;
    set("listening");
    if (how === "browser") browserTurn();
  }

  // ---------- 浏览器自带识别（没有服务端识别、也不能直接听时）：边说边出字，1.2 秒没有新字就算说完 ----------
  async function browserTurn() {
    if (ended || muted || sr) return;
    let l = null;
    try {
      l = await listen({ onPartial: (x) => {
        caption(x, "you");
        if (state === "listening") set("hearing");
        clearTimeout(srTimer);
        srTimer = setTimeout(() => finishBrowser(l), 1200);
      } });
    } catch (e) { if (!ended) fail(e); return; }
    sr = l;
    clearTimeout(srTimer);
    srTimer = setTimeout(() => finishBrowser(l), 8000);  // 一直没开口：浏览器自己会停，重新开始听
  }
  async function finishBrowser(l) {
    if (!l || sr !== l) return;
    sr = null;
    let text = "";
    try { text = await l.stop(); } catch { /* 没听到声音之类：重新开始听 */ }
    if (ended) return;
    if (!text) { set("listening"); return browserTurn(); }
    set("thinking");
    try { await reply({ text }); } catch (e) { if (!ended) { fail(e); set("listening"); browserTurn(); } }
  }

  // ---------- 进出 ----------
  async function start() {
    if (el) return;
    ended = false; muted = false; floor = 0; echo = 0;
    const mode = await sttMode();
    how = (await canHear()) ? "hear" : mode === "server" ? "stt" : mode === "browser" ? "browser" : "";
    if (!how) return toast("语音输入在设置里关闭了");
    if (how !== "browser" && !navigator.mediaDevices?.getUserMedia) return toast("浏览器不支持录音");
    build();
    set("listening");
    animate();
    if (how === "browser") return browserTurn();
    try {
      mic = await openMic();
      mic.onFrame(onFrame);
    } catch (e) {
      stop();
      toast(e.name === "NotAllowedError" ? "没有麦克风权限：请在浏览器地址栏允许麦克风" : "✕ " + (e.message || e), 5000);
    }
  }
  function stop() {
    if (!el) return;
    ended = true;
    cancelAnimationFrame(raf);
    clearTimeout(srTimer);
    sr?.cancel(); sr = null;
    mic?.close(); mic = null;
    stopSpeaking(); speaking = null;
    const old = el; el = null; state = "off";
    old.classList.remove("in");
    setTimeout(() => old.remove(), 250);
    onExit?.();
  }

  return { start, stop, get active() { return !!el; } };
}
