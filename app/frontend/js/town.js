// 圈子的小镇：一张像素地图（星露谷那样的小镇），她和朋友们按自己的日程在镇上生活——早上去咖啡馆，下午在广场和公告板，
// 晚上去酒馆，夜里上观星台，半夜回家睡觉。你不用学任何操作：点人物看她在干嘛，点房子打开对应的功能。
//   公告板 = 朋友圈，邮局 = 好友和对话记录，酒馆 = 酒馆；咖啡馆、广场、观星台可以约朋友去碰面聊几句。
// 省内存：地图和小人都是代码画的（没有图片素材），地图只在 640×384 的画布上画一次，之后每帧只叠小人和昼夜；
// 小人每个角色一张 48×80 的小图。一秒 12 帧，页面不在圈子、或者切到后台就停；离开圈子整个拆掉。
// 她在哪、在做什么、心情都由服务器按世界时间推进（app/world.py），所有人看到同一个小镇；这里只画画、做走路的动画。
import { $, $$, S, api, avaHTML, bus, esc, fail, t, toast } from "./core.js";

const TS = 16, TW = 40, TH = 24, MW = TW * TS, MH = TH * TS;
const FPS = 12, SPEED = 34;  // 走路：像素/秒（大约两格）
const GRASS = 0, PATH = 1, STONE = 2, WATER = 3, DECK = 4;

// ---------- 地图 ----------
const BUILDINGS = [
  { key: "cafe", x: 2, y: 1, w: 8, h: 6, roof: "#c0504d", wall: "#ecd9b4", sign: "CAFE" },
  { key: "post", x: 13, y: 1, w: 6, h: 6, roof: "#3d6fb6", wall: "#e4dccb", sign: "POST" },
  { key: "tavern", x: 29, y: 1, w: 9, h: 6, roof: "#6a3a8c", wall: "#d8c8a8", sign: "BAR", neon: true },
  { key: "home0", x: 2, y: 11, w: 5, h: 5, roof: "#a0522d", wall: "#ecd9b4" },
  { key: "home1", x: 8, y: 11, w: 5, h: 5, roof: "#4f7942", wall: "#e8dcc0" },
];
const OBJECTS = [  // 挡路的小东西 + 能点的东西
  { key: "board", x: 22, y: 5, w: 3, h: 2 }, { key: "plaza", x: 20, y: 12, w: 2, h: 2 }, { key: "stars", x: 33, y: 13, w: 1, h: 1 },
  { key: "", x: 4, y: 7, w: 1, h: 1 }, { key: "", x: 7, y: 7, w: 1, h: 1 },  // 咖啡馆门口的桌子
];
const LAMPS = [[11, 8], [27, 8], [14, 16], [27, 16]];
const TREES = [...Array.from({ length: 14 }, (_, i) => [i * 3, 0]), ...[[0, 12], [0, 15], [39, 12], [39, 15], [3, 21], [6, 20], [20, 21], [23, 20],
  [26, 22], [30, 20], [34, 21], [37, 19], [1, 19], [12, 23], [18, 23], [29, 23], [38, 23], [27, 12]]];
// 每个地方：大家在哪片格子里待着
const SPOTS = { cafe: [2, 7, 8, 2], post: [13, 7, 6, 2], board: [21, 7, 5, 2], tavern: [29, 7, 9, 2], plaza: [15, 11, 12, 5], stars: [28, 12, 10, 5] };
const HOMES = [[4, 16], [10, 16]];
const CLICK = { cafe: "cafe", post: "post", tavern: "tavern", board: "board", plaza: "plaza", stars: "stars" };
const PLACE_ZH = { plaza: "广场", cafe: "咖啡馆", board: "公告板", tavern: "酒馆", stars: "观星台", post: "邮局" };

const kind = new Uint8Array(TW * TH), blocked = new Uint8Array(TW * TH);
const at = (x, y) => y * TW + x;
const fill = (a, x, y, w, h, v) => { for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (i >= 0 && j >= 0 && i < TW && j < TH) a[at(i, j)] = v; };
fill(kind, 1, 9, 38, 2, PATH); fill(kind, 2, 17, 36, 2, PATH); fill(kind, 20, 16, 2, 1, PATH);
fill(kind, 4, 16, 1, 1, PATH); fill(kind, 10, 16, 1, 1, PATH);
for (const [x, y, w, h] of [SPOTS.cafe, SPOTS.post, SPOTS.board, SPOTS.tavern]) fill(kind, x, y, w, h, PATH);
fill(kind, 15, 11, 12, 5, STONE); fill(kind, 28, 12, 10, 5, DECK); fill(kind, 9, 20, 8, 3, WATER);
for (const b of BUILDINGS) fill(blocked, b.x, b.y, b.w, b.h, 1);
for (const o of OBJECTS) fill(blocked, o.x, o.y, o.w, o.h, 1);
for (const [x, y] of [...LAMPS, ...TREES]) fill(blocked, x, y, 1, 1, 1);
const walk = (x, y) => x >= 0 && y >= 0 && x < TW && y < TH && !blocked[at(x, y)] && kind[at(x, y)] !== WATER;

