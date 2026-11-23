// 语音对话（边听边回）：参照 ChatGPT 的语音模式和全双工模型的做法。点一下进来就能说，不用再按任何键：
//   听你说 → 你停下 0.45 秒就先把这段交给她（先想着，不出声）→ 停满 0.8 秒才算真的说完，她开口
//     （回复边生成边念，第一句出来就开始说）→ 念完自动接着听。
//   0.8 秒之前你又开口了：撤回这一轮，把前后两段合成一句重新交给她，她没出过声，你也听不出来。
//   你说得久时，停下喘口气，她会轻轻“嗯”一声、点个头。
//   她说话时你开口：她先把声音压低；只是“嗯”“对”一声就恢复接着说，说了 0.6 秒以上才算打断（或者点一下中间的光球）。
//   被打断时告诉后端她其实只说到哪，聊天记录只留你听到的那部分。“静音”只是暂时不听，“结束”回到打字。
// 判断开口 / 说完用的是音量（自适应环境噪声），不依赖任何服务。能“直接听”的就把录音整段交给她，
// 否则先在服务端识别成文字再发；两样都没有时退回浏览器自带识别（这种情况不能打断，只能点光球）。
import { esc, fail, t, toast } from "./core.js";
import { ICON } from "./icons.js";
import { pixelOrb } from "./pixelbg.js";
import { canHear, duck, framesToWav, listen, openMic, speakable, sttMode, stopSpeaking, transcribeWav } from "./voice.js";

const SPECULATE_MS = 450;  // 停这么久：先把这段交给她想着（不出声）
const COMMIT_MS = 800;     // 停这么久：算真的说完，她开口（原来固定等 1.2 秒才开始交给她）
const SHORT_SPECULATE_MS = 900, SHORT_COMMIT_MS = 1300;  // 才说了一两个字就停下：多半是在想怎么说，多等一会儿
const RESUME_MS = 250;     // 她还没开口时，你连续出声这么久，就算是接着说
const DUCK_MS = 120;       // 她说话时你出声这么久：先把她压低
const BARGE_MS = 600;      // 出声这么久才算打断（“嗯”“对”一声不算）
const HUM_AFTER_MS = 3000, HUM_PAUSE_MS = 300;  // 你说了 3 秒以上、停下 0.3 秒：她“嗯”一声（每轮最多一次）
const MIN_SPEECH_MS = 350; // 比这短的声音（咳嗽、碰桌子）不算
const MAX_TURN_S = 30;     // 一口气最多说这么久
const PREROLL = 8;
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;         // 开口前多留几帧（约 0.35 秒），不吃掉第一个字

