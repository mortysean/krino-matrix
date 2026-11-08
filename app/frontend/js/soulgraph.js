// 工作台右栏：她的“意识星图”——赛博朋克风的脑形粒子星团（只看不改）。
//   左半脑（金色）是灵魂：性格、说话方式、价值观……每个维度一个亮节点，它的每条设定是旁边的小光点。
//   右半脑（紫色）是记忆：你们之间每记下一条，就多一颗星；越重要越大，一天内新记下的会闪，最新的一条有扩散的光波。
//   下面是全息底座和光柱，神经连线会闪、有信号流过。可以拖动旋转，点节点在下面面板看全文。
//   记忆会按遗忘曲线淡忘：越久没提起、越不重要，星就越暗；淡到一定程度就从星图上消失（你再提起会回来）。
// 灵魂是她自己的，改了就不是她了（OOC）；想要不一样的她，就新建一个角色。
import { api, esc, fail, toast, tr } from "./core.js";
import { getLocale } from "./i18n.js";

const DIMS = [  // [字段, 中文, 英文]
  ["personality", "性格", "Personality"], ["speech", "说话方式", "Speech"], ["values", "价值观", "Values"],
  ["interests", "兴趣", "Interests"], ["preferences", "小习惯", "Habits"], ["relationships", "关系", "Relationships"],
  ["worldview", "世界", "World"], ["background", "来历", "Background"], ["boundaries", "底线", "Boundaries"],
];
const MEM_TYPES = {  // 记忆类型 → [中文, 英文, 颜色]
  fact: ["关于你", "About you", [190, 120, 255]], preference: ["偏好", "Likes", [255, 110, 220]],
  event: ["共同经历", "Moments", [120, 200, 255]], commitment: ["约定", "Promises", [120, 255, 210]],
  summary: ["会话回忆", "Recaps", [160, 150, 255]],
};
const GOLD = [255, 190, 90], GOLD_HI = [255, 236, 180], CYAN = [80, 220, 255], VIOLET = [170, 110, 255];

function bullets(text) {  // 一个字段拆成一条条设定
  const s = String(text || "").trim();
  if (!s) return [];
  const lines = s.split(/\n+/).map((x) => x.replace(/^\s*[-*•·]\s*/, "").trim()).filter(Boolean);
  if (lines.length > 1) return lines.slice(0, 8);
  return s.split(/(?<=[。！？.!?])\s*/).map((x) => x.trim()).filter(Boolean).slice(0, 6);
}
const clip = (s, n) => ([...s].length > n ? [...s].slice(0, n).join("") + "…" : s);
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
function rng(seed) { let s = seed >>> 0 || 1; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); }
function hash(str) { let h = 2166136261; for (const ch of String(str)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619); return h >>> 0; }

// 脑形：左右两个略扁的椭球，表面起伏像脑沟；越靠表面越密；中间留一条缝
function brainPoint(r, side, surface = 0.85) {
  for (;;) {
    // 单位球里取方向，大部分点贴着表面（脑皮层），少部分在里面
    const u = r() * 2 - 1, v = r() * 2 - 1, w = r() * 2 - 1;
    const d = Math.hypot(u, v, w);
    if (d > 1 || d < 0.05) continue;
    const rad = r() < surface ? 0.88 + r() * 0.12 : Math.cbrt(r()) * 0.85;
    let x = (u / d) * rad, y = (v / d) * rad, z = (w / d) * rad;
    // 脑回：表面沿着几组波纹起伏
    const g = 0.06 * Math.sin(11 * y + 6 * z) + 0.05 * Math.sin(9 * z - 7 * x) + 0.04 * Math.sin(13 * x + 5 * y);
    x *= 1 + g; y *= 1 + g; z *= 1 + g;
    // 半球：外侧鼓、内侧平，中间留一道缝；前额略高、后脑略低
    x = side * (0.07 + Math.abs(x) * 0.62);
    y = y * 0.74 - 0.08 * z;
    z = z * 1.08;
    return [x, y, z];
  }
}