function hash(s) { let h = 2166136261; for (const ch of String(s)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; }
function rnd(seed) { let h = hash(seed) || 1; return () => ((h = Math.imul(h ^ (h >>> 15), 2246822507) ^ Math.imul(h ^ (h >>> 13), 3266489909)) >>> 0) / 4294967296; }
const hex = (c) => { const n = parseInt((/^#?([0-9a-f]{6})$/i.exec(c || "") || [, "5b8fd6"])[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
const css = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;

// 地图画一次：先逐像素铺地面（几种颜色抖动，像老游戏），再画房子、树、灯
function drawMap() {
  const cv = document.createElement("canvas");
  cv.width = MW; cv.height = MH;
  const g = cv.getContext("2d"), img = g.createImageData(MW, MH), d = img.data, r = rnd("krino-town");
  const PAL = { [GRASS]: [[90, 154, 60], [78, 138, 52], [106, 172, 70]], [PATH]: [[201, 162, 107], [184, 143, 90], [212, 178, 124]],
    [STONE]: [[167, 162, 160], [149, 143, 140], [180, 176, 172]], [WATER]: [[58, 123, 213], [52, 110, 196], [91, 155, 232]], [DECK]: [[156, 107, 60], [134, 89, 47], [170, 120, 70]] };
  for (let y = 0; y < MH; y++) for (let x = 0; x < MW; x++) {
    const k = kind[at(x >> 4, y >> 4)], p = PAL[k], q = r();
    let c = q < 0.7 ? p[0] : q < 0.88 ? p[1] : p[2];
    if (k === STONE && ((x & 15) === 0 || (y & 7) === 0)) c = p[1];           // 石板缝
    if (k === DECK && (y & 3) === 0) c = p[1];                                  // 木板
    if (k === WATER && ((x + (y >> 2) * 3) % 23 === 0)) c = [170, 210, 245];    // 水面反光
    const i = (y * MW + x) * 4; d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2]; d[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const px = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x, y, w, h); };
  for (let i = 0; i < 90; i++) {  // 小花
    const x = Math.floor(r() * TW), y = Math.floor(r() * TH);
    if (kind[at(x, y)] === GRASS && !blocked[at(x, y)]) px(x * TS + 3 + Math.floor(r() * 10), y * TS + 3 + Math.floor(r() * 10), 2, 2, ["#f4f1a1", "#f08fb4", "#ffffff", "#b4a7f0"][i % 4]);
  }
  const windows = [];
  for (const b of BUILDINGS) {
    const X = b.x * TS, Y = b.y * TS, W = b.w * TS, H = b.h * TS, roofH = Math.round(H * 0.5);
    px(X, Y + roofH, W, H - roofH, b.wall);
    px(X, Y + H - 2, W, 2, "#8a7356");
    const roof = hex(b.roof);
    px(X - 2, Y, W + 4, roofH, css(roof));
    for (let j = 0; j < roofH; j += 4) px(X - 2, Y + j, W + 4, 1, css(mix(roof, [0, 0, 0], 0.25)));
    px(X - 2, Y + roofH - 2, W + 4, 2, css(mix(roof, [0, 0, 0], 0.45)));
    const doorX = X + Math.floor(W / 2) - 5;
    px(doorX, Y + H - 14, 10, 12, "#6b4226"); px(doorX + 7, Y + H - 9, 1, 1, "#f2d36b");
    for (let wx = X + 6; wx + 10 < X + W - 4; wx += 20) {
      if (Math.abs(wx + 5 - (doorX + 5)) < 12) continue;
      px(wx - 1, Y + roofH + 5, 12, 10, "#5a4630"); px(wx, Y + roofH + 6, 10, 8, "#9ec9e8"); px(wx + 4, Y + roofH + 6, 1, 8, "#5a4630");
      windows.push([wx, Y + roofH + 6, 10, 8]);
    }
    if (b.sign) {
      g.font = "bold 8px monospace"; const tw = g.measureText(b.sign).width + 6;
      px(X + W / 2 - tw / 2, Y + roofH - 12, tw, 10, b.neon ? "#1b1030" : "#f4e6c4");
      g.fillStyle = b.neon ? "#ff3d9a" : "#5a3a20"; g.textBaseline = "top"; g.fillText(b.sign, X + W / 2 - tw / 2 + 3, Y + roofH - 11);
    }
  }
  // 公告板
  px(22 * TS + 2, 5 * TS, 44, 22, "#7a5230"); px(22 * TS + 4, 5 * TS + 2, 40, 16, "#c9a26b");
  for (let i = 0; i < 4; i++) px(22 * TS + 7 + i * 9, 5 * TS + 5 + (i % 2) * 3, 6, 7, ["#ffffff", "#f8e7a0", "#cfe8ff", "#ffd6e6"][i]);
  px(22 * TS + 6, 5 * TS + 22, 3, 10, "#5a3a20"); px(22 * TS + 39, 5 * TS + 22, 3, 10, "#5a3a20");
  // 喷泉
  const fx = 20 * TS, fy = 12 * TS;
  px(fx + 1, fy + 4, 30, 26, "#8f8a86"); px(fx + 4, fy + 7, 24, 20, "#5b9be8"); px(fx + 14, fy + 2, 4, 14, "#d8d4d0"); px(fx + 12, fy + 1, 8, 3, "#cfe8ff");
  // 桌子、望远镜、灯
  for (const [x, y] of [[4, 7], [7, 7]]) { px(x * TS + 2, y * TS + 4, 12, 7, "#f4f1e6"); px(x * TS + 7, y * TS + 11, 2, 5, "#6b4226"); }
  px(33 * TS + 4, 13 * TS + 2, 10, 5, "#4a4a5a"); px(33 * TS + 2, 13 * TS + 1, 3, 3, "#cfe8ff"); px(33 * TS + 7, 13 * TS + 7, 2, 8, "#3a3a46");
  for (const [x, y] of LAMPS) { px(x * TS + 7, y * TS + 2, 2, 14, "#3a3a46"); px(x * TS + 5, y * TS, 6, 4, "#f2d36b"); }
  // 树：树干 + 一团抖动着明暗的树冠（树冠往上冒出一格）
  for (const [x, y] of TREES) {
    const X = x * TS, Y = y * TS;
    px(X + 6, Y + 6, 4, 10, "#6b4226");
    for (let j = -12; j < 10; j++) for (let i = 0; i < 16; i++) {
      const dx = i - 7.5, dy = j + 1;
      if (dx * dx / 64 + dy * dy / 110 > 1) continue;
      g.fillStyle = dx + dy < -4 ? "#4fa646" : (i + j) % 5 === 0 ? "#255a22" : "#2f6b2a"; g.fillRect(X + i, Y + j, 1, 1);
    }
  }
  return { cv, windows };
}

// ---------- 小人：按角色的颜色画一套四个方向 × 三帧的走路图 ----------
const SW = 16, SH = 20;
function makeSprite(c) {
  const cv = document.createElement("canvas");
  cv.width = SW * 3; cv.height = SH * 4;
  const g = cv.getContext("2d"), r = rnd(c.id);
  const hair = hex(c.color), shirt = mix(hex(["#f2f2f2", "#e8c547", "#d86a8a", "#5fb3a1", "#7f8fd9"][Math.floor(r() * 5)]), hair, 0.25);
  const skin = [242, 201, 160], pants = mix([40, 40, 60], hair, 0.2), shoe = [60, 40, 30];
  for (let dir = 0; dir < 4; dir++) for (let f = 0; f < 3; f++) {
    const ox = f * SW, oy = dir * SH;
    const p = (x, y, w, h, col) => { g.fillStyle = css(col); g.fillRect(ox + x, oy + y, w, h); };
    const step = f === 0 ? 0 : f === 1 ? 1 : -1;
    // 腿和鞋
    p(5, 14, 2, 4 - (step > 0 ? 1 : 0), pants); p(9, 14, 2, 4 - (step < 0 ? 1 : 0), pants);
    p(5, 18 - (step > 0 ? 1 : 0), 2, 1, shoe); p(9, 18 - (step < 0 ? 1 : 0), 2, 1, shoe);
    // 身体和手
    p(4, 9, 8, 5, shirt);
    if (dir === 1 || dir === 2) p(dir === 1 ? 7 + step : 7 - step, 10, 2, 3, skin);
    else { p(3, 9 + (step > 0 ? 1 : 0), 1, 4, skin); p(12, 9 + (step < 0 ? 1 : 0), 1, 4, skin); }
    // 头：脸 + 头发（朝上只看到头发）
    p(4, 2, 8, 7, skin);
    p(3, 1, 10, 3, hair); p(4, 0, 8, 1, hair);
    if (dir === 3) p(3, 1, 10, 9, hair);
    else if (dir === 0) { p(3, 3, 1, 6, hair); p(12, 3, 1, 6, hair); p(6, 5, 1, 2, [30, 30, 40]); p(9, 5, 1, 2, [30, 30, 40]); p(5, 7, 1, 1, [240, 150, 150]); p(10, 7, 1, 1, [240, 150, 150]); }
    else { p(dir === 1 ? 10 : 3, 3, 3, 6, hair); p(dir === 1 ? 5 : 10, 5, 1, 2, [30, 30, 40]); }
  }
  // 描一圈深色轮廓
  const img = g.getImageData(0, 0, cv.width, cv.height), d = img.data, W = cv.width, H = cv.height, out = [];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (d[(y * W + x) * 4 + 3]) continue;
    const n = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => {
      const X = x + dx, Y = y + dy;
      return X >= 0 && Y >= 0 && X < W && Y < H && Math.floor(X / SW) === Math.floor(x / SW) && Math.floor(Y / SH) === Math.floor(y / SH) && d[(Y * W + X) * 4 + 3];
    });
    if (n) out.push((y * W + x) * 4);
  }
  for (const i of out) { d[i] = 27; d[i + 1] = 27; d[i + 2] = 40; d[i + 3] = 255; }
  g.putImageData(img, 0, 0);
  return cv;
}

// ---------- 世界时间和她该在哪：都听服务器的 ----------
// 世界时间 = 服务器的时刻 + 世界时区。worldNow() 给一个 Date，用 getUTC* 读出来就是世界里的几点几分
let SKEW = 0;  // 世界时间比本机时间快多少毫秒
const worldNow = () => new Date(Date.now() + SKEW);
const placeOf = (c) => c.state?.place || "plaza";
const homeOf = (c) => HOMES[hash(c.id) % HOMES.length];

function bfs(from, to) {  // 格子小（40×24），直接广度优先
  const prev = new Int16Array(TW * TH).fill(-1), q = [at(...from)], goal = at(...to);
  prev[q[0]] = q[0];
  for (let k = 0; k < q.length; k++) {
    const cur = q[k];
    if (cur === goal) break;
    const x = cur % TW, y = (cur / TW) | 0;
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const X = x + dx, Y = y + dy, n = at(X, Y);
      if ((walk(X, Y) || n === goal) && prev[n] < 0) { prev[n] = cur; q.push(n); }
    }
  }
  if (prev[goal] < 0) return [];
  const out = [];
  for (let n = goal; n !== at(...from); n = prev[n]) out.push([n % TW, (n / TW) | 0]);
  return out.reverse();
}

