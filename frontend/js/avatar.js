// KRINO WORLD 3D 形象：Three.js + @pixiv/three-vrm。
// 只负责“画出来、动起来”：表情、预设动作、眨眼、视线、口型。做什么动作由后端的互动策略决定，这里不做决策。
// VRM 加载失败或没有模型时，用三维基本体拼一个钴蓝线刻风格的鲸鱼娘半身像，API 完全一样。
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

export const EXPRESSIONS = ["neutral", "calm", "happy", "shy", "sad", "worried", "angry", "surprised", "sleepy", "focused"];
export const ANIMATIONS = ["idle", "wave", "nod", "shake_head", "bow", "think", "cheer", "tilt_head", "spin"];

// 产品表情 → VRM 预设表情的权重（three-vrm 会把 0.x 的 joy/sorrow/fun 等映射到 1.0 的名字）
const EXPR_MAP = {
  neutral: {},
  calm: { relaxed: 0.3 },
  happy: { happy: 0.85 },
  shy: { happy: 0.3, relaxed: 0.45 },
  sad: { sad: 0.8 },
  worried: { sad: 0.45, surprised: 0.15 },
  angry: { angry: 0.75 },
  surprised: { surprised: 0.85 },
  sleepy: { relaxed: 0.5 },
  focused: { angry: 0.12, relaxed: 0.1 },
};
const VRM_EXPR = ["happy", "relaxed", "sad", "angry", "surprised"];
const EXTRA_BLINK = { sleepy: 0.55 };           // 困的时候眼睛半闭
const EXTRA_LOOK_DOWN = { shy: 0.35, sleepy: 0.15 };

const smooth = (x) => x * x * (3 - 2 * x);
// 动作的包络：开头和结尾各 frac 的时间淡入淡出，中间保持
const env = (t, frac = 0.2) => (t < frac ? smooth(t / frac) : t > 1 - frac ? smooth((1 - t) / frac) : 1);
const clamp01 = (x) => Math.max(0, Math.min(1, x));

// 预设动作：t 是 0..1 的进度，返回各骨骼在待机姿势上叠加的欧拉角，以及根节点的偏移
// 约定和 VRM 1.0 归一化骨骼一致：角色面向 +Z，左臂在 +X；upperArm.z 负值放下左臂、正值放下右臂
const CLIPS = {
  wave: { dur: 2.6, f: (t) => { const e = env(t); const w = Math.sin(t * Math.PI * 8) * 0.35;
    return { rightUpperArm: { z: -0.95 * e }, rightLowerArm: { z: (-2.1 + w) * e }, head: { z: 0.08 * e } }; } },
  nod: { dur: 1.4, f: (t) => { const e = env(t, 0.15); const n = Math.sin(t * Math.PI * 4) * 0.22;
    return { head: { x: Math.max(0, n) * e + 0.05 * e }, neck: { x: 0.06 * e } }; } },
  shake_head: { dur: 1.6, f: (t) => { const e = env(t, 0.15);
    return { head: { y: Math.sin(t * Math.PI * 6) * 0.32 * e }, neck: { y: Math.sin(t * Math.PI * 6) * 0.08 * e } }; } },
  bow: { dur: 2.2, f: (t) => { const e = env(t, 0.3);
    return { spine: { x: 0.32 * e }, chest: { x: 0.18 * e }, head: { x: 0.15 * e } }; } },
  think: { dur: 2.8, f: (t) => { const e = env(t, 0.25);
    return { head: { z: 0.16 * e, x: -0.12 * e }, rightUpperArm: { z: -0.35 * e, x: -0.85 * e }, rightLowerArm: { y: 2.0 * e }, look: { x: 0.4 * e, y: 0.5 * e } }; } },
  cheer: { dur: 1.9, f: (t) => { const e = env(t, 0.2); const b = Math.abs(Math.sin(t * Math.PI * 3)) * 0.04 * e;
    return { leftUpperArm: { z: 2.1 * e }, rightUpperArm: { z: -2.1 * e }, leftLowerArm: { z: 0.4 * e }, rightLowerArm: { z: -0.4 * e }, root: { y: b } }; } },
  tilt_head: { dur: 1.8, f: (t) => { const e = env(t, 0.25); return { head: { z: 0.3 * e }, neck: { z: 0.08 * e } }; } },
  spin: { dur: 2.6, f: (t) => ({ root: { ry: Math.sin(t * Math.PI) * 0.9 }, spine: { y: Math.sin(t * Math.PI * 2) * 0.12 } }) },
};

