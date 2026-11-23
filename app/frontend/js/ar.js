// AR：把她放进你眼前的真实空间。两种做法，按手机能力自动选：
//   xr      支持 WebXR 的浏览器（安卓 Chrome）：找到桌面 / 地面，点一下放她上去。她站在那个位置上，你拿着手机走动、绕着她转，
//           她都留在原地（有空间锚点时用锚点，没有就用这次 AR 里的固定位置），身体始终转向你。形象是她的 2D 形象（Q 版小人 / 立绘 / Live2D）
//           逐帧画到一张立在空间里的卡片上，脚下一块软阴影。
//   camera  没有 WebXR（iPhone Safari 等）：后置摄像头画面做底，她叠在上面；点一下屏幕把她放在那个方向，
//           转动手机时按陀螺仪反向移动她，看起来像留在原地（没有表面识别，只跟随转向，不跟随走动）。
// 摄像头模式下她也看得见：语音对话里你每说一句，frame() 截一帧眼前的画面（不带她），和录音一起交给她（要在“设置 → 隐私”里允许摄像头）。
// 这是给眼镜做的测试替身：眼镜上同样是说话时带一帧（设备协议 mic.audio 的 image）。画面只用来回答这一句，不保存。
// 说话、表情、动作仍由后端的互动策略决定：这里给出一个 createStage 形象，聊天页把它当成舞台来驱动，语音对话就挂在 AR 界面底部。
import { esc, t } from "./core.js";
import { createStage } from "./stage.js";