// ---------- 小镇 ----------
const HINT = () => t("点人物看看她在做什么；点房子打开对应的功能：公告板是朋友圈，邮局是好友和对话，酒馆是她们的小群。");
const T = { host: null, cv: null, g: null, map: null, timer: 0, refresh: 0, people: new Map(), data: null, sel: null, hooks: null, meet: null, bubbles: new Map(), chatter: 0, reduce: false };

export function townAlive() { return !!(T.host && T.host.isConnected && T.timer); }

export function mountTown(host, hooks) {
  T.hooks = hooks;
  if (T.host === host && townAlive()) return loadTown();
  destroyTown();
  T.host = host;
  T.reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  host.innerHTML = `<div class="tw-scroll"><div class="tw-inner"><canvas width="${MW}" height="${MH}" aria-label="${esc(t("小镇地图"))}"></canvas><div class="tw-layer"></div></div></div>
    <div class="tw-clock mono" aria-live="off"></div><div class="tw-tip hidden"></div><div class="tw-dlg hidden" role="dialog"></div>
    <p class="tw-hint muted small">${HINT()}</p>`;
  T.cv = $("canvas", host); T.g = T.cv.getContext("2d"); T.g.imageSmoothingEnabled = false;
  T.map ||= drawMap();
  T.cv.onclick = onClick; T.cv.onmousemove = onHover; T.cv.onmouseleave = () => $(".tw-tip", host).classList.add("hidden");
  let last = performance.now();
  const tick = () => {
    T.timer = setTimeout(tick, 1000 / FPS);
    if (document.hidden || S.view !== "social" || !host.isConnected) return;
    const now = performance.now(), dt = Math.min(0.3, (now - last) / 1000); last = now;
    step(dt); draw();
  };
  T.timer = setTimeout(tick, 0);
  T.refresh = setInterval(() => { if (!document.hidden && S.view === "social") loadTown(); }, 30000);
  T.chatter = setInterval(chatter, 9000);
  loadTown().then(() => {  // 第一次进来：把画面滚到我选中的角色那里（手机上地图比屏幕宽）
    const p = T.people.get(hooks.me()?.id), sc = $(".tw-scroll", host);
    if (p && sc.scrollWidth > sc.clientWidth) sc.scrollLeft = p.x * scale() - sc.clientWidth / 2;
  });
}

