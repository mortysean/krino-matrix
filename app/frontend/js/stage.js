// 2D 角色形象。两种：
//   image  一张立绘（透明 PNG）。呼吸、轻微摇摆、说话时的上下弹动、预设动作用 CSS 变换表现，表情用一个小表情气泡提示；
//          有整套表情图（portrait.expressions，外观工作台生成）时换表情就换图。
//   live2d Live2D 模型（PixiJS + pixi-live2d-display + Cubism Core）。眨眼、视线、物理、口型都由模型自己完成。
// 对外接口统一：load(portrait) / setExpression(name) / play(name) / speaking(bool) / attachAudio(audio) / setLook(x, y)。
// 做什么动作由后端互动策略决定，这里只负责演出来。
import { t } from "./i18n.js";

const EMOJI = { happy: "♪", shy: "///", sad: "…", worried: "?", angry: "!!", surprised: "!", sleepy: "zzz", focused: "…!", calm: "", neutral: "" };
// Live2D 示例模型没有表情文件，用参数近似：[眼睛笑, 嘴型(-1 撇嘴 ~ 1 笑), 脸红, 眉毛高低]
const L2D_EXPR = { neutral: [0, 0, 0, 0], calm: [0.2, 0.3, 0, 0], happy: [1, 1, 0, 0.3], shy: [0.6, 0.4, 1, 0], sad: [0, -0.8, 0, -0.6],
  worried: [0, -0.4, 0, -0.4], angry: [0, -1, 0, -1], surprised: [0, 0, 0, 1], sleepy: [0, 0, 0, -0.3], focused: [0, -0.1, 0, -0.5] };
// 预设动作在 Live2D 上用头和身体角度做（示例模型的动作文件只有待机），在立绘上用 CSS 动画做
const L2D_MOVES = {
  wave: (t) => ({ ParamAngleZ: 8 * Math.sin(t * 12), ParamBodyAngleZ: 4 * Math.sin(t * 12) }),
  nod: (t) => ({ ParamAngleY: -18 * Math.abs(Math.sin(t * 9)) }),
  shake_head: (t) => ({ ParamAngleX: 22 * Math.sin(t * 14) }),
  bow: (t) => ({ ParamAngleY: -25 * Math.sin(Math.min(1, t) * Math.PI), ParamBodyAngleY: -8 * Math.sin(Math.min(1, t) * Math.PI) }),
  think: () => ({ ParamAngleZ: 12, ParamAngleY: 8, ParamEyeBallX: 0.6, ParamEyeBallY: 0.6 }),
  cheer: (t) => ({ ParamBodyAngleY: 6 * Math.abs(Math.sin(t * 10)), ParamAngleY: 10 * Math.abs(Math.sin(t * 10)) }),
  tilt_head: () => ({ ParamAngleZ: 20 }),
  spin: (t) => ({ ParamAngleX: 30 * Math.sin(t * Math.PI), ParamBodyAngleX: 10 * Math.sin(t * Math.PI) }),
};
const MOVE_MS = { wave: 1800, nod: 1100, shake_head: 1200, bow: 1600, think: 2200, cheer: 1500, tilt_head: 1600, spin: 1800 };

let scriptsLoaded = null;
function loadScript(src) {
  return new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = () => bad(new Error("加载失败：" + src)); document.head.appendChild(s); });
}
// Live2D 的库只在用到时加载（大部分角色用立绘，不需要）
async function loadLive2DLibs() {
  scriptsLoaded ||= (async () => {
    await loadScript("/static/vendor/live2d/live2dcubismcore.min.js");
    await loadScript("/static/vendor/pixi/pixi.min.js");
    await loadScript("/static/vendor/live2d/pixi-live2d-display-cubism4.min.js");
  })();
  return scriptsLoaded;
}