// onState(state)：给形象做“在听”的样子；onHum()：她该“嗯”一声了（返回这声“嗯”有多长，秒）
export function createVoiceMode({ host, submit, onExit, onState, onHum }) {
  let el = null, mic = null, state = "off", muted = false, how = "hear", ended = false;
  let frames = [], pre = [], recent = [], loud = 0, quiet = 0, voiced = 0, floor = 0, echo = 0, level = 0, ducked = false;
  let speaking = null, sr = null, srTimer = 0, raf = 0, orb = null, smooth = 0, hummed = false, humUntil = 0, bargeAt = null, levels = [];
  // 正在交给她的这一轮：{ frames, ctrl, gate, committed, r, cut }。gate 放行之前她不出声；撤回时 gate 作废
  let turn = null;
  const newTurn = (fr, committed = false) => {
    const tn = { frames: fr, ctrl: new AbortController(), committed, r: null, cut: false };
    tn.gate = new Promise((ok, no) => { tn.open = ok; tn.drop = no; });
    tn.gate.catch(() => {});
    if (committed) tn.open();
    return tn;
  };

  // ---------- 界面 ----------
  const STATUS = {
    listening: () => t("在听……"),
    hearing: () => t("在听……停一下我就开始回答"),
    thinking: () => t("在想……还没说完可以接着说"),
    speaking: () => (how === "browser" ? t("在说话，点一下光球可以打断") : t("在说话，直接开口就能打断")),
    muted: () => t("麦克风已静音"),
  };
  function build() {
    el = document.createElement("div");
    el.className = "vm";
    el.innerHTML = `
      <div class="vm-stage">
        <button class="vm-orb" type="button" title="${esc(t("点一下：打断，或者表示你说完了"))}"><canvas></canvas></button>
        <div class="vm-status" aria-live="polite"></div>
        <div class="vm-caption"></div>
      </div>
      <div class="vm-bar">
        <button class="vm-btn vm-mute" type="button"></button>
        <button class="vm-btn vm-end" type="button">✕ <span>${esc(t("结束"))}</span></button>
      </div>`;
    host.appendChild(el);
    el.querySelector(".vm-orb").onclick = tapOrb;
    orb = pixelOrb(el.querySelector(".vm-orb canvas"));
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
  function animate(now = performance.now()) {  // 像素光球：在听时跟着你的音量，在想时转圈，说话时往外扩散
    raf = requestAnimationFrame(animate);
    if (!el || !orb) return;
    const lv = state === "hearing" || state === "listening" ? Math.min(1, level * 9) : 0;
    smooth += (lv - smooth) * 0.35;
    orb(el.dataset.state || state, smooth, reduceMotion ? 0 : now / 1000);
  }

  // ---------- 状态 ----------
  function set(s) { const was = state; state = s; if (s !== "speaking") bargeAt = null; render(); if (s !== was) onState?.(s); }
  function setMuted(on) {
    muted = on;
    if (on && state === "hearing") resetTurn();
    if (on && sr) { sr.cancel(); sr = null; }
    if (!on && state === "listening" && how === "browser") browserTurn();
    render();
  }
  function resetTurn() { frames = []; loud = 0; quiet = 0; voiced = 0; turn = null; if (state === "hearing") set("listening"); }

  function tapOrb() {
    if (state === "speaking") return interrupt();
    if (state === "hearing") return finishTurn();
    if (state === "listening" && muted) setMuted(false);
  }
  // 打断她：停下，告诉后端她说到哪了（回复还没收齐就先记下，收齐了再报）
  function interrupt() {
    const tn = turn;
    stopSpeaking(); ducked = false;
    speaking = null; turn = null;
    if (tn) { tn.cut = true; tn.r?.interrupted?.(); }
    set("listening");
    if (how === "browser") browserTurn();
  }
  // 她开始出声了（第一句合成好、放行之后）
  function started(tn) {
    if (ended || turn !== tn || state === "speaking") return;
    set("speaking"); echo = 0; loud = 0; ducked = false;
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
    recent.push(f); levels.push(rms);  // 约 2.6 秒：打断她时，你开口那段也要带上
    if (recent.length > 60) { recent.shift(); levels.shift(); if (bargeAt) bargeAt--; }
    const BARGE_GAP_MS = 1200;  // 停顿不到这么久，前后算同一次插话（“等一下，我想问你……”中间那个逗号）

    if (state === "speaking" && how !== "browser" && !muted) {
      // 她在说话：音箱的声音会漏进麦克风，门槛抬高到漏音的两倍多。你一出声她先压低；持续 0.6 秒以上才算打断，“嗯”一声不算
      const bar = Math.max(on * 2.5, echo * 2.2);
      if (rms < bar) {
        echo = echo ? echo * 0.97 + rms * 0.03 : rms;
        if (loud || bargeAt != null) {
          quiet += ms;
          if (loud && quiet > 250) { loud = 0; if (ducked) { ducked = false; duck(false); } }  // 只是“嗯”一声：恢复音量
          if (quiet > BARGE_GAP_MS) { bargeAt = null; quiet = 0; }
        }
        return;
      }
      if (bargeAt == null) {  // 你开口的那一帧：门槛抬高了，最先过线的常常是第二三个字，往回找到声音真正起来的地方（比漏音大）
        let i = recent.length - 1;
        while (i > 0 && levels[i - 1] > Math.max(on, echo * 1.3)) i--;
        bargeAt = i;
      }
      loud += ms; quiet = 0;
      if (loud >= DUCK_MS && !ducked) { ducked = true; duck(true); }
      if (loud >= BARGE_MS) {
        const fr = recent.slice(Math.max(0, bargeAt - PREROLL));  // 从你开口前一点开始：第一个字不丢
        bargeAt = null;
        interrupt(); frames = fr; voiced = loud; quiet = 0; loud = 0; hummed = false; set("hearing");
      }
      return;
    }
    if (muted || how === "browser") return;
    if (state === "thinking" && turn) {  // 交给她了、她还没开口：你又说话了，就是还没说完
      if (rms > on) { loud += ms; if (loud >= RESUME_MS) resume(); return; }
      loud = 0; quiet += ms;
      if (!turn.committed && quiet >= (turn.short ? SHORT_COMMIT_MS : COMMIT_MS)) { turn.committed = true; turn.open(); }  // 真的说完了：放行，她开口
      return;
    }
    if (state === "listening") {
      if (rms > on) { loud += ms; if (loud >= 130) { frames = [...pre]; voiced = loud; quiet = 0; hummed = false; set("hearing"); } }
      else loud = 0;
      return;
    }
    if (state === "hearing") {
      frames.push(f);
      const humming = performance.now() < humUntil;  // 她在“嗯”：漏进来的这声不算你在说
      if (rms > off && !humming) { voiced += ms; quiet = 0; } else quiet += ms;
      if (!hummed && voiced + (turn?.prevVoiced || 0) >= HUM_AFTER_MS && quiet >= HUM_PAUSE_MS && onHum) {
        hummed = true;
        Promise.resolve(onHum()).then((sec) => { if (sec) humUntil = performance.now() + sec * 1000 + 150; }).catch(() => {});
      }
      const len = frames.length * ms;
      if (quiet >= (voiced < 900 ? SHORT_SPECULATE_MS : SPECULATE_MS) || len >= MAX_TURN_S * 1000) finishTurn();
    }
  }

  async function finishTurn() {
    if (state !== "hearing") return;
    const got = frames; frames = []; loud = 0; quiet = 0;
    const q = quiet;
    if (voiced < MIN_SPEECH_MS && !turn?.prev) { voiced = 0; quiet = 0; return set("listening"); }
    const said = voiced + (turn?.prevVoiced || 0);  // 接着说的：前半句说了多久也算上
    const short = said < 900;
    voiced = 0;
    const all = [...(turn?.prev || []), ...got];  // 接着说的：前半句也带上
    const mine = turn = newTurn(all, got.length * (1000 * 2048 / mic.rate) >= MAX_TURN_S * 1000);  // 说满 30 秒：不再等，直接放行
    mine.short = short; mine.voiced = said;
    quiet = q;  // 接着数静音：数到 0.8 秒放行
    set("thinking");
    const wav = framesToWav(all, mic.rate);
    try {
      if (how === "hear") await reply({ audio: wav, signal: mine.ctrl.signal }, mine);
      else {
        const text = await transcribeWav(wav);
        if (ended || turn !== mine) return;
        if (!text) { turn = null; toast("没听清，再说一次？"); return set("listening"); }
        caption(text, "you");
        await reply({ text, signal: mine.ctrl.signal }, mine);
      }
    } catch (e) { if (!ended && turn === mine) { turn = null; fail(e); set("listening"); } }
  }

  // 她还没开口你又开口了：撤回这一轮（她没出过声），接着听，说完把两段合成一句重新交给她。
  // 回复已经收齐、存进记录了：撤不回，就当她刚要开口被你打断（记录里她这句只剩“……”），这次只发后半段
  function resume() {
    const t0 = turn;
    if (!t0) return;
    t0.drop();
    speaking = null;
    if (t0.r) { t0.cut = true; t0.r.interrupted?.(); turn = null; }
    else { t0.ctrl.abort(); t0.aborted = true; turn = { prev: t0.frames, prevVoiced: t0.voiced || 0 }; }
    frames = [...pre]; voiced = loud; quiet = 0; loud = 0;
    caption("", "");
    set("hearing");
  }

  // 交给她（她第一句合成好、而且放行了才出声），等她念完再接着听
  async function reply(payload, own = newTurn([], true)) {
    if (!turn) turn = own;
    const r = await submit({ ...payload, gate: own.gate, onStart: () => started(own) });
    if (ended) return;
    own.r = r;
    if (turn !== own) {  // 已经撤回（你接着说了）或者被打断了
      if (r?.ok && (own.aborted || own.cut)) r.interrupted?.();  // 撤回晚了一步、记录已经存下：标成没听到
      return;
    }
    if (!r?.ok) { turn = null; own.drop(); return set("listening"); }
    caption(speakable(r.reply || ""), "her");  // 字幕跟她念的一样：不带动作描写和颜文字
    if (!r.speaking) { turn = null; return set("listening"); }
    const mine = (speaking = r.speaking);
    await mine;
    if (ended || speaking !== mine) return;  // 被打断 / 撤回了：那时已经切到“在听”
    speaking = null; turn = null; ducked = false;
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
    ended = false; muted = false; floor = 0; echo = 0; turn = null;
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
    turn?.drop?.(); turn?.ctrl?.abort(); turn = null;
    mic?.close(); mic = null;
    stopSpeaking(); speaking = null;
    const old = el; el = null; state = "off"; onState?.("off");
    old.classList.remove("in");
    setTimeout(() => old.remove(), 250);
    onExit?.();
  }

  return { start, stop, get active() { return !!el; } };
}