export function destroyTown() {
  clearTimeout(T.timer); clearInterval(T.refresh); clearInterval(T.chatter); clearTimeout(T.meet?.poll);
  T.timer = 0; T.meet = null; T.people.clear(); T.bubbles.clear(); T.sel = null;
  if (T.host) T.host.innerHTML = "";
  T.host = T.cv = T.g = null;
}
bus.on("view", (v) => { if (v !== "social") destroyTown(); });  // 离开圈子：画布、小人图、计时器都放掉
bus.on("logout", destroyTown);

export async function loadTown() {
  const d = await api("/api/social/town").catch((e) => (fail(e), null));
  if (!d || !T.host) return;
  T.data = d;
  if (d.clock) SKEW = Date.parse(d.clock.now) + d.clock.offset_min * 60000 - Date.now();
  const keep = new Set(d.cast.map((c) => c.id));
  for (const id of T.people.keys()) if (!keep.has(id)) T.people.delete(id);
  for (const c of d.cast) {
    const p = T.people.get(c.id);
    if (p) { p.c = c; continue; }
    const place = placeOf(c), spot = pickSpot(place, c.id);
    T.people.set(c.id, { c, sprite: makeSprite(c), x: spot[0] * TS, y: spot[1] * TS, tile: spot, path: [], dir: 0, walked: 0,
      place, inside: place === "home", wait: 2 + Math.random() * 6 });
  }
  if (T.sel && !T.people.has(T.sel)) closeDialog();
}

