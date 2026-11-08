// 角色舞台的像素背景：低分辨率画一张夜景（抖动渐变的天空、星星、城市剪影和亮着的窗、透视地面），放大时保持像素颗粒。
// 颜色跟着角色走（--char），城市轮廓按角色 id 固定：同一个角色每次看到的是同一片街区。只有星星偶尔闪一下，别的都是静止的。

const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5].map((v) => (v + 0.5) / 16);  // 4×4 有序抖动
const PX = 4;  // 一个像素点在屏幕上多大（CSS 像素）

function hex(c) {
  const m = /^#?([0-9a-f]{6})$/i.exec(c || "");
  const n = parseInt(m ? m[1] : "5b8fd6", 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;

function rng(seed) {  // 按字符串播种的伪随机，同一个角色得到同一片城市
  let h = 2166136261;
  for (const ch of String(seed || "krino")) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => { h = Math.imul(h ^ (h >>> 15), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); return ((h ^= h >>> 16) >>> 0) / 4294967296; };
}

export function pixelBackdrop(host) {
  const cv = document.createElement("canvas");
  cv.className = "pixel-bg";
  cv.setAttribute("aria-hidden", "true");
  host.prepend(cv);
  const g = cv.getContext("2d");
  let color = "#5b8fd6", seed = "", stars = [], timer = 0, scene = null;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function draw() {
    const W = Math.max(40, Math.round(host.clientWidth / PX)), H = Math.max(40, Math.round(host.clientHeight / PX));
    if (!host.clientWidth) return;
    cv.width = W; cv.height = H;
    const r = rng(seed), tint = hex(color);
    const ink = [7, 7, 13], deep = mix(ink, tint, 0.16), dusk = mix(ink, tint, 0.42), glow = mix(tint, [255, 255, 255], 0.15);
    const horizon = Math.round(H * 0.7);
    const img = g.createImageData(W, H), d = img.data;
    const put = (x, y, c) => { const i = (y * W + x) * 4; d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = 255; };
    // 天空：从上到下 ink → deep → dusk，用抖动在相邻两色之间过渡（只用几种颜色，像老游戏）
    const bands = [ink, ink, deep, dusk];
    for (let y = 0; y < horizon; y++) {
      const t = (y / horizon) * (bands.length - 1), k = Math.min(bands.length - 2, Math.floor(t)), f = t - k;
      for (let x = 0; x < W; x++) put(x, y, f > BAYER[(y & 3) * 4 + (x & 3)] ? bands[k + 1] : bands[k]);
    }
    // 角色身后的光晕：圆形，抖动着变淡
    const cx = W / 2, cy = H * 0.52, rad = Math.min(W, H) * 0.34;
    for (let y = 0; y < horizon; y++) for (let x = 0; x < W; x++) {
      const q = 1 - Math.hypot((x - cx) / 1.1, y - cy) / rad;
      if (q > 0 && q * 0.6 > BAYER[(y & 3) * 4 + (x & 3)]) {
        const i = (y * W + x) * 4; const c = mix([d[i], d[i + 1], d[i + 2]], glow, 0.14 + q * 0.16);
        d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2];
      }
    }
    // 地面：深色，透视网格线
    const floor = mix(ink, tint, 0.08), line = mix(ink, tint, 0.55);
    for (let y = horizon; y < H; y++) for (let x = 0; x < W; x++) put(x, y, floor);
    for (let k = 1; k < 9; k++) {  // 横线越往近处越稀
      const y = horizon + Math.round(Math.pow(k / 8, 2) * (H - horizon - 1));
      for (let x = 0; x < W; x++) if ((x + k) % 2 || k > 3) put(x, y, line);
    }
    for (let k = -10; k <= 10; k++) {  // 竖线汇聚到地平线中点
      for (let y = horizon; y < H; y++) {
        const x = Math.round(cx + (k * (y - horizon) * 1.6));
        if (x >= 0 && x < W) put(x, y, line);
      }
    }
    // 城市剪影：一排高低不同的楼，楼上零星亮着窗
    const bld = mix(ink, tint, 0.1), win = [mix(tint, [255, 255, 255], 0.5), [255, 61, 154], [242, 255, 61]];
    for (let x = 0; x < W;) {
      const w = 4 + Math.floor(r() * 9), h = Math.floor(H * (0.08 + r() * r() * 0.32)), top = horizon - h;
      for (let y = top; y < horizon; y++) for (let i = x; i < Math.min(W, x + w); i++) put(i, y, bld);
      if (r() < 0.5) for (let y = top - 1 - Math.floor(r() * 4); y < top; y++) put(Math.min(W - 1, x + (w >> 1)), y, bld);  // 天线
      for (let y = top + 2; y < horizon - 1; y += 3) for (let i = x + 1; i < Math.min(W, x + w) - 1; i += 2)
        if (r() < 0.09) put(i, y, r() < 0.82 ? win[0] : win[1 + Math.floor(r() * 2)]);
      x += w + (r() < 0.3 ? 1 : 0);
    }
    g.putImageData(img, 0, 0);
    scene = g.getImageData(0, 0, W, H);
    stars = Array.from({ length: Math.round(W * horizon / 600) }, () => [Math.floor(r() * W), Math.floor(r() * horizon * 0.62), r()]);
    twinkle();
  }

  function twinkle() {  // 星星：大多数常亮，少数在闪
    if (!scene) return;
    g.putImageData(scene, 0, 0);
    const now = performance.now() / 1000;
    for (const [x, y, p] of stars) {
      const on = p < 0.7 || Math.sin(now * (1.5 + p * 3) + p * 40) > 0.2;
      if (!on) continue;
      g.fillStyle = p < 0.12 ? "#3df5ff" : p > 0.92 ? "#ff3d9a" : "#e6e7ef";
      g.fillRect(x, y, 1, 1);
    }
  }

  const ro = new ResizeObserver(() => { clearTimeout(ro.t); ro.t = setTimeout(draw, 80); });
  ro.observe(host);
  if (!reduce) timer = setInterval(() => { if (!document.hidden && host.isConnected) twinkle(); }, 700);

  return {
    set(c, s) { if (c === color && s === seed && scene) return; color = c || color; seed = s || seed; draw(); },
    destroy() { ro.disconnect(); clearInterval(timer); cv.remove(); },
  };
}

// 语音对话的光球：一个像素圆，按状态换颜色和动画。返回 draw(state, level, t)，t 是秒
export function pixelOrb(cv) {
  const N = 48, g = cv.getContext("2d");
  cv.width = cv.height = N;
  const C = N / 2, R = 13;
  const PAL = {
    listening: [[61, 245, 255], [18, 120, 140]], hearing: [[61, 245, 255], [18, 120, 140]],
    thinking: [[242, 255, 61], [110, 116, 30]], speaking: [[255, 61, 154], [120, 24, 72]], muted: [[110, 110, 130], [50, 50, 64]],
  };
  return function draw(state, level, t) {
    const [hi, lo] = PAL[state] || PAL.listening;
    g.clearRect(0, 0, N, N);
    const pulse = state === "speaking" ? 1 + 0.08 * Math.sin(t * 9) + 0.04 * Math.sin(t * 23) : state === "hearing" ? 1 + level * 0.25 : 1;
    const r = R * pulse;
    // 球：左上亮、右下暗，用抖动过渡
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const dx = x + 0.5 - C, dy = y + 0.5 - C, dist = Math.hypot(dx, dy);
      if (dist > r) continue;
      const light = 0.55 - (dx + dy) / (2.6 * r) + (state === "thinking" ? 0.15 * Math.sin(t * 4 + dist) : 0);
      const c = light > BAYER[(y & 3) * 4 + (x & 3)] ? hi : lo;
      g.fillStyle = rgb(c); g.fillRect(x, y, 1, 1);
    }
    g.fillStyle = "#ffffff"; g.fillRect(Math.round(C - r * 0.45), Math.round(C - r * 0.5), 2, 2);  // 高光
    g.fillStyle = rgb(hi);
    if (state === "listening" || state === "hearing") {  // 一圈音量条，跟着你的声音长短
      for (let k = 0; k < 28; k++) {
        const a = (k / 28) * Math.PI * 2, wob = 0.5 + 0.5 * Math.sin(t * 7 + k * 1.7);
        const len = state === "hearing" ? 1 + Math.round(level * 7 * (0.4 + wob * 0.6)) : (wob > 0.85 ? 1 : 0);
        for (let s = 0; s < len; s++) {
          const rr = r + 3 + s; g.fillRect(Math.round(C + Math.cos(a) * rr), Math.round(C + Math.sin(a) * rr), 1, 1);
        }
      }
    } else if (state === "thinking") {  // 几个像素点绕着转
      for (let k = 0; k < 6; k++) {
        const a = t * 3 + (k / 6) * Math.PI * 2, rr = r + 5;
        g.globalAlpha = 0.35 + 0.65 * (k / 5);
        g.fillRect(Math.round(C + Math.cos(a) * rr) - 1, Math.round(C + Math.sin(a) * rr) - 1, 2, 2);
      }
      g.globalAlpha = 1;
    } else if (state === "speaking") {  // 一圈圈往外扩散
      for (let w = 0; w < 2; w++) {
        const ph = ((t * 0.9 + w * 0.5) % 1), rr = r + 2 + ph * 9;
        g.globalAlpha = 1 - ph;
        for (let k = 0; k < 64; k++) { const a = (k / 64) * Math.PI * 2; if (k % 2) g.fillRect(Math.round(C + Math.cos(a) * rr), Math.round(C + Math.sin(a) * rr), 1, 1); }
      }
      g.globalAlpha = 1;
    }
  };
}