export function createStage(host, { onStatus } = {}) {
  host.innerHTML = '<div class="portrait"><img alt=""><span class="emote"></span></div>';
  const box = host.querySelector(".portrait"), img = box.querySelector("img"), emote = box.querySelector(".emote");
  const S = { kind: null, base: "", faces: {}, app: null, model: null, expr: "neutral", move: null, mouth: 0, speaking: false, audio: null, look: [0, 0] };

  function status(state, message = "") { onStatus?.({ state, kind: S.kind, message }); }

  function clearLive2D() {
    if (S.app) { S.app.destroy(true, { children: true, texture: true }); S.app = null; S.model = null; }
    box.querySelector("canvas")?.remove();
  }

  // 没有立绘的角色：用她自己的颜色和名字首字做一块铭牌，不借用别人的形象
  function plate(name, color) {
    box.dataset.plate = "1";
    img.hidden = true;
    let el = box.querySelector(".nameplate");
    if (!el) { el = document.createElement("div"); el.className = "nameplate"; box.prepend(el); }
    el.style.setProperty("--c", color || "#1414a8");
    el.innerHTML = `<span>${[...(name || "?")][0]}</span><em>${name || ""}</em>`;
    S.kind = "image";
    status("ready");
  }

  async function load(portrait, { name, color } = {}) {
    clearLive2D();
    S.base = ""; S.faces = {};
    box.querySelector(".nameplate")?.remove(); delete box.dataset.plate;
    if (!portrait) return plate(name, color);
    const p = { ...portrait };
    if (p.kind === "live2d") {
      try {
        S.kind = "live2d"; status("loading");
        await loadLive2DLibs();
        const app = new PIXI.Application({ backgroundAlpha: 0, resizeTo: box, antialias: true, autoDensity: true, resolution: Math.min(2, devicePixelRatio || 1) });
        box.prepend(app.view);
        img.hidden = true;
        const model = await PIXI.live2d.Live2DModel.from(p.src, { autoInteract: false });
        app.stage.addChild(model);
        S.app = app; S.model = model;
        app.resize();  // 加载期间容器可能从 0×0 变成了正常大小（页面切回来了），补一次
        fitLive2D();
        app.ticker.add(tickLive2D);
        status("ready");
        return;
      } catch (e) {
        clearLive2D();
        status("fallback", t("Live2D 模型加载失败：{msg}", { msg: e.message }));
        return plate(name, color);
      }
    }
    S.kind = "image"; img.hidden = false;
    S.base = p.src; S.faces = p.expressions || {};
    Object.values(S.faces).forEach((src) => { new Image().src = src; });  // 预先加载，换表情时不闪
    const ok = await new Promise((done) => { img.onload = () => done(true); img.onerror = () => done(false); img.src = p.src; });
    if (!ok) { status("fallback", t("立绘加载失败")); return plate(name, color); }
    img.onload = img.onerror = null;
    if (S.faces[S.expr]) img.src = S.faces[S.expr];  // 加载期间已经换过表情：补上
    box.classList.toggle("has-faces", Object.keys(S.faces).length > 0);
    status("ready");
  }

  // Live2D：按容器高度缩放，脚底贴着容器底部，人物占 1.15 倍高（上半身更大）
  function fitLive2D() {
    const m = S.model; if (!m) return;
    const w = box.clientWidth, h = box.clientHeight;
    const iw = m.internalModel.width, ih = m.internalModel.height;  // 模型原始尺寸，不受当前缩放影响
    const scale = Math.min((h * 1.45) / ih, (w * 1.1) / iw);         // 放大到上半身占满画面
    m.scale.set(scale);
    m.x = (w - iw * scale) / 2;
    m.y = h * 0.04;
  }
  // 在隐藏的页面里加载时容器是 0×0；PixiJS 的 resizeTo 只跟着窗口变，所以容器一变就手动让画布跟上
  new ResizeObserver(() => { S.app?.resize?.(); fitLive2D(); }).observe(box);

  function tickLive2D() {
    const core = S.model?.internalModel?.coreModel; if (!core) return;
    const set = (id, v) => { try { core.setParameterValueById(id, v); } catch { /* 模型没有这个参数 */ } };
    const [eye, mouthForm, cheek, brow] = L2D_EXPR[S.expr] || L2D_EXPR.neutral;
    set("ParamEyeLSmile", eye); set("ParamEyeRSmile", eye); set("ParamMouthForm", mouthForm); set("ParamCheek", cheek);
    set("ParamBrowLY", brow); set("ParamBrowRY", brow);
    if (S.speaking && !S.audio) set("ParamMouthOpenY", 0.35 + 0.35 * Math.abs(Math.sin(performance.now() / 90)));
    if (S.move) {
      const t = (performance.now() - S.move.at) / 1000;
      if (t * 1000 > S.move.ms) { S.move.done(); S.move = null; } else Object.entries(L2D_MOVES[S.move.name](t)).forEach(([k, v]) => set(k, v));
    } else {
      set("ParamAngleX", S.look[0] * 18); set("ParamAngleY", S.look[1] * 12); set("ParamEyeBallX", S.look[0]); set("ParamEyeBallY", S.look[1]);
    }
  }

  function setExpression(name) {
    S.expr = name in L2D_EXPR ? name : "neutral";
    box.dataset.expr = S.expr;
    if (S.kind === "image" && S.base && !box.dataset.plate) {
      const src = S.faces[S.expr] || S.base;
      if (img.getAttribute("src") !== src) img.src = src;
    }
    box.classList.toggle("has-faces", Object.keys(S.faces).length > 0);
    const e = Object.keys(S.faces).length ? "" : EMOJI[S.expr] || "";  // 有表情图就不用再冒小气泡
    emote.textContent = e; emote.classList.toggle("on", !!e);
    clearTimeout(setExpression._t);
    if (e) setExpression._t = setTimeout(() => emote.classList.remove("on"), 2600);
  }

  function play(name) {
    if (!(name in MOVE_MS)) return Promise.reject(new Error("没有这个动作：" + name));
    if (S.move) S.move.done();
    return new Promise((done) => {
      S.move = { name, at: performance.now(), ms: MOVE_MS[name], done };
      if (S.kind === "image") {  // 立绘：CSS 动画，结束后清掉
        box.classList.remove(...Object.keys(MOVE_MS).map((m) => "mv-" + m)); void box.offsetWidth;
        box.classList.add("mv-" + name);
        setTimeout(() => { box.classList.remove("mv-" + name); if (S.move?.name === name) { S.move = null; done(); } }, MOVE_MS[name]);
      }
    });
  }

  function speaking(on) { S.speaking = !!on; box.classList.toggle("talking", !!on && S.kind === "image"); }

  function attachAudio(audio) {
    S.audio = audio; speaking(true);
    if (S.kind === "live2d" && S.model?.speak) {
      // pixi-live2d-display-lipsyncpatch 自带按音量驱动口型；它需要音频地址
      S.model.speak(audio.src, { volume: 1, resetExpression: false, onFinish: () => { S.audio = null; speaking(false); }, onError: () => { S.audio = null; speaking(false); } });
      audio.muted = true;  // 由模型播放，避免重复出声
    }
    const end = () => { S.audio = null; speaking(false); };
    audio.addEventListener("ended", end, { once: true }); audio.addEventListener("pause", end, { once: true });
  }

  function setLook(x, y) { S.look = [Math.max(-1, Math.min(1, x)), Math.max(-1, Math.min(1, y))]; }

  return { load, setExpression, play, speaking, attachAudio, setLook, kind: () => S.kind };
}
