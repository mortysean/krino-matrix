// 每个角色自己的像素小人：按她的“像素形象”（look，服务器从设定里定下来：app/backend/app/pixel.py）用代码画出来，没有图片素材。
// 一帧 20×28（头顶留 2 像素给呆毛、耳朵、光环），四个方向（下、左、右、上）× 三帧（站、迈左脚、迈右脚）。大头 Q 版：头占一半，好认出是谁。
// look：{hair, hair2, style, skin, eyes, top, top2, bottom, bottom_color, shoes, extras: [...]}，缺的按角色主色补上。
//   style：long 长发 | low_tie 低扎长发 | ponytail 马尾 | twin 双马尾 | bob 短发齐耳 | short 短发
//   bottom：skirt 裙子 | pants 裤子 | dress 连衣裙（上下同色）
//   extras：glasses 眼镜 | fins 头侧的鳍 | tail 鱼尾 | ahoge 呆毛 | ribbon 发带 | clip 发夹 | apron 围裙 | notebook 笔记本
//           cat_ears 猫耳 | fox_ears 狐耳 | horns 角 | halo 光环 | hat 帽子 | scarf 围巾 | wings 翅膀 | headphones 耳机 | antenna 天线
//   tail：有 fins 的是鱼尾，没有的是细长的兽尾
export const SW = 20, SH = 28;
const TOP = 2;  // 整个小人往下挪 2 像素：头顶上的东西不出格