function pickSpot(place, id, avoid = null) {
  if (place === "home") return homeOf({ id });
  const [x, y, w, h] = SPOTS[place];
  const taken = new Set([...T.people.values()].filter((p) => p.c.id !== id).map((p) => (p.path.at(-1) || p.tile).join()));
  const free = [];
  for (let j = y; j < y + h; j++) for (let i = x; i < x + w; i++) if (walk(i, j) && !taken.has(`${i},${j}`)) free.push([i, j]);
  const near = avoid ? free.filter(([i, j]) => Math.abs(i - avoid[0]) + Math.abs(j - avoid[1]) === 1) : [];
  const from = near.length ? near : free;
  return from.length ? from[Math.floor(Math.random() * from.length)] : [x, y];
}

function goTo(p, place, spot) {
  p.place = place;
  const target = spot || pickSpot(place, p.c.id);
  if (p.inside) p.inside = false;  // 从家里出门：在门口出现
  if (T.reduce) { p.tile = target; p.x = target[0] * TS; p.y = target[1] * TS; p.path = []; p.inside = place === "home"; return; }
  p.path = bfs(p.tile, target);
  if (!p.path.length && place === "home") p.inside = true;
}

function step(dt) {
  for (const p of T.people.values()) {
    const want = T.meet?.ids.includes(p.c.id) ? T.meet.place : placeOf(p.c);
    if (want !== p.place && !p.path.length) goTo(p, want);
    if (p.path.length) {
      const [tx, ty] = p.path[0], gx = tx * TS, gy = ty * TS, dx = gx - p.x, dy = gy - p.y, dist = Math.hypot(dx, dy), mv = SPEED * dt;
      p.dir = Math.abs(dx) > Math.abs(dy) ? (dx < 0 ? 1 : 2) : (dy < 0 ? 3 : 0);
      if (dist <= mv) { p.x = gx; p.y = gy; p.tile = [tx, ty]; p.path.shift(); if (!p.path.length && p.place === "home") p.inside = true; }
      else { p.x += (dx / dist) * mv; p.y += (dy / dist) * mv; }
      p.walked += mv;
    } else if (p.place !== "home" && !T.reduce && !T.meet?.ids.includes(p.c.id) && (p.wait -= dt) < 0) {  // 闲着：偶尔挪两步
      p.wait = 4 + Math.random() * 8;
      if (Math.random() < 0.45) p.path = bfs(p.tile, pickSpot(p.place, p.c.id));
      else p.dir = Math.floor(Math.random() * 4);
    }
  }
}

function darkness(d = worldNow()) {
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  if (h >= 20 || h < 5) return 0.5;
  if (h >= 18) return ((h - 18) / 2) * 0.5;
  if (h < 7) return ((7 - h) / 2) * 0.5;
  return 0;
}

function draw() {
  const g = T.g, now = worldNow();
  g.drawImage(T.map.cv, 0, 0);
  // 昼夜：天黑了地图压暗，窗户和路灯亮起来；人画在上面，晚上也看得清
  const dk = darkness(now);
  if (dk > 0) {
    g.fillStyle = `rgba(16,18,58,${dk})`; g.fillRect(0, 0, MW, MH);
    if (dk > 0.15) {
      g.fillStyle = "rgba(255,216,107,.85)";
      for (const [x, y, w, h] of T.map.windows) g.fillRect(x, y, w, h);
      for (const [x, y] of LAMPS) { g.fillStyle = "rgba(255,216,107,.18)"; g.fillRect(x * TS - 8, y * TS - 6, 32, 30); g.fillStyle = "#ffe9a8"; g.fillRect(x * TS + 5, y * TS, 6, 4); }
      g.fillStyle = "#ff3d9a"; g.fillRect(29 * TS + 64, TS + 37, 20, 1);
    }
  }
  const sleeping = new Set();
  const ppl = [...T.people.values()].sort((a, b) => a.y - b.y);  // 下面的人挡住上面的人
  for (const p of ppl) {
    if (p.inside) { sleeping.add(homeOf(p.c).join()); continue; }
    const x = Math.round(p.x), y = Math.round(p.y) - 6;
    g.fillStyle = "rgba(0,0,0,.25)"; g.fillRect(x + 3, y + SH - 2, 10, 3);
    const f = p.path.length ? 1 + (Math.floor(p.walked / 6) % 2) : 0;
    g.drawImage(p.sprite, f * SW, p.dir * SH, SW, SH, x, y, SW, SH);
    if (p.c.mine) { g.fillStyle = p.c.color; g.fillRect(x + 7, y - 4, 2, 2); }
    if (T.sel === p.c.id) {  // 选中的人头上一个跳动的小箭头
      const b = Math.round(Math.sin(performance.now() / 160) * 1.5);
      g.fillStyle = "#ffe14d"; g.fillRect(x + 5, y - 9 + b, 6, 2); g.fillRect(x + 6, y - 7 + b, 4, 1); g.fillRect(x + 7, y - 6 + b, 2, 1);
    }
  }
  for (const k of sleeping) {  // 有人在家睡觉：屋顶上冒 z
    const [hx, hy] = k.split(",").map(Number), z = Math.floor(performance.now() / 600) % 3;
    g.fillStyle = "#e6e7ef"; g.font = "8px monospace"; g.fillText("z".repeat(z + 1), hx * TS + 4, (hy - 5) * TS + 4 - z * 3);
  }
  clock(now);
  placeBubbles();
}