export function soulGraph(host, c, { onNew } = {}) {
  host._sbStop?.();  // 重画时停掉上一个
  const en = getLocale() === "en";
  const L = (zh, e) => (en ? e : zh);
  const p = c.persona || {};
  const dims = DIMS.map(([k, zh, e]) => ({ key: k, label: en ? e : zh, items: bullets(p[k]) })).filter((d) => d.items.length);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const traitCount = dims.reduce((n, d) => n + d.items.length, 0);

  host.innerHTML = `
    <div class="soul-brain">
      <canvas role="img" aria-label="${esc(L(`${p.name || ""} 的意识星图`, `${p.name || ""}'s mind`))}"></canvas>
      <div class="sb-hud sb-tl">
        <div class="sb-kicker">A LIVING CONSTELLATION</div>
        <div class="sb-title">${esc(L("每一段记忆，都有自己的光。", "Every memory has its own light."))}</div>
        <div class="sb-sub">${esc(L("左边是她的灵魂，右边是你们之间的记忆。", "Her soul on the left, your memories together on the right."))}</div>
        <div class="sb-stats"><div><b>${traitCount}</b><span>${L("灵魂设定", "Soul traits")}</span></div>
          <div><b class="mem" data-sb-memn>…</b><span>${L("共同记忆", "Memories")}</span></div>
          <div><b data-sb-days>…</b><span>${L("认识天数", "Days")}</span></div></div>
      </div>
      <div class="sb-legend"><span style="--c:${rgba(GOLD, 1)}">${L("灵魂", "Soul")}</span><span style="--c:${rgba(VIOLET, 1)}">${L("记忆", "Memory")}</span></div>
      <div class="sb-hud sb-bl" data-sb-bars></div>
      <div class="sb-hud sb-br" data-sb-clock></div>
      <div class="sb-tip"></div>
      <div class="sb-ctrl"><button data-sb-ctl="spin" class="${reduce ? "" : "on"}">${L("自动旋转", "Rotate")}</button><button data-sb-ctl="reset">${L("重置视角", "Reset view")}</button></div>
    </div>
    <div class="sb-panel">
      <div class="sb-tabs"><button data-sb-tab="soul" class="on">${L("灵魂", "Soul")}</button><button data-sb-tab="mem">${L("记忆", "Memories")}</button></div>
      <div class="sb-body" data-sb-body></div>
      ${p.greeting ? `<blockquote class="sb-greet">“${esc(p.greeting)}”</blockquote>` : ""}
      <div class="sb-lock"><span>${esc(L("灵魂是她自己的，不能直接改——改了就不是她了。想要一个不一样的她？",
        "Her soul is her own and can't be edited — she wouldn't be her anymore. Want someone different?"))}</span>
        <button class="ghost small" data-sg-new>${L("＋ 设计新角色", "+ Design a new character")}</button></div>
    </div>`;

  const canvas = host.querySelector("canvas"), ctx = canvas.getContext("2d");
  const tip = host.querySelector(".sb-tip"), body = host.querySelector("[data-sb-body]");
  host.querySelector("[data-sg-new]").onclick = () => onNew?.();
  const CENTER = { x: 0, y: 0.02, z: 0 };

  // ---------- 点云 ----------
  const r = rng(hash(c.id));
  const dust = [];
  const N = innerWidth < 700 ? 2600 : 4600;
  for (let i = 0; i < N; i++) {
    const side = i % 2 ? 1 : -1;
    const [x, y, z] = brainPoint(r, side);
    dust.push({ x, y, z, side, tw: r() * Math.PI * 2, s: 0.5 + r() * 0.9 });
  }
  // 灵魂：维度节点放在左半脑外侧一圈，设定点散在它旁边
  const nodes = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  dims.forEach((d, i) => {
    // 在左半脑外表面上均匀铺开（斐波那契点），避开中缝
    const t = (i + 0.5) / dims.length, yy = 0.85 - 1.7 * t, ang = i * golden * 2.3;
    const ring = Math.sqrt(1 - yy * yy);
    const hx = -(0.25 + 0.4 * Math.abs(Math.cos(ang)) * ring), hy = yy * 0.62, hz = Math.sin(ang) * ring * 0.95;
    nodes.push({ kind: "dim", key: d.key, label: d.label, items: d.items, x: hx, y: hy, z: hz, col: GOLD_HI, size: 4.4 });
    d.items.forEach((txt, j) => {
      const b = (j / d.items.length) * Math.PI * 2 + i, rr = 0.1 + (j % 3) * 0.03;
      nodes.push({ kind: "trait", parent: d.key, label: d.label, text: txt, col: GOLD, size: 2.2,
        x: Math.min(-0.1, hx + rr * Math.cos(b) * 0.6), y: hy + rr * Math.sin(b), z: hz + rr * Math.cos(b) });
    });
  });
  const mems = [];
  let links = [];
  function buildLinks() {
    links = [];
    for (const n of [...nodes, ...mems]) {
      const side = n.x < 0 ? -1 : 1;
      dust.filter((d) => d.side === side).map((d) => [d, (d.x - n.x) ** 2 + (d.y - n.y) ** 2 + (d.z - n.z) ** 2])
        .sort((a, b) => a[1] - b[1]).slice(0, 3).forEach(([d]) => links.push({ a: n, b: d, ph: r() * 6.28, sp: 0.6 + r() * 1.6 }));
    }
    nodes.forEach((n) => {
      if (n.kind === "trait") links.push({ a: n, b: nodes.find((x) => x.key === n.parent), ph: r() * 6.28, sp: 1 + r(), strong: true });
      else links.push({ a: n, b: CENTER, ph: r() * 6.28, sp: 1.2, strong: true });
    });
    mems.forEach((m) => links.push({ a: m, b: CENTER, ph: r() * 6.28, sp: 0.9 + r(), strong: true }));
  }
  buildLinks();

  // ---------- 记忆和关系（数据回来后，记忆一颗颗亮起来） ----------
  let memList = [];
  Promise.all([api(`/api/memories?character_id=${c.id}`).catch(() => []), api(`/api/relations/${c.id}/bond`).catch(() => null)]).then(([ms, bond]) => {
    if (!host.isConnected) return;
    memList = (ms || []).filter((m) => m.status === "active" && m.type !== "summary");
    const rm = rng(hash(c.id + "m"));
    const newest = memList.reduce((t, m) => Math.max(t, Date.parse(m.created_at)), 0);
    const t0 = performance.now();
    memList.forEach((m, i) => {
      const [x, y, z] = brainPoint(rm, 1);
      const ty = MEM_TYPES[m.type] || MEM_TYPES.fact;
      mems.push({ kind: "mem", id: m.id, x: x * 0.92, y: y * 0.92, z: z * 0.92, col: ty[2],
        size: 1.6 + (m.importance || 3) * 0.55 + (m.pinned ? 1 : 0), text: m.content, label: ty[en ? 1 : 0],
        fade: 0.3 + 0.7 * (m.strength ?? 1),  // 记忆强度：快淡忘的星暗一些
        hot: Date.now() - Date.parse(m.created_at) < 24 * 3600e3, newest: Date.parse(m.created_at) === newest,
        born: t0 + Math.min(1800, i * 60) });
    });
    buildLinks();
    host.querySelector("[data-sb-memn]").textContent = memList.length;
    host.querySelector("[data-sb-days]").textContent = bond?.days ?? 0;
    const counts = {};
    memList.forEach((m) => (counts[m.type] = (counts[m.type] || 0) + 1));
    const max = Math.max(1, ...Object.values(counts));
    host.querySelector("[data-sb-bars]").innerHTML = `<div class="sb-kicker" style="margin-bottom:6px">${L("记忆类型", "MEMORY TYPES")}</div>` +
      Object.entries(MEM_TYPES).filter(([k]) => k !== "summary").map(([k, [zh, e, col]]) =>
        `<div class="sb-bar" style="--c:${rgba(col, 1)};--w:${((counts[k] || 0) / max) * 100}%"><span>${en ? e : zh}</span><i></i><em>${counts[k] || 0}</em></div>`).join("") +
      (bond ? `<div class="sb-kicker" style="margin:8px 0 4px">${L("关系", "BOND")}</div><div class="sb-bar" style="--c:#5fd4ff;--w:${Math.min(100, bond.closeness)}%"><span>${esc(tr(bond.stage))}</span><i></i><em>${Math.round(bond.closeness)}</em></div>` : "");
    if (tab === "mem") showTab("mem");
    kick();
  });

  // ---------- 下面的面板：灵魂 / 记忆 ----------
  let tab = "soul", focus = null;
  function showTab(name, highlight) {
    tab = name;
    host.querySelectorAll("[data-sb-tab]").forEach((x) => x.classList.toggle("on", x.dataset.sbTab === name));
    if (name === "soul") {
      body.innerHTML = dims.length ? dims.map((d) => `<div class="sb-sec">${esc(d.label)}</div>
        <ul class="sb-list">${d.items.map((x, i) => `<li class="${highlight === d.key ? "hot" : ""}"><em>${String(i + 1).padStart(2, "0")}</em><span>${esc(x)}</span></li>`).join("")}</ul>`).join("")
        : `<p class="sb-empty">${L("她的灵魂还是空白的。", "Her soul is still blank.")}</p>`;
    } else {
      body.innerHTML = memList.length ? `<ul class="sb-list">${memList.map((m, i) => {
        const ty = MEM_TYPES[m.type] || MEM_TYPES.fact;
        return `<li class="${highlight === m.id ? "hot" : ""}"><em>${String(i + 1).padStart(2, "0")}</em><span><span class="dot" style="--c:${rgba(ty[2], 1)}"></span>${esc(m.content)}
          <small>${esc(ty[en ? 1 : 0])} · ${esc(new Date(m.created_at).toLocaleDateString(en ? "en-US" : "zh-CN"))}${m.strength != null && m.strength < 0.5 && !m.pinned ? ` · ${L("在慢慢淡忘", "fading")}` : ""}</small></span>
          <button class="sb-wrong" data-sb-forget="${esc(m.id)}" title="${L("这条记错了（比如录到了别人的声音），她不会再记得；可以在聊天页“她记得的”里恢复",
            "This is wrong (e.g. someone else's voice got picked up). She'll stop remembering it; you can restore it from \"What she remembers\" in chat.")}">${L("记错了", "Wrong")}</button></li>`;
      }).join("")}</ul>` : `<p class="sb-empty">${L("还没有共同的记忆。多聊几句，她记下的每件事都会在右半脑亮起一颗星。",
        "No memories yet. Chat a little — everything she remembers lights up as a star on the right.")}</p>`;
    }
    if (highlight) body.querySelector("li.hot")?.scrollIntoView({ block: "nearest" });
  }
  host.querySelectorAll("[data-sb-tab]").forEach((x) => (x.onclick = () => { focus = null; showTab(x.dataset.sbTab); kick(); }));
  // 记错了（录进了别人的声音、听错了字）：一键让她不再记得。灵魂不能改，记忆是关于你的，你说了算
  body.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-sb-forget]");
    if (!b) return;
    b.disabled = true;
    try {
      await api(`/api/memories/${b.dataset.sbForget}/forget`, { method: "POST" });
    } catch (err) { b.disabled = false; return fail(err); }
    const id = b.dataset.sbForget;
    memList = memList.filter((m) => m.id !== id);
    const i = mems.findIndex((m) => m.id === id);
    if (i >= 0) mems.splice(i, 1);
    buildLinks();
    host.querySelector("[data-sb-memn]").textContent = memList.length;
    if (focus === id) focus = null;
    showTab("mem");
    kick();
    toast(L("好，她不会再记得这件事了", "Got it — she won't remember that"));
  });
  showTab("soul");

  // ---------- 渲染 ----------
  let W = 0, H = 0, dpr = 1, rotY = -0.35, rotX = 0.12, spin = !reduce, last = performance.now(), raf = 0, alive = true;
  let drag = null, mouse = null, hover = null;
  function resize() {
    dpr = Math.min(2, devicePixelRatio || 1);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.max(1, W * dpr); canvas.height = Math.max(1, H * dpr);
    kick();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  function project(pt) {
    const cy = Math.cos(rotY), sy = Math.sin(rotY), cx = Math.cos(rotX), sx = Math.sin(rotX);
    const x = pt.x * cy + pt.z * sy;
    let z = -pt.x * sy + pt.z * cy;
    const y = pt.y * cx - z * sx; z = pt.y * sx + z * cx;
    const scale = Math.min(W * 1.05, H * 1.2) * 0.4, persp = 2.6 / (2.6 + z);
    return [W / 2 + x * scale * persp, H * 0.47 + y * scale * persp, persp, z];
  }

  function frame(now) {
    raf = 0;
    if (!alive) return;
    if (!host.isConnected) return stop();
    if (!W || !H) return;
    const dt = Math.min(50, now - last); last = now;
    if (spin && !drag) rotY += dt * 0.00012;
    const T = now / 1000;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = "lighter";

    // 全息底座：几圈光环 + 虚线转盘 + 光柱
    const bx = W / 2, by = H * 0.93;
    for (let i = 0; i < 5; i++) {
      const rx = W * (0.09 + i * 0.06), ry = rx * 0.17, a = 0.5 - i * 0.08 + 0.1 * Math.sin(T * 2 + i);
      ctx.strokeStyle = rgba(CYAN, Math.max(0.05, a)); ctx.lineWidth = i === 0 ? 2.2 : 1;
      ctx.shadowColor = rgba(CYAN, 0.9); ctx.shadowBlur = i === 0 ? 18 : 6;
      ctx.beginPath(); ctx.ellipse(bx, by, rx, ry, 0, 0, Math.PI * 2); ctx.stroke();
    }
    ctx.shadowBlur = 0;
    ctx.setLineDash([2, 6]); ctx.strokeStyle = rgba(CYAN, 0.55); ctx.lineDashOffset = -T * 20;
    ctx.beginPath(); ctx.ellipse(bx, by, W * 0.18, W * 0.18 * 0.17, 0, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    const beam = ctx.createLinearGradient(0, 0, 0, by);
    beam.addColorStop(0, rgba(CYAN, 0)); beam.addColorStop(0.5, rgba(CYAN, 0.16)); beam.addColorStop(1, rgba(CYAN, 0.6));
    ctx.fillStyle = beam; ctx.fillRect(bx - 1.2, 0, 2.4, by);
    ctx.strokeStyle = "rgba(120,170,255,.13)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.ellipse(W / 2, H * 0.5, W * 0.47, H * 0.12, -0.05, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.ellipse(W / 2, H * 0.48, W * 0.38, H * 0.44, 0, 0, Math.PI * 2); ctx.stroke();

    // 脑形粒子（远的暗、近的亮）
    for (const d of dust) {
      const [x, y, s, z] = project(d);
      const tw = 0.55 + 0.45 * Math.sin(T * 1.7 + d.tw);
      ctx.fillStyle = rgba(d.side < 0 ? GOLD : VIOLET, (0.2 + 0.38 * tw) * (z < 0 ? 1 : 0.5));
      const sz = d.s * s * 1.35;
      ctx.fillRect(x - sz / 2, y - sz / 2, sz, sz);
    }
    // 神经连线和流过的信号
    for (const l of links) {
      const [x1, y1] = project(l.a), [x2, y2] = project(l.b);
      const f = 0.5 + 0.5 * Math.sin(T * l.sp + l.ph);
      const on = focus && (l.a.key === focus || l.a.parent === focus || l.a.id === focus);
      const col = l.a.kind === "mem" ? l.a.col : GOLD;
      if (l.a.kind === "mem" && now < l.a.born) continue;
      ctx.strokeStyle = rgba(col, on ? 0.8 : (l.strong ? 0.2 : 0.08) * (0.4 + f));
      ctx.lineWidth = on ? 1.3 : 0.6;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      if (l.strong && !reduce) {
        const k = ((T * l.sp * 0.35 + l.ph) % 1 + 1) % 1;
        ctx.fillStyle = rgba(col, 0.9);
        ctx.fillRect(x1 + (x2 - x1) * k - 1, y1 + (y2 - y1) * k - 1, 2, 2);
      }
    }
    // 中心核
    const [ccx, ccy] = project(CENTER);
    const core = ctx.createRadialGradient(ccx, ccy, 0, ccx, ccy, 46);
    core.addColorStop(0, "rgba(220,240,255,.55)"); core.addColorStop(1, "rgba(80,220,255,0)");
    ctx.fillStyle = core; ctx.beginPath(); ctx.arc(ccx, ccy, 46, 0, Math.PI * 2); ctx.fill();

    // 节点：灵魂维度、设定、记忆
    hover = null;
    const pts = [...nodes, ...mems].map((n) => ({ n, q: project(n) })).sort((a, b) => b.q[3] - a.q[3]);
    for (const { n, q: [x, y, s] } of pts) {
      let a = 1;
      if (n.kind === "mem") { const age = now - n.born; if (age < 0) continue; a = Math.min(1, age / 700) * n.fade; }
      const pulse = n.hot ? 1 + 0.5 * Math.abs(Math.sin(T * 3 + n.x * 9)) : 1 + 0.12 * Math.sin(T * 2 + n.y * 7);
      const on = focus && (n.key === focus || n.parent === focus || n.id === focus);
      const rad = n.size * s * pulse * (on ? 1.5 : 1) * (n.kind === "mem" && a < 1 ? 1 + (1 - a) * 2 : 1);
      ctx.shadowColor = rgba(n.col, 1); ctx.shadowBlur = (n.kind === "dim" ? 22 : n.kind === "mem" ? 16 : 10) * (on ? 1.6 : 1);
      ctx.fillStyle = rgba(n.col, 0.95 * a);
      ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.fill();
      if (n.newest && !reduce) {
        const k = (T % 2.4) / 2.4;
        ctx.shadowBlur = 0; ctx.strokeStyle = rgba(n.col, 0.7 * (1 - k)); ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(x, y, rad + k * 22, 0, Math.PI * 2); ctx.stroke();
      }
      if (mouse && (mouse[0] - x) ** 2 + (mouse[1] - y) ** 2 < Math.max(64, (rad + 5) ** 2)) hover = n;
    }
    ctx.shadowBlur = 0;
    ctx.globalCompositeOperation = "source-over";
    ctx.font = "500 11.5px system-ui, 'PingFang SC', 'Microsoft YaHei', sans-serif";
    ctx.textAlign = "center";
    for (const n of nodes) {
      if (n.kind !== "dim") continue;
      const [x, y, s, z] = project(n);
      ctx.fillStyle = rgba(GOLD_HI, (focus === n.key ? 1 : 0.8) * (z < 0.3 ? 1 : 0.45));
      ctx.fillText(n.label, x, y - 10 * s - 4);
    }
    if (hover && mouse) {
      tip.innerHTML = `<small>${esc(hover.label)}</small>${esc(clip(hover.kind === "dim" ? hover.items.join(L("；", "; ")) : hover.text || "", 90))}`;
      tip.style.left = Math.max(8, Math.min(W - 260, mouse[0] + 14)) + "px"; tip.style.top = Math.max(8, mouse[1] - 10) + "px";
      tip.classList.add("on"); canvas.style.cursor = "pointer";
    } else { tip.classList.remove("on"); canvas.style.cursor = drag ? "grabbing" : "grab"; }
    if (!reduce || drag) raf = requestAnimationFrame(frame);
  }

  const clock = host.querySelector("[data-sb-clock]");
  const tick = setInterval(() => { if (!host.isConnected) return stop(); clock.textContent = new Date().toLocaleTimeString("en-GB") + " · LIVE"; }, 1000);

  // ---------- 交互 ----------
  canvas.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, ry: rotY, rx: rotX, moved: false }; canvas.setPointerCapture(e.pointerId); kick(); });
  canvas.addEventListener("pointermove", (e) => {
    const rect = canvas.getBoundingClientRect(); mouse = [e.clientX - rect.left, e.clientY - rect.top];
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      rotY = drag.ry + dx * 0.008; rotX = Math.max(-0.7, Math.min(0.7, drag.rx + dy * 0.006));
    }
    kick();
  });
  canvas.addEventListener("pointerleave", () => { mouse = null; kick(); });
  canvas.addEventListener("pointerup", () => {
    const moved = drag?.moved; drag = null;
    if (!moved && hover) {
      if (hover.kind === "mem") { focus = hover.id; showTab("mem", hover.id); }
      else { focus = hover.key || hover.parent; showTab("soul", focus); }
    }
    kick();
  });
  host.querySelector('[data-sb-ctl="spin"]').onclick = (e) => { spin = !spin; e.target.classList.toggle("on", spin); kick(); };
  host.querySelector('[data-sb-ctl="reset"]').onclick = () => { rotY = -0.35; rotX = 0.12; focus = null; showTab(tab); kick(); };

  function kick() { if (!raf && alive) { last = performance.now(); raf = requestAnimationFrame(frame); } }
  const vis = () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; } else kick(); };
  document.addEventListener("visibilitychange", vis);
  function stop() { alive = false; cancelAnimationFrame(raf); ro.disconnect(); clearInterval(tick); document.removeEventListener("visibilitychange", vis); }
  host._sbStop = stop;
  // 测试和调试用：能点的节点在画布上的位置
  host._sbNodes = () => [...nodes, ...mems].map((n) => ({ kind: n.kind, key: n.key || n.id, at: project(n) }));
  kick();
}