const POSE_BONES = ["hips", "spine", "chest", "neck", "head", "leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm"];

function hasWebGL() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); }
  catch { return false; }
}

function noopAvatar(onStatus) {
  const msg = "此浏览器不支持 WebGL，已切换为平面立绘";
  queueMicrotask(() => onStatus({ state: "error", kind: "procedural", message: msg }));
  const p = () => Promise.resolve({ done: false, reason: "no-webgl" });
  return { supported: false, load: p, play: p, setExpression() {}, setLook() {}, setMouth() {}, speaking() {},
    attachAudio: () => () => {}, info: () => ({ kind: null, supported: false }), dispose() {} };
}

export function createAvatar(container, opts = {}) {
  const onStatus = opts.onStatus || (() => {});
  if (!hasWebGL()) return noopAvatar(onStatus);

  // ---------- 场景 ----------
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: !!opts.preserveDrawingBuffer });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.className = "avatar-canvas";
  renderer.domElement.style.cssText = "display:block;width:100%;height:100%";
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50);
  scene.add(new THREE.HemisphereLight(0xe6e7ef, 0x131319, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(1, 2, 3); scene.add(key);
  const rim = new THREE.DirectionalLight(0x5b6cff, 1.2); rim.position.set(-2, 1.5, -2); scene.add(rim);
  const lookTarget = new THREE.Object3D(); scene.add(lookTarget);

  const S = {
    kind: null, vrm: null, fb: null, root: null, bones: {}, base: {},
    exprTarget: "neutral", exprWeight: 1, cur: Object.fromEntries([...VRM_EXPR, "blinkBase", "lookDown"].map((k) => [k, 0])),
    clip: null, blink: { next: 1.5 + Math.random() * 3, t: -1 },
    look: { x: 0, y: 0 }, saccade: { x: 0, y: 0, next: 1 },
    mouth: { ext: null, extAt: 0, speaking: false, level: 0, phase: 0 }, audio: null,
    headY: 1.4, rootRy: 0, loadToken: 0, running: true, disposed: false, time: 0,
  };
  const color = new THREE.Color(opts.color || "#1414a8");

  // ---------- 取景：半身像 ----------
  // 竖直方向至少看到约 0.85 m（头顶到胸口以下），窄容器再退远一点保证肩膀放得下。
  // 画面比 0.85 m 高时，头顶固定在离上边缘约 12% 的位置，多出来的空间留给下半身，而不是头顶上方。
  function frame() {
    const w = container.clientWidth || 1, h = container.clientHeight || 1;
    camera.aspect = w / h;
    const span = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
    const dist = Math.max(0.85 / span, 0.62 / (span * camera.aspect));
    const viewH = dist * span;                        // 这个距离下能看到的高度（米）
    const top = S.headY + 0.14;                       // 头顶略上方
    const cy = Math.min(S.headY - 0.2, top - viewH * 0.38);
    camera.position.set(0, cy + 0.03, dist);
    camera.lookAt(0, cy, 0);
    camera.updateProjectionMatrix();
    renderer.setSize(w, h, false);
  }
  const ro = new ResizeObserver(frame); ro.observe(container);

  function clear() {
    if (S.root) { scene.remove(S.root); }
    if (S.vrm) VRMUtils.deepDispose(S.vrm.scene);
    if (S.fb) S.fb.group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
    Object.assign(S, { vrm: null, fb: null, root: null, bones: {}, base: {}, kind: null });
  }

  // 待机姿势：手臂放下，稍微向前
  function setBasePose() {
    S.base = { leftUpperArm: { z: -1.2, x: 0.08 }, rightUpperArm: { z: 1.2, x: 0.08 }, leftLowerArm: { z: -0.12 }, rightLowerArm: { z: 0.12 } };
  }

  // ---------- 加载 VRM ----------
  async function load(url) {
    const token = ++S.loadToken;
    if (!url) { useFallback(); onStatus({ state: "ready", kind: "procedural", message: "使用内置形象" }); return { kind: "procedural" }; }
    onStatus({ state: "loading", kind: "vrm", message: "正在加载 3D 形象…" });
    try {
      const loader = new GLTFLoader();
      loader.register((parser) => new VRMLoaderPlugin(parser));
      const gltf = await loader.loadAsync(url, (e) => {
        if (token === S.loadToken && e.total) onStatus({ state: "loading", kind: "vrm", message: `正在加载 3D 形象… ${Math.round(e.loaded / e.total * 100)}%` });
      });
      if (token !== S.loadToken || S.disposed) { if (gltf.userData.vrm) VRMUtils.deepDispose(gltf.scene); return { kind: "stale" }; }
      const vrm = gltf.userData.vrm;
      if (!vrm) throw new Error("文件里没有 VRM 数据");
      VRMUtils.removeUnnecessaryVertices(gltf.scene);
      VRMUtils.combineSkeletons?.(gltf.scene);
      VRMUtils.rotateVRM0(vrm);  // 0.x 模型面朝 -Z，转到和 1.0 一致
      vrm.scene.traverse((o) => { o.frustumCulled = false; });
      clear();
      S.vrm = vrm; S.root = vrm.scene; S.kind = "vrm"; S.rootRy = vrm.scene.rotation.y;
      for (const b of POSE_BONES) S.bones[b] = vrm.humanoid?.getNormalizedBoneNode(b) || null;
      if (vrm.lookAt) vrm.lookAt.target = lookTarget;
      scene.add(vrm.scene);
      vrm.update(0);
      const head = vrm.humanoid?.getNormalizedBoneNode("head");
      S.headY = head ? head.getWorldPosition(new THREE.Vector3()).y + 0.05 : 1.4;
      setBasePose(); frame();
      const meta = vrm.meta || {};
      onStatus({ state: "ready", kind: "vrm", message: "3D 形象已就绪", meta: { name: meta.name || meta.title, authors: meta.authors || (meta.author ? [meta.author] : []) } });
      return { kind: "vrm" };
    } catch (err) {
      if (token !== S.loadToken) return { kind: "stale" };
      console.warn("VRM 加载失败", err);
      useFallback();
      onStatus({ state: "fallback", kind: "procedural", message: "3D 模型加载失败，已使用内置形象：" + (err?.message || err) });
      return { kind: "procedural", error: String(err?.message || err) };
    }
  }

  // ---------- 内置形象：钴蓝线刻风格的鲸鱼娘半身像 ----------
  function useFallback() {
    clear();
    const fb = buildFallback(color);
    S.fb = fb; S.root = fb.group; S.kind = "procedural"; S.rootRy = 0;
    S.bones = fb.bones;
    scene.add(fb.group);
    S.headY = 1.52;  // 和 VRM 一样取头部骨骼 + 0.05
    setBasePose(); frame();
  }

  // ---------- 对外：表情 / 动作 / 视线 / 口型 ----------
  function setExpression(name, weight = 1) {
    if (!EXPR_MAP[name]) name = "neutral";
    S.exprTarget = name; S.exprWeight = clamp01(weight);
  }

  function play(name) {
    if (name === "idle") { if (S.clip) S.clip.resolve({ done: false, interrupted: true }); S.clip = null; return Promise.resolve({ done: true }); }
    const c = CLIPS[name];
    if (!c) return Promise.reject(new Error("未知动作：" + name));
    if (S.clip) S.clip.resolve({ done: false, interrupted: true });
    return new Promise((resolve) => { S.clip = { name, t: 0, dur: c.dur, f: c.f, resolve }; });
  }

  const setLook = (x, y) => { S.look.x = Math.max(-1, Math.min(1, +x || 0)); S.look.y = Math.max(-1, Math.min(1, +y || 0)); };
  const setMouth = (level) => { S.mouth.ext = clamp01(+level || 0); S.mouth.extAt = S.time; };
  const speaking = (on) => { S.mouth.speaking = !!on; };

  // 用音频振幅驱动口型：HTMLAudioElement（TTS 播放）或 MediaStream
  const sourceCache = new WeakMap();
  function attachAudio(src) {
    try {
      const ctx = S.audioCtx || (S.audioCtx = new (window.AudioContext || window.webkitAudioContext)());
      ctx.resume?.();
      const analyser = ctx.createAnalyser(); analyser.fftSize = 1024;
      let node;
      if (src instanceof HTMLMediaElement) {
        node = sourceCache.get(src) || ctx.createMediaElementSource(src);
        sourceCache.set(src, node);
        node.connect(analyser); node.connect(ctx.destination);
      } else {
        node = ctx.createMediaStreamSource(src); node.connect(analyser);
      }
      const buf = new Uint8Array(analyser.fftSize);
      const a = { analyser, buf, node };
      S.audio = a;
      return () => { try { node.disconnect(analyser); } catch { /* 已断开 */ } if (S.audio === a) S.audio = null; };
    } catch (e) {
      console.warn("口型同步不可用", e);
      return () => {};
    }
  }

  // ---------- 每帧 ----------
  const clock = new THREE.Timer();
  const tmp = new THREE.Vector3();

  function mouthLevel(dt) {
    let lvl = 0;
    if (S.audio) {
      S.audio.analyser.getByteTimeDomainData(S.audio.buf);
      let sum = 0; for (const v of S.audio.buf) { const d = (v - 128) / 128; sum += d * d; }
      lvl = clamp01((Math.sqrt(sum / S.audio.buf.length) - 0.015) * 7);
    } else if (S.mouth.ext != null && S.time - S.mouth.extAt < 0.5) {
      lvl = S.mouth.ext;
    } else if (S.mouth.speaking) {
      S.mouth.phase += dt * 11;
      lvl = 0.25 + 0.55 * Math.abs(Math.sin(S.mouth.phase)) * (0.6 + 0.4 * Math.sin(S.mouth.phase * 0.37));
    }
    S.mouth.level += (lvl - S.mouth.level) * Math.min(1, dt * 18);
    return S.mouth.level;
  }

  function blinkValue(dt) {
    const b = S.blink;
    if (b.t < 0) { b.next -= dt; if (b.next <= 0) { b.t = 0; } return 0; }
    b.t += dt;
    const v = b.t < 0.07 ? b.t / 0.07 : b.t < 0.16 ? 1 - (b.t - 0.07) / 0.09 : 0;
    if (b.t >= 0.16) { b.t = -1; b.next = 2 + Math.random() * 4; if (Math.random() < 0.15) b.next = 0.25; }
    return clamp01(v);
  }

  function computePose(dt) {
    const t = S.time;
    const pose = {};
    const add = (bone, rot) => { const p = pose[bone] || (pose[bone] = { x: 0, y: 0, z: 0 }); for (const k in rot) p[k] = (p[k] || 0) + rot[k]; };
    for (const [b, r] of Object.entries(S.base)) add(b, r);
    // 呼吸和轻微摇摆
    add("chest", { x: Math.sin(t * 1.6) * 0.025 });
    add("spine", { z: Math.sin(t * 0.55) * 0.02, y: Math.sin(t * 0.37) * 0.02 });
    add("head", { z: Math.sin(t * 0.7 + 1) * 0.025, x: Math.sin(t * 0.9) * 0.015 });
    add("leftUpperArm", { z: Math.sin(t * 1.6) * 0.015 }); add("rightUpperArm", { z: -Math.sin(t * 1.6) * 0.015 });
    let root = { y: Math.sin(t * 1.6) * 0.003, ry: 0 }, look = { x: 0, y: 0 };
    if (S.clip) {
      const c = S.clip;
      c.t += dt;
      const p = Math.min(1, c.t / c.dur);
      const out = c.f(p);
      for (const [b, r] of Object.entries(out)) {
        if (b === "root") { root.y += r.y || 0; root.ry += r.ry || 0; }
        else if (b === "look") { look = r; }
        else add(b, r);
      }
      if (p >= 1) { S.clip = null; c.resolve({ done: true }); }
    }
    return { pose, root, look };
  }

  function applyPose({ pose, root }) {
    for (const b of POSE_BONES) {
      const node = S.bones[b];
      if (!node) continue;
      const r = pose[b] || { x: 0, y: 0, z: 0 };
      node.rotation.set(r.x || 0, r.y || 0, r.z || 0);
    }
    // rootRy 记住加载时的朝向（VRM 0.x 被 rotateVRM0 转过 180°）
    if (S.root) { S.root.position.y = root.y; S.root.rotation.y = S.rootRy + root.ry; }
  }

  function applyExpression(dt, blink, mouth, lookDownExtra) {
    const target = EXPR_MAP[S.exprTarget] || {};
    const k = 1 - Math.exp(-dt * 8);
    for (const name of VRM_EXPR) S.cur[name] += ((target[name] || 0) * S.exprWeight - S.cur[name]) * k;
    S.cur.blinkBase += ((EXTRA_BLINK[S.exprTarget] || 0) * S.exprWeight - S.cur.blinkBase) * k;
    S.cur.lookDown += (((EXTRA_LOOK_DOWN[S.exprTarget] || 0) + lookDownExtra) - S.cur.lookDown) * k;
    const eyes = Math.max(blink, S.cur.blinkBase);
    // 口型在 aa / oh / ih 之间轮换，听起来不机械
    const ph = S.mouth.phase;
    const vow = { aa: mouth * (0.6 + 0.4 * Math.max(0, Math.sin(ph * 0.5))), oh: mouth * 0.35 * Math.max(0, Math.sin(ph * 0.5 + 2)), ih: mouth * 0.25 * Math.max(0, Math.sin(ph * 0.5 + 4)) };
    if (S.kind === "vrm") {
      const em = S.vrm.expressionManager;
      if (!em) return;
      for (const name of VRM_EXPR) em.setValue(name, S.cur[name]);
      em.setValue("blink", eyes);
      for (const [v, w] of Object.entries(vow)) em.setValue(v, clamp01(w));
    } else if (S.fb) {
      S.fb.express({ ...S.cur, blink: eyes, mouth, vow, time: S.time });
    }
  }

  function updateLook(dt, extra) {
    const s = S.saccade;
    s.next -= dt;
    if (s.next <= 0) { s.x = (Math.random() - 0.5) * 0.12; s.y = (Math.random() - 0.5) * 0.08; s.next = 0.8 + Math.random() * 2.5; }
    // 视线目标放在相机前方，setLook 的 [-1,1] 对应左右 / 上下偏移
    const lx = S.look.x + (extra.x || 0) + s.x, ly = S.look.y + (extra.y || 0) + s.y - S.cur.lookDown;
    camera.getWorldPosition(tmp);
    lookTarget.position.set(tmp.x + lx * 0.6, tmp.y + ly * 0.4, tmp.z);
    if (S.fb) S.fb.lookAt(lx, ly);
  }

  function tick() {
    if (S.disposed) return;
    requestAnimationFrame(tick);
    clock.update();
    // 页面切到后台、或容器看不见（切到别的页面、尺寸为 0）时不渲染，省 CPU / GPU
    if (!S.running || !container.isConnected || container.offsetWidth === 0) return;
    const dt = Math.min(clock.getDelta(), 0.1);
    S.time += dt;
    if (!S.root) { renderer.render(scene, camera); return; }
    const posed = computePose(dt);
    applyPose(posed);
    updateLook(dt, posed.look);
    applyExpression(dt, blinkValue(dt), mouthLevel(dt), 0);
    if (S.vrm) S.vrm.update(dt);
    if (S.fb) S.fb.update(dt, S.time);
    renderer.render(scene, camera);
  }

  const onVis = () => { S.running = !document.hidden; };
  document.addEventListener("visibilitychange", onVis);
  frame();
  tick();

  function dispose() {
    S.disposed = true; S.loadToken++;
    document.removeEventListener("visibilitychange", onVis);
    ro.disconnect();
    if (S.clip) S.clip.resolve({ done: false, interrupted: true });
    clear();
    S.audioCtx?.close?.();
    renderer.dispose();
    renderer.domElement.remove();
  }

  return {
    supported: true, load, play, setExpression, setLook, setMouth, speaking, attachAudio, dispose,
    info: () => ({ kind: S.kind, supported: true, expression: S.exprTarget, animation: S.clip?.name || "idle",
      expressions: EXPRESSIONS, animations: ANIMATIONS }),
  };
}

// ---------- 内置形象 ----------
// 结构和 VRM 归一化骨骼同名（spine/chest/neck/head/左右上臂/前臂），所以预设动作两边共用。
function buildFallback(color) {
  const group = new THREE.Group();
  const silver = new THREE.Color("#b9bac7"), skin = new THREE.Color("#eceaf0"), ink = new THREE.Color("#131319");
  const mats = [];
  const mat = (c, extra = {}) => { const m = new THREE.MeshStandardMaterial({ color: c, roughness: 0.55, metalness: 0.15, ...extra }); mats.push(m); return m; };
  const line = new THREE.MeshBasicMaterial({ color: silver, side: THREE.BackSide });
  // 线刻感：每个部件加一层略大的背面外壳当描边
  const mesh = (geo, m, outline = 1.04) => {
    const g = new THREE.Group();
    g.add(new THREE.Mesh(geo, m));
    if (outline) { const o = new THREE.Mesh(geo, line); o.scale.setScalar(outline); g.add(o); }
    return g;
  };
  const cobalt = mat(color), cobaltDk = mat(color.clone().multiplyScalar(0.6)), skinM = mat(skin, { roughness: 0.8, metalness: 0 });
  const silverM = mat(silver, { metalness: 0.6, roughness: 0.3 });

  const hips = new THREE.Group(); hips.position.y = 0.95; group.add(hips);
  const spine = new THREE.Group(); hips.add(spine);
  const chest = new THREE.Group(); chest.position.y = 0.2; spine.add(chest);
  const torso = mesh(new THREE.CapsuleGeometry(0.105, 0.24, 6, 16), cobalt); torso.scale.set(1.15, 1, 0.75); torso.position.y = 0.06; chest.add(torso);
  const collar = mesh(new THREE.TorusGeometry(0.075, 0.018, 8, 24), silverM, 0); collar.rotation.x = Math.PI / 2; collar.position.y = 0.24; chest.add(collar);
  const neck = new THREE.Group(); neck.position.y = 0.26; chest.add(neck);
  neck.add(mesh(new THREE.CylinderGeometry(0.035, 0.04, 0.08, 12), skinM, 0));
  const head = new THREE.Group(); head.position.y = 0.06; neck.add(head);

  const face = mesh(new THREE.SphereGeometry(0.11, 32, 24), skinM); face.scale.set(1, 1.08, 0.98); face.position.y = 0.1; head.add(face);
  // 头发：后脑的大半球 + 刘海 + 两侧长发
  // SphereGeometry 的 phi 在 (π, 2π) 是后半球（-Z），(0, π) 是前半球；theta 从头顶往下量
  const hairTop = mesh(new THREE.SphereGeometry(0.122, 32, 12, 0, Math.PI * 2, 0, Math.PI * 0.3), cobalt);
  hairTop.position.set(0, 0.115, 0); head.add(hairTop);
  const hairBack = mesh(new THREE.SphereGeometry(0.124, 32, 24, Math.PI, Math.PI, 0, Math.PI * 0.78), cobalt);
  hairBack.position.set(0, 0.112, -0.006); head.add(hairBack);
  const bangs = mesh(new THREE.SphereGeometry(0.121, 24, 12, Math.PI * 0.12, Math.PI * 0.76, Math.PI * 0.08, Math.PI * 0.34), cobaltDk, 0);
  bangs.position.set(0, 0.118, 0.004); head.add(bangs);
  for (const s of [-1, 1]) {
    const lock = mesh(new THREE.CapsuleGeometry(0.035, 0.22, 4, 10), cobalt); lock.position.set(s * 0.1, -0.02, -0.03); lock.rotation.z = s * 0.12; head.add(lock);
    // 鳍耳：压扁的圆锥，银色描边
    const fin = mesh(new THREE.ConeGeometry(0.045, 0.12, 3), cobaltDk, 1.12); fin.scale.set(1, 1, 0.25);
    fin.position.set(s * 0.125, 0.12, -0.01); fin.rotation.set(0, s * 0.3, -s * 1.15); head.add(fin);
  }
  const eyes = [], brows = [], cheeks = [];
  const eyeM = mat(ink, { roughness: 0.2 }), glintM = new THREE.MeshBasicMaterial({ color: 0xffffff }); mats.push(glintM);
  for (const s of [-1, 1]) {
    const eye = new THREE.Group(); eye.position.set(s * 0.04, 0.1, 0.098); head.add(eye);
    const ball = new THREE.Mesh(new THREE.SphereGeometry(0.019, 16, 12), eyeM); ball.scale.set(1, 1.35, 0.5); eye.add(ball);
    const iris = new THREE.Mesh(new THREE.SphereGeometry(0.011, 12, 8), cobalt); iris.position.z = 0.006; iris.scale.set(1, 1.3, 0.4); eye.add(iris);
    const glint = new THREE.Mesh(new THREE.SphereGeometry(0.0045, 8, 6), glintM); glint.position.set(0.006, 0.009, 0.01); eye.add(glint);
    eyes.push({ g: eye, iris });
    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.005, 0.005), cobaltDk); brow.position.set(s * 0.04, 0.142, 0.103); head.add(brow);
    brows.push(brow);
    const cheekM = new THREE.MeshBasicMaterial({ color: 0xc75b84, transparent: true, opacity: 0 }); mats.push(cheekM);
    const cheek = new THREE.Mesh(new THREE.CircleGeometry(0.016, 16), cheekM); cheek.position.set(s * 0.062, 0.075, 0.1); cheek.rotation.y = s * 0.45; head.add(cheek);
    cheeks.push(cheek);
  }
  const mouthM = mat(new THREE.Color("#6b2a3a"), { roughness: 0.6 });
  const mouth = new THREE.Mesh(new THREE.SphereGeometry(0.014, 16, 10), mouthM); mouth.position.set(0, 0.052, 0.104); mouth.scale.set(1, 0.15, 0.4); head.add(mouth);

  // 手臂：肩部为支点，T 姿势时沿 ±X，与 VRM 骨骼约定一致
  const arm = (s) => {
    const upper = new THREE.Group(); upper.position.set(s * 0.13, 0.19, 0); chest.add(upper);
    const u = mesh(new THREE.CapsuleGeometry(0.032, 0.17, 4, 10), cobalt); u.rotation.z = Math.PI / 2; u.position.x = s * 0.1; upper.add(u);
    const lower = new THREE.Group(); lower.position.x = s * 0.2; upper.add(lower);
    const l = mesh(new THREE.CapsuleGeometry(0.026, 0.16, 4, 10), skinM); l.rotation.z = Math.PI / 2; l.position.x = s * 0.1; lower.add(l);
    const cuff = mesh(new THREE.TorusGeometry(0.034, 0.008, 6, 16), silverM, 0); cuff.rotation.y = Math.PI / 2; cuff.position.x = s * 0.02; lower.add(cuff);
    return { upper, lower };
  };
  const L = arm(1), R = arm(-1);
  // 鲸尾：身后的一片尾鳍
  const tail = new THREE.Group(); tail.position.set(0, -0.05, -0.12); hips.add(tail);
  const fluke = mesh(new THREE.ConeGeometry(0.09, 0.22, 3), cobaltDk, 1.08); fluke.scale.set(1.6, 1, 0.2); fluke.rotation.x = -0.6; fluke.position.set(0, 0.08, -0.06); tail.add(fluke);
  // 基座：银色细环，像版画里的底框
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.32, 0.004, 6, 64), silverM); ring.rotation.x = Math.PI / 2; ring.position.y = 0.82; group.add(ring);

  const bones = { hips, spine, chest, neck, head, leftUpperArm: L.upper, rightUpperArm: R.upper, leftLowerArm: L.lower, rightLowerArm: R.lower };

  function express(e) {
    const happy = e.happy || 0, sad = e.sad || 0, angry = e.angry || 0, surprised = e.surprised || 0, relaxed = e.relaxed || 0;
    const open = clamp01(1 - e.blink - happy * 0.55 - relaxed * 0.25 + surprised * 0.3);
    for (const [i, { g }] of eyes.entries()) {
      g.scale.y = 0.08 + open * 0.92 * (1 + surprised * 0.2);
      g.scale.x = 1 + surprised * 0.15;
      brows[i].position.y = 0.142 + surprised * 0.012 - angry * 0.006 + sad * 0.004;
      brows[i].rotation.z = (i === 0 ? 1 : -1) * (angry * 0.45 - sad * 0.4);
      cheeks[i].material.opacity = clamp01(relaxed * 0.9 + happy * 0.3) * 0.55;
    }
    const m = e.mouth || 0;
    mouth.scale.set(1 + happy * 0.6 - (e.vow?.oh || 0) * 0.3, 0.15 + m * 0.9 + surprised * 0.35, 0.4);
    mouth.position.y = 0.052 + happy * 0.002;
  }
  function lookAt(x, y) { for (const { iris } of eyes) { iris.position.x = x * 0.005; iris.position.y = y * 0.004; } }
  function update(dt, t) { tail.rotation.z = Math.sin(t * 1.3) * 0.18; tail.rotation.x = Math.sin(t * 0.9) * 0.05; }

  return { group, bones, express, lookAt, update };
}