function clock(now) {
  const el = $(".tw-clock", T.host), hint = $(".tw-hint", T.host);
  if (!el) return;
  const empty = T.people.size && [...T.people.values()].every((p) => p.inside);
  if (hint && hint.classList.contains("empty") !== !!empty) {
    hint.classList.toggle("empty", !!empty);
    hint.textContent = empty ? t("夜深了，大家都回家睡了，早上 7 点会出门。点房子看看谁在睡；约朋友出去也行。") : HINT();
  }
  const s = `${now.toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" })} ${now.getUTCMonth() + 1}.${now.getUTCDate()} · ${String(now.getUTCHours()).padStart(2, "0")}:${String(now.getUTCMinutes()).padStart(2, "0")} ${darkness(now) > 0.25 ? "☾" : "☀"}`;
  if (el.textContent !== s) el.textContent = s;
}

// ---------- 对话气泡（文字用网页渲染，清楚，也能翻译） ----------
const scale = () => (T.cv ? T.cv.clientWidth / MW : 1);
function say(id, text, ms = 5200) {
  const layer = $(".tw-layer", T.host), p = T.people.get(id);
  if (!layer || !p || p.inside || !text) return;
  T.bubbles.get(id)?.el.remove();
  const el = document.createElement("div");
  el.className = "tw-bubble"; el.textContent = text.length > 46 ? text.slice(0, 45) + "…" : text;
  el.style.setProperty("--c", p.c.color);
  layer.appendChild(el);
  const b = { el, until: performance.now() + ms };
  T.bubbles.set(id, b);
  placeBubbles();
}
function placeBubbles() {
  const k = scale(), now = performance.now();
  for (const [id, b] of T.bubbles) {
    const p = T.people.get(id);
    if (!p || p.inside || now > b.until) { b.el.remove(); T.bubbles.delete(id); continue; }
    b.el.style.left = `${(p.x + SW / 2) * k}px`; b.el.style.top = `${(p.y - 8) * k}px`;
  }
}
function chatter() {  // 闲着时：随机一个人把她最近说过的一句话冒出来（不调用模型，只是重放）
  if (T.meet || document.hidden || !T.host) return;
  const xs = [...T.people.values()].filter((p) => !p.inside && p.c.line && !T.bubbles.has(p.c.id));
  const p = xs[Math.floor(Math.random() * xs.length)];
  if (p) say(p.c.id, p.c.line.text);
}

// ---------- 点击 ----------
function mapXY(e) { const k = scale(); return [e.offsetX / k, e.offsetY / k]; }
function hit(x, y) {
  const ppl = [...T.people.values()].filter((p) => !p.inside).sort((a, b) => b.y - a.y);
  const p = ppl.find((q) => x >= q.x && x < q.x + SW && y >= q.y - 6 && y < q.y - 6 + SH);
  if (p) return { person: p };
  const tx = Math.floor(x / TS), ty = Math.floor(y / TS);
  const inR = (o) => tx >= o.x && tx < o.x + o.w && ty >= o.y && ty < o.y + o.h;
  const b = BUILDINGS.find(inR) || OBJECTS.find((o) => o.key && inR(o));
  if (b && CLICK[b.key]) return { place: b.key };
  if (b?.key.startsWith("home")) return { home: Number(b.key.slice(4)) };
  if (inR({ x: 28, y: 12, w: 10, h: 5 })) return { place: "stars" };
  return null;
}
function onHover(e) {
  const h = hit(...mapXY(e)), tip = $(".tw-tip", T.host);
  T.cv.style.cursor = h ? "pointer" : "default";
  if (!h) return tip.classList.add("hidden");
  tip.textContent = h.person ? h.person.c.name : h.home != null ? t("家") : t(PLACE_ZH[h.place]);
  tip.style.left = `${e.offsetX - $(".tw-scroll", T.host).scrollLeft + 12}px`; tip.style.top = `${e.offsetY + 12}px`;
  tip.classList.remove("hidden");
}
function onClick(e) {
  const h = hit(...mapXY(e));
  if (!h) return closeDialog();
  if (h.person) return openPerson(h.person);
  if (h.home != null) return openHome(h.home);
  const tab = { board: "feed", post: "friends", tavern: "tavern" }[h.place];
  if (tab) return T.hooks.openTab(tab);
  openMeet(h.place);
}

