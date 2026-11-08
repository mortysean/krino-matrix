// 灵魂的神经网络视图（工作台右栏）。只看不改：灵魂是她自己的，改了就不是她了（OOC）；想要不一样的她，就新建一个角色。
// 中间是她，第一圈是灵魂的几个维度（性格、说话方式、价值观……），外圈每个点是一条具体设定；信号沿着连线流动。
// 点一个维度，下面显示它的全部内容。
import { esc, t } from "./core.js";
import { getLocale } from "./i18n.js";

const DIMS = [  // [字段, 中文, 英文]
  ["personality", "性格", "Personality"], ["speech", "说话方式", "Speech"], ["values", "价值观", "Values"],
  ["interests", "兴趣", "Interests"], ["preferences", "小习惯", "Habits"], ["relationships", "关系", "Relationships"],
  ["worldview", "世界", "World"], ["background", "来历", "Background"], ["boundaries", "底线", "Boundaries"],
];
const STYLE_EN = { 温柔: "Gentle", 俏皮: "Playful", 沉稳: "Calm", 元气: "Lively" };

// 一个字段拆成一条条设定：有“- ”列表就按列表，没有就按句子
function bullets(text) {
  const s = String(text || "").trim();
  if (!s) return [];
  const lines = s.split(/\n+/).map((x) => x.replace(/^\s*[-*•·]\s*/, "").trim()).filter(Boolean);
  if (lines.length > 1) return lines.slice(0, 8);
  return s.split(/(?<=[。！？.!?])\s*/).map((x) => x.trim()).filter(Boolean).slice(0, 6);
}

const clip = (s, n) => ([...s].length > n ? [...s].slice(0, n).join("") + "…" : s);