const THREE_URL = "/static/vendor/three/three.module.min.js";
const TEX = 512;              // 她那张卡片的贴图大小（正方形，脚底贴着底边）
const DESK_H = 0.32, FLOOR_H = 0.9;  // 放在桌上 / 地上时她多高（米）
const FRAME_W = 512;          // 给她看的那一帧多宽（像素）：够看清桌上的东西，上传也快
// Safari（iPhone 上所有浏览器都是它的内核）播 WebM 不认透明通道，Q 版小人的视频会带一圈黑底
const NO_ALPHA_VIDEO = /iP(hone|ad|od)/.test(navigator.userAgent) || (/Safari\//.test(navigator.userAgent) && !/Chrome|Chromium|Edg\//.test(navigator.userAgent));

let xrOk = null;
// 这台设备能不能进 AR：xr / camera / ""（不能）。结果缓存：按钮点下去时不用再等
export async function arSupport() {
  if (xrOk === null) {
    xrOk = window.isSecureContext && navigator.xr ? await navigator.xr.isSessionSupported("immersive-ar").catch(() => false) : false;
  }
  if (xrOk) return "xr";
  const touch = matchMedia("(pointer: coarse)").matches;
  return touch && navigator.mediaDevices?.getUserMedia ? "camera" : "";
}

// 打开 AR。必须在点击里调用（浏览器要求进 AR、开摄像头都由用户操作触发）。
// 返回 { stage, overlay, say(text), close() }；退出（点 ✕ 或系统返回）时调 onExit
export async function openAR({ character, level, onTap, onPlaced, onExit, mode, seeing = false }) {
  mode ||= await arSupport();
  if (!mode) throw new Error(t("这台设备不支持 AR：请用手机打开（安卓 Chrome 能识别桌面，iPhone 用摄像头模式）"));
  const overlay = buildOverlay(character, mode, seeing && mode === "camera");
  document.body.appendChild(overlay);
  const stage = createStage(overlay.querySelector(".ar-puppet"), { level, stillChibi: NO_ALPHA_VIDEO });
  const ui = {
    hint: (s) => { overlay.querySelector(".ar-hint").textContent = s; overlay.querySelector(".ar-hint").hidden = !s; },
    placed: () => { overlay.classList.add("placed"); onPlaced?.(); },
  };
  let closed = false, impl = null;
  const close = () => {
    if (closed) return;
    closed = true;
    impl?.stop();
    stage.destroy();
    overlay.remove();
    onExit?.();
  };
  overlay.querySelector(".ar-close").onclick = close;
  // 界面上的按钮不当作“在空间里点了一下”（不然点 ✕ 也会把她挪过去）
  overlay.querySelectorAll(".ar-ui").forEach((el) => el.addEventListener("beforexrselect", (e) => e.preventDefault()));
  try {
    impl = mode === "xr" ? await startXR({ overlay, stage, ui, onTap, close }) : await startCamera({ overlay, stage, ui, onTap });
  } catch (e) {
    close();
    throw e;
  }
  const loading = stage.load(character.portrait, { name: character.name, color: character.color })
    .then(() => stage.setExpression(character.default_expression || "calm"));
  overlay.querySelectorAll("[data-size]").forEach((b) => (b.onclick = () => impl.resize(+b.dataset.size)));
  let sayT = 0;
  return {
    stage, overlay, mode, loading,
    say(text) {
      const el = overlay.querySelector(".ar-say");
      el.textContent = text ? (text.length > 90 ? text.slice(0, 88) + "…" : text) : "";
      el.hidden = !text;
      clearTimeout(sayT);
      if (text) sayT = setTimeout(() => (el.hidden = true), Math.min(12000, 3000 + text.length * 110));
    },
    close,
    frame: () => impl?.frame?.() || null,  // 她眼前的一帧（JPEG data URL）；WebXR 下拿不到相机画面，是 null
    get closed() { return closed; },
  };
}

function buildOverlay(c, mode, seeing) {
  const el = document.createElement("div");
  el.className = "ar ar-" + mode;
  el.innerHTML = `
    ${mode === "camera" ? '<video class="ar-cam" muted playsinline autoplay></video>' : ""}
    <div class="ar-puppet" aria-hidden="true"></div>
    <div class="ar-top ar-ui">
      <span class="ar-name">${esc(c.name || "")}</span><span class="ai-badge" title="${esc(t("这是人工智能角色"))}">AI</span>
      <span class="ar-mode">${mode === "xr" ? "AR" : esc(t("摄像头模式"))}</span>
      ${seeing ? `<span class="ar-seeing" title="${esc(t("你说话时，她会看一眼你眼前的画面（不保存）"))}">${esc(t("她看得见"))}</span>` : ""}
      <button class="ar-close" type="button" title="${esc(t("退出 AR"))}">✕</button>
    </div>
    <div class="ar-hint"></div>
    <div class="ar-say" hidden></div>
    <div class="ar-size ar-ui">
      <button type="button" data-size="-1" title="${esc(t("小一点"))}">−</button><button type="button" data-size="1" title="${esc(t("大一点"))}">＋</button>
    </div>
    <div class="ar-voice ar-ui"></div>`;
  return el;
}

// ---------- WebXR：表面识别 + 点击放置 + 空间锚点 ----------
async function startXR({ overlay, stage, ui, onTap, close }) {
  // 先要 AR 会话（离点击最近，浏览器才认这是用户操作），再加载 three.js
  const session = await navigator.xr.requestSession("immersive-ar", {
    requiredFeatures: ["hit-test"], optionalFeatures: ["dom-overlay", "anchors"], domOverlay: { root: overlay },
  });
  try { return await runXR(session, { overlay, stage, ui, onTap, close }); } catch (e) { session.end().catch(() => {}); throw e; }
}

async function runXR(session, { overlay, stage, ui, onTap, close }) {
  const THREE = await import(THREE_URL);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  renderer.xr.enabled = true;
  renderer.xr.setReferenceSpaceType("local");
  // 画面直接画进 AR 会话，画布本身不放进页面（放进覆盖层会挡住相机画面）
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera();

  // 找到表面时脚下的圆环
  const reticle = new THREE.Mesh(new THREE.RingGeometry(0.06, 0.075, 40).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0x3df5ff, transparent: true, opacity: 0.9 }));
  reticle.matrixAutoUpdate = false; reticle.visible = false;
  scene.add(reticle);

  // 她：一张立着的卡片（底边中点在原点），贴图每帧从形象上取
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = TEX;
  const ctx2d = canvas.getContext("2d");
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const card = new THREE.Mesh(new THREE.PlaneGeometry(1, 1).translate(0, 0.5, 0),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, alphaTest: 0.04, side: THREE.DoubleSide }));
  // 脚下的软阴影：让她“站在”桌面上，而不是浮在画面前面
  const sc = document.createElement("canvas"); sc.width = sc.height = 128;
  const g = sc.getContext("2d"), grad = g.createRadialGradient(64, 64, 4, 64, 64, 62);
  grad.addColorStop(0, "rgba(0,0,0,.55)"); grad.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(sc), transparent: true, depthWrite: false }));
  shadow.position.y = 0.002;
  const her = new THREE.Group();
  her.add(shadow, card); her.visible = false;
  scene.add(her);

  const P = { height: DESK_H, anchor: null, matrix: new THREE.Matrix4(), hit: null, placedAt: 0 };
  function setHeight(h) {
    P.height = Math.max(0.12, Math.min(1.8, h));
    card.scale.set(P.height, P.height, 1);
    shadow.scale.set(P.height * 0.55, P.height * 0.55 * 0.6, 1);
  }
  setHeight(DESK_H);

  await renderer.xr.setSession(session);
  const refSpace = renderer.xr.getReferenceSpace();
  const viewer = await session.requestReferenceSpace("viewer");
  const hitSource = await session.requestHitTestSource({ space: viewer });
  ui.hint(t("慢慢移动手机，对准桌面或地面"));

  const pos = new THREE.Vector3(), camPos = new THREE.Vector3(), ray = new THREE.Raycaster();
  async function place(hit) {
    const pose = hit.getPose(refSpace);
    if (!pose) return;
    P.matrix.fromArray(pose.transform.matrix);
    P.anchor?.delete?.(); P.anchor = null;
    // 第一次放：按她离你眼睛多低猜是桌面还是地面，决定多高
    if (!P.placedAt) {
      pos.setFromMatrixPosition(P.matrix);
      camPos.setFromMatrixPosition(renderer.xr.getCamera().matrixWorld);
      setHeight(camPos.y - pos.y > 1.0 ? FLOOR_H : DESK_H);
    }
    P.placedAt = performance.now();
    her.visible = true;
    ui.hint("");
    ui.placed();
    if (hit.createAnchor) {  // 空间锚点：手机重新理解了房间之后，她仍然在原来那个点上
      try { const a = await hit.createAnchor(); if (P.placedAt) P.anchor = a; } catch { /* 不支持就用固定位置 */ }
    }
  }

  session.addEventListener("select", (e) => {
    // 点到她身上 = 摸摸头；点到别处的表面 = 让她走过去
    if (her.visible) {
      const pose = e.frame.getPose(e.inputSource.targetRaySpace, refSpace);
      if (pose) {
        const m = new THREE.Matrix4().fromArray(pose.transform.matrix);
        ray.ray.origin.setFromMatrixPosition(m);
        ray.ray.direction.set(0, 0, -1).transformDirection(m);
        if (ray.intersectObject(card).length) return onTap?.();
      }
    }
    if (P.hit) place(P.hit);
  });
  session.addEventListener("end", () => close());

  renderer.setAnimationLoop((time, frame) => {
    if (!frame) return;
    const hits = frame.getHitTestResults(hitSource);
    P.hit = hits[0] || null;
    const hp = P.hit?.getPose(refSpace);
    reticle.visible = !!hp && (!her.visible || performance.now() - P.placedAt > 1500);  // 放下后圆环先藏一会儿，免得挡着她
    if (hp) reticle.matrix.fromArray(hp.transform.matrix);
    if (her.visible) {
      if (P.anchor) { const ap = frame.getPose(P.anchor.anchorSpace, refSpace); if (ap) P.matrix.fromArray(ap.transform.matrix); }
      her.position.setFromMatrixPosition(P.matrix);
      camPos.setFromMatrixPosition(renderer.xr.getCamera().matrixWorld);
      her.rotation.set(0, Math.atan2(camPos.x - her.position.x, camPos.z - her.position.z), 0);  // 只绕竖轴转向你，不往后仰
      if (stage.snapshot(ctx2d, TEX, TEX)) tex.needsUpdate = true;
    }
    renderer.render(scene, camera);
  });

  return {
    resize: (d) => setHeight(P.height * (d > 0 ? 1.2 : 1 / 1.2)),
    stop() {
      renderer.setAnimationLoop(null);
      hitSource.cancel?.();
      P.anchor?.delete?.();
      session.end().catch(() => {});
      renderer.dispose();
    },
  };
}