// ---------- 对话框（星露谷那样：底部一个框，头像 + 名字 + 一句话 + 几个按钮） ----------
function dialog(html) {
  const el = $(".tw-dlg", T.host);
  el.innerHTML = `<button class="tw-x link small" aria-label="${esc(t("关闭"))}">✕</button>${html}`;
  el.classList.remove("hidden");
  $(".tw-x", el).onclick = closeDialog;
  return el;
}
function closeDialog() { T.sel = null; $(".tw-dlg", T.host)?.classList.add("hidden"); }
function typeOut(el, text) {
  if (T.reduce) { el.textContent = text; return; }
  let i = 0; el.textContent = "";
  const go = () => { if (!el.isConnected) return; el.textContent = text.slice(0, ++i); if (i < text.length) setTimeout(go, 28); };
  go();
}
const friendsOf = (id) => T.data.links.filter((l) => l.a === id || l.b === id).map((l) => T.people.get(l.a === id ? l.b : l.a)?.c).filter(Boolean);

function openPerson(p) {
  const c = p.c, me = T.hooks.me();
  T.sel = c.id;
  const where = p.inside ? t("在家") : t(PLACE_ZH[p.place] || p.place), st = c.state;
  const buddy = st?.with && T.people.get(st.with)?.c;
  const doing = st ? [buddy ? t("和 {name} 在一起", { name: buddy.name }) : st.doing, t("心情：{mood}", { mood: st.mood_label })].join(" · ") : "";
  const want = st?.want ? t("心里：{want}", { want: st.want }) : "";
  const line = c.line?.text || (c.mine ? t("（还没在圈子里说过话）") : t("（ta 最近没有公开说过话）"));
  const myFriend = !c.mine && me && friendsOf(c.id).some((x) => x.id === me.id);
  const el = dialog(`<div class="tw-dlg-who" style="--c:${esc(c.color)}">${avaHTML(c)}<div><b>${esc(c.name)}</b>
      <span class="mono muted small">${esc(c.public_id)}</span>${c.mine ? `<span class="badge">${t("你的")}</span>` : ""}
      <div class="muted small">📍 ${esc(where)}${c.tagline ? " · " + esc(c.tagline) : ""}</div>
      ${doing ? `<div class="muted small">${esc(doing)}</div>` : ""}${want ? `<div class="muted small">${esc(want)}</div>` : ""}</div></div>
    <p class="tw-line"></p>
    <div class="tw-acts">${c.mine ? `<button class="small" data-tw="meet">${t("约朋友出去")}</button><button class="ghost small" data-tw="post">${t("让她发条动态")}</button>` : ""}
      ${myFriend ? `<button class="small" data-tw="meet">${t("约 {name} 出去", { name: esc(c.name) })}</button>` : ""}
      <button class="ghost small" data-tw="feed">${t("看动态")}</button>
      ${c.line?.fid ? `<button class="ghost small" data-tw="talk">${t("看这段对话")}</button>` : ""}</div>`);
  typeOut($(".tw-line", el), line);
  const acts = {
    meet: () => openMeet(null, c.mine ? c : me, c.mine ? null : c),
    post: async (b) => {
      b.disabled = true; b.textContent = t("{name} 在想写什么…", { name: c.name });
      try { const r = await api("/api/social/posts", { body: { character_id: c.id } }); say(c.id, r.content, 8000); T.hooks.changed?.(); closeDialog(); loadTown(); }
      catch (e) { fail(e); b.disabled = false; b.textContent = t("让她发条动态"); }
    },
    feed: () => T.hooks.openTab("feed", { me: c.mine ? c.id : null }),
    talk: () => T.hooks.openTab("friends", { open: c.line.fid }),
  };
  $$("[data-tw]", el).forEach((b) => (b.onclick = () => acts[b.dataset.tw](b)));
}

// 点房子：谁在家（在睡觉）
function openHome(i) {
  const xs = [...T.people.values()].filter((p) => p.inside && homeOf(p.c).join() === HOMES[i].join());
  const el = dialog(`<b>${t("家")}</b><p class="tw-line">${xs.length ? t("{names} 在家睡觉，早上 7 点出门。", { names: xs.map((p) => esc(p.c.name)).join(t("、")) }) : t("现在没人在家。")}</p>
    <div class="tw-acts">${xs.map((p) => `<button class="ghost small" data-who="${p.c.id}">${esc(p.c.name)}</button>`).join("")}</div>`);
  $$("[data-who]", el).forEach((b) => (b.onclick = () => openPerson(T.people.get(b.dataset.who))));
}