export function soulGraph(host, c, { onNew } = {}) {
  const en = getLocale() === "en";
  const p = c.persona || {}, b = c.behavior || {};
  const dims = DIMS.map(([k, zh, e]) => ({ key: k, label: en ? e : zh, items: bullets(p[k]) })).filter((d) => d.items.length);
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const W = 560, H = 430, cx = W / 2, cy = H / 2 - 6, R1 = 128, R2 = 186;
  const color = esc(p.color || "#1414a8");
  let selected = dims.find((d) => d.key === "personality") ? "personality" : dims[0]?.key;

  // 位置：维度均匀分布一圈；每个维度的设定在它外侧散开
  const pos = dims.map((d, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / dims.length;
    const span = Math.min(0.9, (2 * Math.PI) / dims.length) * 0.8;
    const leaves = d.items.map((txt, j) => {
      const k = d.items.length === 1 ? 0 : j / (d.items.length - 1) - 0.5;
      const r = R2 + (j % 2 ? 14 : 0);
      return { txt, x: cx + Math.cos(a + k * span) * r, y: cy + Math.sin(a + k * span) * r, a: a + k * span };
    });
    return { ...d, a, x: cx + Math.cos(a) * R1, y: cy + Math.sin(a) * R1, leaves };
  });

  const curve = (x1, y1, x2, y2, bend = 0.18) => {  // 略弯的连线，更像神经
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
    return `M${x1.toFixed(1)},${y1.toFixed(1)} Q${(mx - dy * bend).toFixed(1)},${(my + dx * bend).toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  };
  let paths = [], pulses = [], uid = 0;
  const edge = (d, cls, key, pulse) => {
    const id = `sg${c.id.slice(0, 6)}${uid++}`;
    paths.push(`<path id="${id}" d="${d}" class="${cls}" data-k="${key}"/>`);
    if (pulse && !reduce) {
      const dur = 2.2 + Math.random() * 3, begin = (-Math.random() * dur).toFixed(2);  // 负的开始时间：一出现就在半路上，不会先停在左上角
      pulses.push(`<circle r="2.4" class="sg-pulse" data-k="${key}"><animateMotion dur="${dur.toFixed(1)}s" begin="${begin}s" repeatCount="indefinite" rotate="auto"><mpath href="#${id}"/></animateMotion></circle>`);
    }
  };
  pos.forEach((d, i) => {
    edge(curve(cx, cy, d.x, d.y, 0.12), "sg-edge", d.key, true);
    d.leaves.forEach((l) => edge(curve(d.x, d.y, l.x, l.y, 0.25), "sg-edge thin", d.key, Math.random() < 0.5));
    const n = pos[(i + 1) % pos.length];
    if (pos.length > 2) edge(curve(d.x, d.y, n.x, n.y, -0.35), "sg-edge faint", "", Math.random() < 0.35);
  });

  const label = (d) => {
    const right = Math.cos(d.a) >= -0.15, x = d.x + (right ? 14 : -14);
    return `<text x="${x.toFixed(1)}" y="${(d.y + 4).toFixed(1)}" text-anchor="${right ? "start" : "end"}" class="sg-label">${esc(d.label)}</text>`;
  };
  const _leafLabel = (l) => {  // 外圈每条设定的文字太挤，改成点开后在下面卡片里看全文
    const right = Math.cos(l.a) >= 0, x = l.x + (right ? 8 : -8);
    return `<text x="${x.toFixed(1)}" y="${(l.y + 3).toFixed(1)}" text-anchor="${right ? "start" : "end"}" class="sg-leaf-label">${esc(clip(l.txt, en ? 22 : 12))}</text>`;
  };

  const style = b.style ? (en ? STYLE_EN[b.style] || b.style : b.style) : "";
  host.innerHTML = `
    <div class="soul-graph" style="--c:${color}">
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t("{name} 的灵魂", { name: p.name || "" }))}">
        <defs><radialGradient id="sg-core-${c.id.slice(0, 6)}"><stop offset="0" stop-color="${color}" stop-opacity=".9"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></radialGradient></defs>
        <g class="sg-edges">${paths.join("")}</g>
        <g class="sg-pulses">${pulses.join("")}</g>
        <circle cx="${cx}" cy="${cy}" r="58" fill="url(#sg-core-${c.id.slice(0, 6)})" class="sg-halo"/>
        <circle cx="${cx}" cy="${cy}" r="30" class="sg-core"/>
        <text x="${cx}" y="${cy + 5}" text-anchor="middle" class="sg-name">${esc(clip(p.name || "", 6))}</text>
        ${pos.map((d) => `<g class="sg-dim" data-k="${d.key}" tabindex="0" role="button" aria-label="${esc(d.label)}">
            ${d.leaves.map((l) => `<circle cx="${l.x.toFixed(1)}" cy="${l.y.toFixed(1)}" r="3.2" class="sg-leaf"/>`).join("")}
            <circle cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="9" class="sg-node"/>
            <circle cx="${d.x.toFixed(1)}" cy="${d.y.toFixed(1)}" r="22" class="sg-hit"/>
            ${label(d)}</g>`).join("")}
      </svg>
      <div class="sg-detail" aria-live="polite"></div>
      ${p.greeting ? `<blockquote class="sg-greet">“${esc(p.greeting)}”</blockquote>` : ""}
      <div class="sg-meta muted small">
        ${style ? `<span>${t("互动风格")} · ${esc(style)}</span>` : ""}
        ${(p.tags || []).slice(0, 6).map((x) => `<span class="sg-tag">${esc(x)}</span>`).join("")}
      </div>
      ${p.examples ? `<details class="sg-examples"><summary>${t("她平时怎么说话（对话样例）")}</summary><pre>${esc(p.examples)}</pre></details>` : ""}
      <div class="sg-lock">
        <span>${t("灵魂是她自己的，不能直接改——改了就不是她了。想要一个不一样的她？")}</span>
        <button class="ghost small" data-sg-new>${t("＋ 设计新角色")}</button>
      </div>
    </div>`;

  const svg = host.querySelector("svg"), detail = host.querySelector(".sg-detail");
  function select(key) {
    selected = key;
    svg.querySelectorAll("[data-k]").forEach((el) => el.classList.toggle("on", !!key && el.dataset.k === key));
    const d = pos.find((x) => x.key === key);
    detail.innerHTML = d ? `<b>${esc(d.label)}</b><ul>${d.items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
  }
  svg.querySelectorAll(".sg-dim").forEach((g) => {
    g.onclick = () => select(g.dataset.k);
    g.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(g.dataset.k); } };
  });
  host.querySelector("[data-sg-new]").onclick = () => onNew?.();
  select(selected);
}