const hex = (c, d = "#5b8fd6") => { const n = parseInt((/^#?([0-9a-f]{6})$/i.exec(c || "") || /^#?([0-9a-f]{6})$/i.exec(d))[1], 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const mix = (a, b, k) => a.map((v, i) => Math.round(v + (b[i] - v) * k));
const dark = (c, k = 0.35) => mix(c, [20, 18, 32], k);
const light = (c, k = 0.35) => mix(c, [255, 255, 255], k);
const OUT = [27, 25, 40];

function fill(look, color) {
  const base = hex(color);
  const l = look || {};
  return {
    hair: hex(l.hair, color), hair2: l.hair2 ? hex(l.hair2) : null, style: l.style || "long",
    skin: hex(l.skin, "#f6d2b4"), eyes: hex(l.eyes, "#3a4a7a"),
    top: hex(l.top, "#" + mix(base, [240, 240, 240], 0.55).map((v) => v.toString(16).padStart(2, "0")).join("")),
    top2: l.top2 ? hex(l.top2) : null,
    bottom: l.bottom || "skirt", bottomC: hex(l.bottom_color, "#" + dark(base, 0.5).map((v) => v.toString(16).padStart(2, "0")).join("")),
    shoes: hex(l.shoes, "#4a3426"),
    extras: new Set(l.extras || []),
  };
}

export function makeSprite(c) {
  const L = fill(c.pixel, c.color);
  const cv = document.createElement("canvas");
  cv.width = SW * 3; cv.height = SH * 4;
  const g = cv.getContext("2d");
  for (let dir = 0; dir < 4; dir++) for (let f = 0; f < 3; f++) drawFrame(g, L, dir, f, f * SW, dir * SH);
  outline(g, cv.width, cv.height);
  return cv;
}

// dir：0 朝下（正面）1 朝左 2 朝右 3 朝上（背面）；f：0 站 1 迈左脚 2 迈右脚
function drawFrame(g, L, dir, f, ox, oy) {
  const px = (x, y, w, h, col) => { if (!col) return; g.fillStyle = `rgb(${col[0]},${col[1]},${col[2]})`; g.fillRect(ox + x, oy + TOP + y, w, h); };
  const front = dir === 0, back = dir === 3, side = dir === 1 || dir === 2, left = dir === 1;
  const mx = (x, w = 1) => (left ? 2 * 10 - x - w : x);  // 侧面：按朝右画，朝左时镜像（以 x=10 为中线）
  const sx = (x, y, w, h, col) => px(side ? mx(x, w) : x, y, w, h, col);
  const step = f === 0 ? 0 : f === 1 ? 1 : -1, bob = f === 0 ? 0 : 1;  // 走路时身体往下沉一像素
  const E = L.extras, hairD = dark(L.hair, 0.3), tip = L.hair2 || L.hair;
  const hairAt = (y) => (y > 14 && L.hair2 ? mix(L.hair, tip, Math.min(1, (y - 14) / 6)) : L.hair);

  // ---- 身后的东西（先画，被身体挡住）----
  if (E.has("wings")) {  // 小翅膀：上宽下窄，扇一扇
    const w = [252, 252, 255], flap = f === 0 ? 0 : 1;
    const wing = (x, dir) => { px(x, 11 + bob - flap, 2, 2, w); px(x + (dir < 0 ? -1 : 1), 10 + bob - flap, 2, 2, w); px(x, 13 + bob - flap, 1, 2, w); };
    if (side) wing(left ? 14 : 4, left ? 1 : -1); else { wing(2, -1); wing(16, 1); }  // 在头发外面一点，别被长发挡住
  }
  if (E.has("tail") && !E.has("fins")) {  // 兽尾：细长，尾巴尖翘起来，走路时左右甩
    const tc = L.hair, sw = f === 1 ? -1 : f === 2 ? 1 : 0;
    if (back) { px(10, 17 + bob, 1, 3, tc); px(10 + sw, 20 + bob, 1, 2, tc); px(11 + sw, 19 + bob, 1, 1, light(tc, 0.3)); }
    else if (side) { sx(5, 17 + bob, 2, 1, tc); sx(3, 15 + bob + sw, 2, 2, tc); sx(3, 14 + bob + sw, 1, 1, light(tc, 0.3)); }
    else px(15, 15 + bob + sw, 1, 3, tc);
  }
  if (E.has("tail") && E.has("fins")) {  // 鱼尾：从腰后面拖出来，尾鳍分叉
    const tc = L.hair2 || L.hair, tl = light(tc, 0.25);
    if (back) { px(8, 17 + bob, 4, 4, tc); px(7, 21, 6, 2, tc); px(5, 22 + (f === 1 ? 1 : 0), 4, 2, tl); px(11, 22 + (f === 2 ? 1 : 0), 4, 2, tl); }
    else if (side) { sx(2, 17 + bob, 5, 3, tc); sx(0, 15 + bob + (f === 1 ? 1 : 0), 3, 3, tl); sx(0, 19 + bob, 3, 3, tl); }
    else { px(3, 19 + bob, 3, 2, tl); px(14, 19 + bob, 3, 2, tl); }
  }
  // 长头发在身后的部分
  const long = ["long", "low_tie", "twin"].includes(L.style);
  if (front && long) for (let y = 7; y < (L.style === "low_tie" ? 18 : 17); y++) { px(4, y + bob, 2, 1, hairAt(y)); px(14, y + bob, 2, 1, hairAt(y)); }

  // ---- 腿和鞋 ----
  const legY = 19 + bob, legH = 4 - bob;
  if (side) {
    sx(9 + step, legY, 2, legH, L.skin); sx(9 + step, 23, 3, 1, L.shoes);
    sx(9 - step, legY, 2, legH, dark(L.skin, 0.15)); sx(9 - step, 23, 3, 1, dark(L.shoes, 0.3));
  } else {
    px(7, legY, 2, legH - (step > 0 ? 1 : 0), L.skin); px(11, legY, 2, legH - (step < 0 ? 1 : 0), L.skin);
    px(7, 23 - (step > 0 ? 1 : 0), 2, 1, L.shoes); px(11, 23 - (step < 0 ? 1 : 0), 2, 1, L.shoes);
  }
  if (L.bottom === "pants") {
    if (side) { sx(9 + step, legY - 1, 2, legH, L.bottomC); sx(9 - step, legY - 1, 2, legH, dark(L.bottomC, 0.2)); }
    else { px(7, legY - 1, 2, legH, L.bottomC); px(11, legY - 1, 2, legH, L.bottomC); }
  }

  // ---- 身体：上衣、裙子 ----
  const bodyY = 12 + bob;
  const skirtC = L.bottom === "dress" ? L.top : L.bottomC;
  if (L.bottom !== "pants") {
    if (side) { sx(7, bodyY + 5, 6, 2, skirtC); sx(6, bodyY + 7, 8, 1, dark(skirtC, 0.15)); }
    else { px(6, bodyY + 5, 8, 2, skirtC); px(5, bodyY + 7, 10, 1, dark(skirtC, 0.15)); }
  } else if (side) sx(8, bodyY + 5, 4, 2, L.bottomC); else px(7, bodyY + 5, 6, 2, L.bottomC);
  if (side) sx(8, bodyY, 5, 5, L.top); else px(6, bodyY, 8, 5, L.top);
  if (L.top2) {  // 里面那件 / 领子：正面中间一条，侧面领口
    if (front) { px(9, bodyY, 2, 5, L.top2); px(8, bodyY, 4, 1, L.top2); }
    else if (side) sx(11, bodyY, 2, 1, L.top2);
    else px(8, bodyY, 4, 1, L.top2);
  }
  if (E.has("apron") && !back) {
    const a = [250, 250, 248];
    if (front) { px(7, bodyY + 2, 6, 3, a); px(7, bodyY + 5, 6, 2, a); px(9, bodyY + 5, 2, 1, light(L.hair, 0.1)); }
    else sx(11, bodyY + 2, 2, 5, a);
  }
  if (E.has("apron") && back) { px(9, bodyY + 3, 2, 1, [250, 250, 248]); px(8, bodyY + 4, 1, 1, [250, 250, 248]); px(11, bodyY + 4, 1, 1, [250, 250, 248]); }
  if (E.has("scarf")) { const sc = light(L.hair, 0.15); if (side) sx(8, bodyY, 5, 1, sc); else px(6, bodyY, 8, 1, sc); }

  // ---- 手 ----
  if (side) { sx(10 - step, bodyY + 1, 2, 3, L.top); sx(10 - step, bodyY + 4, 2, 1, L.skin); }
  else {
    px(5, bodyY + 1 + (step > 0 ? 1 : 0), 1, 3, L.top); px(14, bodyY + 1 + (step < 0 ? 1 : 0), 1, 3, L.top);
    px(5, bodyY + 4 + (step > 0 ? 1 : 0), 1, 1, L.skin); px(14, bodyY + 4 + (step < 0 ? 1 : 0), 1, 1, L.skin);
  }
  if (E.has("notebook")) {
    if (front) px(14, bodyY + 2, 2, 3, [32, 32, 40]);
    else if (side) sx(11 - step, bodyY + 2, 2, 3, [32, 32, 40]);
  }

  // ---- 头 ----
  const hy = 2 + bob;  // 头顶
  if (!back) px(6, hy + 2, 8, 8, L.skin);  // 脸
  // 头发：头顶一片，正面留刘海，背面整片
  px(5, hy, 10, 3, L.hair); px(6, hy - 1, 8, 1, L.hair);
  if (back) {
    px(5, hy + 2, 10, 8, L.hair);
    if (long) for (let y = hy + 10; y < hy + (L.style === "low_tie" ? 16 : 15); y++) px(7, y, 6, 1, hairAt(y - bob));  // 窄一点，露出肩膀
    if (L.style === "low_tie") px(8, hy + 9, 4, 1, E.has("ribbon") ? [24, 24, 30] : hairD);
  } else if (front) {
    px(6, hy + 2, 8, 1, L.hair); px(6, hy + 3, 2, 1, L.hair); px(9, hy + 3, 1, 1, L.hair); px(12, hy + 3, 2, 1, L.hair);  // 刘海
    const sideLen = { short: 4, bob: 6 }[L.style] ?? 8;
    px(5, hy + 2, 1, sideLen, L.hair); px(14, hy + 2, 1, sideLen, L.hair);
  } else {  // 侧面：后脑勺的头发在背后那一侧
    sx(5, hy + 2, 5, 5, L.hair); sx(6, hy + 2, 7, 1, L.hair); sx(13, hy + 2, 1, 2, L.hair);
    const backLen = { short: 6, bob: 7 }[L.style] ?? 9;
    sx(5, hy + 2, 2, backLen, L.hair);
    if (long) for (let y = hy + 9; y < hy + 14; y++) sx(5, y, 3, 1, hairAt(y - bob));
    if (L.style === "low_tie") sx(6, hy + 9, 2, 1, E.has("ribbon") ? [24, 24, 30] : hairD);
  }
  // 马尾、双马尾
  if (L.style === "ponytail") { if (back) px(9, hy + 8, 2, 5, L.hair); else if (side) { sx(3, hy + 2, 2, 7, L.hair); sx(2, hy + 6, 2, 3, tip); } }
  if (L.style === "twin") {
    if (front || back) { px(2, hy + 3, 3, 9, L.hair); px(15, hy + 3, 3, 9, L.hair); px(2, hy + 10, 3, 3, tip); px(15, hy + 10, 3, 3, tip); }
    else sx(3, hy + 3, 3, 9, L.hair);
  }
  // 脸：眼睛、腮红、嘴
  if (front) {
    px(7, hy + 5, 2, 2, L.eyes); px(11, hy + 5, 2, 2, L.eyes);
    px(7, hy + 5, 1, 1, light(L.eyes, 0.7)); px(11, hy + 5, 1, 1, light(L.eyes, 0.7));
    px(6, hy + 7, 1, 1, [242, 160, 160]); px(13, hy + 7, 1, 1, [242, 160, 160]);
    px(9, hy + 8, 2, 1, [190, 110, 100]);
  } else if (side) {
    sx(11, hy + 5, 2, 2, L.eyes); sx(11, hy + 5, 1, 1, light(L.eyes, 0.7)); sx(12, hy + 7, 1, 1, [242, 160, 160]);
  }
  if (E.has("glasses") && !back) {
    const gc = [30, 30, 42];
    if (front) { px(6, hy + 4, 4, 1, gc); px(10, hy + 4, 4, 1, gc); px(6, hy + 5, 1, 2, gc); px(13, hy + 5, 1, 2, gc); px(9, hy + 5, 2, 1, gc); }
    else { sx(10, hy + 4, 4, 1, gc); sx(13, hy + 5, 1, 2, gc); sx(8, hy + 5, 2, 1, gc); }
  }
  // 头上的东西
  if (E.has("ahoge")) { px(10, hy - 3, 1, 2, L.hair); px(11, hy - 4, 1, 1, L.hair); }
  if (E.has("clip") && !back) { const cc = [120, 200, 230]; if (front) { px(12, hy + 1, 2, 1, cc); px(13, hy, 1, 1, light(cc, 0.5)); } else sx(11, hy + 1, 2, 1, cc); }
  if (E.has("ribbon") && L.style !== "low_tie") { const rc = [210, 60, 90]; if (back) { px(8, hy + 1, 4, 2, rc); } else if (front) px(13, hy, 3, 2, rc); else sx(5, hy + 1, 2, 2, rc); }
  if (E.has("fins")) {  // 头两侧的鳍（鲸鱼、人鱼）
    const fc = light(L.hair2 || L.hair, 0.45);
    if (side) { sx(5, hy + 3, 2, 3, fc); sx(4, hy + 2, 1, 2, fc); }
    else { px(3, hy + 3, 2, 3, fc); px(2, hy + 2, 1, 2, fc); px(15, hy + 3, 2, 3, fc); px(17, hy + 2, 1, 2, fc); }
  }
  if (E.has("cat_ears") || E.has("fox_ears")) {
    const ec = L.hair, inner = E.has("fox_ears") ? [250, 240, 230] : [240, 170, 180], tall = E.has("fox_ears") ? 1 : 0;
    if (side) { sx(8, hy - 2 - tall, 2, 2 + tall, ec); sx(11, hy - 2 - tall, 2, 2 + tall, ec); }
    else { px(5, hy - 2 - tall, 3, 2 + tall, ec); px(12, hy - 2 - tall, 3, 2 + tall, ec); if (front) { px(6, hy - 1, 1, 1, inner); px(13, hy - 1, 1, 1, inner); } }
  }
  if (E.has("horns")) { const hc = [236, 226, 200]; if (side) sx(10, hy - 2, 2, 2, hc); else { px(5, hy - 2, 2, 2, hc); px(13, hy - 2, 2, 2, hc); } }
  if (E.has("halo")) { const hc = [255, 226, 110]; px(6, hy - 4, 8, 1, hc); px(5, hy - 3, 1, 1, hc); px(14, hy - 3, 1, 1, hc); }
  if (E.has("hat")) { const hc = dark(L.top, 0.2); px(4, hy - 1, 12, 2, hc); px(6, hy - 3, 8, 2, hc); }
  if (E.has("antenna")) { px(10, hy - 3, 1, 3, [150, 150, 165]); px(9, hy - 4, 3, 1, f === 1 ? [255, 120, 120] : [120, 220, 255]); }
  if (E.has("headphones")) { const hc = [40, 40, 52]; px(5, hy - 1, 10, 1, hc); if (!side) { px(4, hy + 3, 2, 3, hc); px(14, hy + 3, 2, 3, hc); } else sx(8, hy + 3, 2, 3, hc); }
}

function outline(g, W, H) {  // 描一圈深色轮廓，像素小人在草地上才清楚
  const img = g.getImageData(0, 0, W, H), d = img.data, out = [];
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    if (d[(y * W + x) * 4 + 3]) continue;
    const n = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => {
      const X = x + dx, Y = y + dy;
      return X >= 0 && Y >= 0 && X < W && Y < H && Math.floor(X / SW) === Math.floor(x / SW) && Math.floor(Y / SH) === Math.floor(y / SH) && d[(Y * W + X) * 4 + 3];
    });
    if (n) out.push((y * W + x) * 4);
  }
  for (const i of out) { d[i] = OUT[0]; d[i + 1] = OUT[1]; d[i + 2] = OUT[2]; d[i + 3] = 255; }
  g.putImageData(img, 0, 0);
}