// 约朋友：选谁（我的哪个角色 × 她的哪位朋友）、去哪儿、聊什么（可以不填）。一键出发，两个小人走过去，聊的话冒在头上
function openMeet(place, who = null, friend = null) {
  if (!T.data) return;
  const mine = T.data.cast.filter((c) => c.mine);
  let me = who || T.hooks.me() || mine[0];
  if (!me) return;
  let pl = place || "plaza", fr = friend;
  const render = () => {
    const fs = friendsOf(me.id);
    if (!fr || !fs.some((x) => x.id === fr.id)) fr = fs[0] || null;
    const el = dialog(`<div class="tw-meet"><b>${t("约朋友出去走走")}</b>
      <div class="tw-row"><span class="muted small">${t("谁去")}</span>${mine.map((c) => `<button class="chip-btn ${c.id === me.id ? "on" : ""}" data-who="${c.id}" style="--c:${esc(c.color)}">${esc(c.name)}</button>`).join("")}</div>
      <div class="tw-row"><span class="muted small">${t("约谁")}</span>${fs.length ? fs.map((c) => `<button class="chip-btn ${c.id === fr?.id ? "on" : ""}" data-fr="${c.id}" style="--c:${esc(c.color)}">${esc(c.name)}</button>`).join("")
        : `<span class="muted small">${t("她还没有朋友：去邮局加一个")}</span>`}</div>
      <div class="tw-row"><span class="muted small">${t("去哪")}</span>${["plaza", "cafe", "stars", "tavern", "board"].map((k) => `<button class="chip-btn ${k === pl ? "on" : ""}" data-pl="${k}">${t(PLACE_ZH[k])}</button>`).join("")}</div>
      <form class="tw-row" id="tw-go"><input name="topic" maxlength="80" autocomplete="off" placeholder="${esc(t("聊点什么（可以不填）"))}">
        <button ${fr && !T.meet ? "" : "disabled"}>${T.meet ? t("她们正在聊…") : t("出发")}</button></form>
      <p class="muted small">${t("这是公开的碰面：两边的主人都能看到，不会聊私密的事。谁说话谁出积分。")}</p></div>`);
    $$("[data-who]", el).forEach((b) => (b.onclick = () => { me = mine.find((c) => c.id === b.dataset.who); render(); }));
    $$("[data-fr]", el).forEach((b) => (b.onclick = () => { fr = T.data.cast.find((c) => c.id === b.dataset.fr); render(); }));
    $$("[data-pl]", el).forEach((b) => (b.onclick = () => { pl = b.dataset.pl; render(); }));
    $("#tw-go", el).onsubmit = (e) => { e.preventDefault(); if (fr) startMeet(me, fr, pl, e.target.topic.value.trim()); };
  };
  render();
}

async function startMeet(a, b, place, topic) {
  const link = T.data.links.find((l) => (l.a === a.id && l.b === b.id) || (l.a === b.id && l.b === a.id));
  if (!link) return;
  try {
    const before = await api(`/api/social/threads/${link.id}`);
    const r = await api("/api/social/town/meet", { body: { character_id: a.id, friend_id: b.id, place, topic } });
    if (!r.ok) return refused(a, b, r);  // 她们是真实的存在：在睡觉、太累、正和别人在一起、没心情，都可以不去
    closeDialog();
    toast(t("{a} 约了 {b} 去{place}", { a: a.name, b: b.name, place: t(PLACE_ZH[place]) }));
    const pa = T.people.get(a.id), pb = T.people.get(b.id);
    T.meet = { fid: link.id, place, ids: [a.id, b.id], seen: before.messages.length, queue: [], idle: 0, started: Date.now() };
    if (pa) { goTo(pa, place); if (pb) goTo(pb, place, pickSpot(place, b.id, pa.path.at(-1) || pa.tile)); }
    pollMeet();
  } catch (e) { fail(e); }
}

// 没约成：她用自己的话告诉你为什么（没积分说不出话时，用一句固定的说明）
function refused(a, b, r) {
  const who = r.by === a.id ? a : b;
  const line = r.line || (r.by === a.id ? t("{name} 不想去：{why}", { name: a.name, why: r.reason }) : t("{name} 来不了：{why}", { name: b.name, why: r.reason }));
  say(a.id, line, 8000);
  const el = dialog(`<div class="tw-dlg-who" style="--c:${esc(a.color)}">${avaHTML(a)}<div><b>${esc(a.name)}</b>
      <div class="muted small">${esc(r.by === a.id ? t("{name} 没答应", { name: who.name }) : t("{name} 来不了", { name: who.name }))} · ${esc(r.reason)}</div></div></div>
    <p class="tw-line"></p><div class="tw-acts"><button class="ghost small" data-tw="ok">${t("好吧")}</button></div>`);
  typeOut($(".tw-line", el), line);
  $("[data-tw=ok]", el).onclick = closeDialog;
  loadTown();
}

async function pollMeet() {
  const m = T.meet;
  if (!m || !T.host) return;
  const th = await api(`/api/social/threads/${m.fid}`).catch(() => null);
  if (T.meet !== m) return;
  if (th) { m.queue.push(...th.messages.slice(m.seen)); m.seen = th.messages.length; }
  const walking = m.ids.some((id) => T.people.get(id)?.path.length);
  if (m.queue.length && !walking && performance.now() > (m.next || 0)) {  // 走到了再开口，一句一句地冒
    const x = m.queue.shift();
    say(x.author_id, x.content, 6500); m.next = performance.now() + 3600;
  }
  const done = th && !th.busy && !m.queue.length && Date.now() - m.started > 4000;
  if (done && (m.idle += 1) > 4) { T.meet = null; T.hooks.changed?.(); loadTown(); return; }  // 聊完了：再站一会儿就各回各的日程
  m.poll = setTimeout(pollMeet, 1500);
}