// ---------- 摄像头模式：相机画面 + 陀螺仪，没有表面识别 ----------
const HFOV = 52, VFOV = 68;  // 竖拿手机时后置摄像头大约的视角（度）
async function startCamera({ overlay, stage, ui, onTap }) {
  // iPhone 读陀螺仪要先问（也必须在点击里）：先问，再开摄像头。有没有陀螺仪看实际收没收到数据，不看问的结果
  if (typeof DeviceOrientationEvent !== "undefined" && DeviceOrientationEvent.requestPermission) {
    await DeviceOrientationEvent.requestPermission().catch(() => "denied");
  }
  let cam;
  try {
    cam = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
  } catch (e) {
    throw new Error(e.name === "NotAllowedError" ? t("没有摄像头权限：请在浏览器设置里允许摄像头") : t("打不开摄像头：{msg}", { msg: e.message || e }));
  }
  const video = overlay.querySelector(".ar-cam");
  video.srcObject = cam;
  video.play().catch(() => {});
  const puppet = overlay.querySelector(".ar-puppet");
  const P = { now: null, at: null, x: 0.5, y: 0.7, scale: 1 };
  const onOrient = (e) => { if (e.alpha != null) P.now = { a: e.webkitCompassHeading != null ? -e.webkitCompassHeading : e.alpha, b: e.beta || 0 }; };
  addEventListener("deviceorientation", onOrient);
  ui.hint(t("把镜头对准想让她站的地方，点一下屏幕"));

  const wrap = (d) => ((d + 540) % 360) - 180;
  let raf = 0;
  function tick() {
    raf = requestAnimationFrame(tick);
    if (!P.at) return;
    let x = P.x, y = P.y;
    if (P.now && P.at.a != null) {  // 手机往左转，她就往右移：看起来她没动
      x = 0.5 + wrap(P.now.a - P.at.a) / HFOV;
      y += (P.now.b - P.at.b) / VFOV;
    }
    puppet.style.left = (x * 100).toFixed(2) + "%";
    puppet.style.top = (y * 100).toFixed(2) + "%";
    puppet.style.scale = P.scale;
    puppet.hidden = x < -0.4 || x > 1.4;
  }
  tick();
  const onPointer = (e) => {
    if (e.target.closest(".ar-ui")) return;
    if (P.at && e.target.closest(".ar-puppet")) return onTap?.();
    const r = overlay.getBoundingClientRect();
    P.at = { a: P.now?.a ?? null, b: P.now?.b ?? 0 };
    P.x = (e.clientX - r.left) / r.width; P.y = (e.clientY - r.top) / r.height;
    // 点在屏幕左右哪里，就把这个偏移折算成方向，让她站在点的位置
    if (P.at.a != null) P.at.a -= ((e.clientX - r.left) / r.width - 0.5) * HFOV;
    overlay.classList.add("placed-cam");
    ui.hint(P.now ? "" : t("这个浏览器读不到陀螺仪：她会固定在屏幕上"));
    ui.placed();
  };
  overlay.addEventListener("pointerdown", onPointer);
  return {
    resize: (d) => { P.scale = Math.max(0.4, Math.min(2.2, P.scale * (d > 0 ? 1.2 : 1 / 1.2))); },
    frame() {  // 只取摄像头画面，不带她
      if (!video.videoWidth) return null;
      const c = document.createElement("canvas");
      c.width = Math.min(FRAME_W, video.videoWidth); c.height = Math.round(c.width * video.videoHeight / video.videoWidth);
      c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
      return c.toDataURL("image/jpeg", 0.75);
    },
    stop() {
      cancelAnimationFrame(raf);
      removeEventListener("deviceorientation", onOrient);
      overlay.removeEventListener("pointerdown", onPointer);
      cam.getTracks().forEach((x) => x.stop());
    },
  };
}
