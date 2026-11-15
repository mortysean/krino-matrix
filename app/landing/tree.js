// Krino Tree：宣言与科技树页（/<地区>/vision/）的交互。没有统计、没有第三方。
//   宽屏：整棵树一次画完（国策树风格：像素徽章 + 名牌 + 直角连线，四个阶段用横幅分段），画在页面里、跟着页面一起滚动，
//         不是一个单独拖动的画布；比容器宽时按宽度缩小，放大后横向用滚动条。悬停或键盘聚焦一个节点：点亮它依赖的整条路径，旁边出提示。
//   窄屏、没有脚本：按阶段的节点清单（页面里本来就有，搜索引擎也能读）。
//   点任何节点：弹出详情（原生 <dialog>，Esc 关闭）。节点详情在 tree.json，宽屏打开页面就加载，窄屏第一次需要时才加载。
// 连线：同一枝干上下相连、阶段大箭头、汇入阶段终点的线常显；跨枝干的多重前置平时不画，只在追踪时出现，免得满屏连线。
(() => {
  const sec = document.getElementById("tree");
  if (!sec) return;
  const X = document.getElementById("tree-x");
  const scroller = X.querySelector(".tx-scroll"), sizer = X.querySelector(".tx-size"), stage = X.querySelector(".tx-stage"), svg = X.querySelector(".tx-links");
  const dlg = document.getElementById("node-dialog"), box = dlg.querySelector(".nd-in");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const wideMQ = matchMedia("(min-width: 900px)");
  const W = 196, H = 104, EM = 56, GX = 34, GY = 34, BAND = 58, PAD = 28;  // 节点宽高、徽章、列距、行距、阶段横幅、边距
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  let D = null, loading = null;
  const get = () => fetch("tree.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
  // 加载失败不缓存（跨境转发偶尔会抖），自动重试一次；之后再点还会重新加载
  const load = () => (loading ||= get().catch(() => new Promise((ok) => setTimeout(ok, 800)).then(get))
    .then((j) => (D = j)).catch((e) => { loading = null; throw e; }));

  // ---------- 像素徽章：8×8 点阵，按枝干取图 ----------
  const ICONS = {
    seed: [".##..##.", "###..###", ".##..##.", "...##...", "...##...", "...##...", ".######.", "########"],
    glasses: ["........", "#......#", "########", "#.#..#.#", "#.#..#.#", "###..###", "........", "........"],
    matrix: ["##....##", "##....##", "..#..#..", "...##...", "...##...", "..#..#..", "##....##", "##....##"],
    eye: ["........", "..####..", ".#....#.", "#..##..#", "#..##..#", ".#....#.", "..####..", "........"],
    memory: ["########", "#......#", "#.#..#.#", "#......#", "#.####.#", "#......#", "########", "..#..#.."],
    persona: ["...##...", "..####..", "..####..", "...##...", "..####..", ".######.", "########", "########"],
    brain: ["..####..", ".#.##.#.", "#..##..#", "#.####.#", "#..##..#", ".#.##.#.", "..####..", "...##..."],
    chip: [".#.##.#.", "########", "#......#", "#.####.#", "#.####.#", "#......#", "########", ".#.##.#."],
    wave: ["........", "...#....", "...#..#.", ".#.#..#.", ".#.##.#.", "##.####.", "########", "........"],
    net: ["#......#", ".#....#.", "..####..", "..#..#..", "..#..#..", "..####..", ".#....#.", "#......#"],
    ascend: ["...##...", "..####..", ".######.", "########", "...##...", "...##...", "...##...", "...##..."],
    time: ["########", ".#....#.", "..#..#..", "...##...", "...##...", "..#..#..", ".#....#.", "########"],
    star: ["...##...", "...##...", "########", ".######.", "..####..", "..####..", ".##..##.", "##....##"],
    crown: ["#..##..#", "#..##..#", "##.##.##", "########", "########", "........", "########", "########"],
  };
  const COL_ICON = {
    "第一个身体": "glasses", "开放矩阵": "matrix", "感知与情感解码": "eye", "一生记忆": "memory", "人格与灵魂推断": "persona",
    "微创接口": "brain", "高通道接口": "chip", "记忆假体与记忆桥": "memory", "感觉写回": "wave",
    "仿真与孪生汇合": "net", "飞升机制与连续性": "ascend", "保存与时间": "time",
  };
  const pixel = (name) => {
    const rows = ICONS[name] || ICONS.star;
    let r = "";
    rows.forEach((row, y) => [...row].forEach((b, x) => { if (b === "#") r += `<rect x="${x}" y="${y}" width="1" height="1"/>`; }));
    return `<svg viewBox="-1 -1 10 10" aria-hidden="true">${r}</svg>`;
  };

  // ---------- 依赖 ----------
  const reqs = (id) => [...(D.nodes[id].requires || []), ...(D.nodes[id].anyOf || [])];
  function ancestors(id) {
    const seen = new Set(), stack = reqs(id);
    while (stack.length) { const r = stack.pop(); if (!seen.has(r)) { seen.add(r); stack.push(...reqs(r)); } }
    return seen;
  }
  const dependents = (id) => Object.keys(D.nodes).filter((n) => reqs(n).includes(id));

  // ---------- 布局：整棵树，阶段从上到下 ----------
  function layout() {
    const phases = D.phases;
    const span = (n) => n * W + (n - 1) * GX;
    const total = Math.max(...phases.map((p) => Math.max(span(p.columns.length), p.gates ? span(p.gates.length) : 0)));
    const pos = {}, cols = {}, bands = [], icon = {};
    let y = PAD;
    const row = (ids, ic) => {  // 一行居中摆开
      const x0 = (total - span(ids.length)) / 2;
      ids.forEach((id, i) => { pos[id] = { x: PAD + x0 + i * (W + GX), y }; icon[id] = ic; });
      y += H + GY;
    };
    for (const p of phases) {
      bands.push({ id: p.id, y }); y += BAND;
      if (p.root) row(p.root, "seed");
      const x0 = (total - span(p.columns.length)) / 2;
      const rows = Math.max(...p.columns.map((c) => c.nodes.length));
      p.columns.forEach((c, ci) => c.nodes.forEach((id, ri) => {
        pos[id] = { x: PAD + x0 + ci * (W + GX), y: y + ri * (H + GY) };
        cols[id] = { phase: p.id, ci, ri };
        icon[id] = COL_ICON[c.v3] || "star";
      }));
      y += rows * (H + GY);
      if (p.gates) row(p.gates, "star");
      row([p.end], p.end === "ascension" ? "crown" : "star");
    }
    const edges = [];
    const roots = new Set(phases.flatMap((p) => p.root || []));
    for (const id of Object.keys(pos)) {
      for (const r of reqs(id)) {
        if (!pos[r]) continue;
        const a = cols[r], b = cols[id];
        let kind = "cross";
        if (a && b && a.phase === b.phase && a.ci === b.ci && b.ri === a.ri + 1) kind = "chain";
        else if (roots.has(r) && b && b.ri === 0 && D.nodes[r].phase === b.phase) kind = "chain";  // 阶段起点 → 各枝干第一个
        else if (D.milestones.includes(id)) kind = "end";
        edges.push({ from: r, to: id, kind });
      }
    }
    for (const p of phases) {  // 阶段大箭头：上一段的终点 → 本段每条枝干的第一个节点
      if (!p.gate) continue;
      for (const c of p.columns) if (!edges.some((e) => e.from === p.gate && e.to === c.nodes[0])) edges.push({ from: p.gate, to: c.nodes[0], kind: "gate" });
    }
    return { pos, edges, bands, icon, w: total + PAD * 2, h: y - GY + PAD };
  }

  // ---------- 画 ----------
  let cur = null, L = null;
  const badge = (s) => `<span class="st st-${s}">${esc(L.status[s])}</span>`;
  function path(e) {
    const a = cur.pos[e.from], b = cur.pos[e.to];
    const x1 = a.x + W / 2, y1 = a.y + H, x2 = b.x + W / 2, y2 = b.y + 2;
    if (e.kind === "cross") {  // 跨枝干：曲线，和主干的直角线区分开
      const dy = Math.max(40, (y2 - y1) / 2);
      return `M${x1} ${y1}C${x1} ${y1 + dy} ${x2} ${y2 - dy} ${x2} ${y2}`;
    }
    if (Math.abs(x1 - x2) < 1) return `M${x1} ${y1}V${y2}`;
    const ym = e.kind === "gate" ? y1 + GY / 2 : y2 - GY / 2;  // 国策树式直角线：在两行之间拐弯
    return `M${x1} ${y1}V${ym}H${x2}V${y2}`;
  }
  function draw() {
    L = D.labels;
    cur = layout();
    stage.querySelectorAll(".tn, .tx-band, .tx-tip").forEach((n) => n.remove());
    stage.style.width = cur.w + "px"; stage.style.height = cur.h + "px";
    svg.setAttribute("width", cur.w); svg.setAttribute("height", cur.h); svg.setAttribute("viewBox", `0 0 ${cur.w} ${cur.h}`);
    const frag = document.createDocumentFragment();
    for (const b of cur.bands) {
      const p = D.phases.find((x) => x.id === b.id), PL = L.phases[p.id];
      const el = document.createElement("div");
      el.className = `tx-band ph-${p.id}`; el.id = "tree-" + p.id;
      el.style.top = b.y + "px"; el.style.height = BAND - 16 + "px";
      el.innerHTML = `<span class="pn">0${p.n} · ${esc(p.key)}</span><span class="pt">${esc(PL.sub)}</span>`;
      frag.appendChild(el);
    }
    for (const [id, p] of Object.entries(cur.pos)) {
      const n = D.nodes[id];
      const b = document.createElement("button");
      b.type = "button";
      b.className = `tn s-${n.status} n-${n.nature}`;
      b.dataset.node = id;
      b.style.left = p.x + "px"; b.style.top = p.y + "px"; b.style.width = W + "px"; b.style.height = H + "px";
      b.setAttribute("aria-label", `${n.name}. ${L.status[n.status]}. ${L.nature[n.nature]}. ${n.summary}`);
      b.innerHTML = `<span class="em">${pixel(cur.icon[id])}</span><span class="pl"><i class="pip"></i><b>${esc(n.name)}</b></span>`;
      frag.appendChild(b);
    }
    const tip = document.createElement("div");
    tip.className = "tx-tip"; tip.hidden = true; tip.setAttribute("aria-hidden", "true");
    frag.appendChild(tip);
    stage.appendChild(frag);
    svg.innerHTML = `<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>` +
      cur.edges.map((e) => `<path class="e e-${e.kind}" data-from="${e.from}" data-to="${e.to}" d="${path(e)}"${e.kind === "cross" ? ' marker-end="url(#ah)"' : ""}/>`).join("");
    fit();
  }

  // ---------- 缩放：只改比例，树仍在页面里，跟页面一起滚 ----------
  let S = 1, fitS = 1;
  function apply() {
    stage.style.transform = `scale(${S})`;
    sizer.style.width = cur.w * S + "px"; sizer.style.height = cur.h * S + "px";
  }
  function fit() {
    if (!cur) return;
    fitS = Math.min(1, (scroller.clientWidth - 2) / cur.w);
    S = fitS; apply();
  }
  function zoom(f) {
    if (!cur) return;
    const cx = scroller.scrollLeft + scroller.clientWidth / 2, old = S;  // 横向保持中心不动；纵向由页面滚动，不用管
    S = Math.min(1.6, Math.max(fitS * 0.7, S * f)); apply();
    scroller.scrollLeft = cx * (S / old) - scroller.clientWidth / 2;
  }
  X.querySelector(".tx-zoom").addEventListener("click", (e) => {
    const b = e.target.closest("[data-zoom]"); if (!b) return;
    const z = +b.dataset.zoom;
    if (!z) fit(); else zoom(z > 0 ? 1.2 : 1 / 1.2);
  });
  addEventListener("resize", () => { if (!X.hidden) { const was = S === fitS; fitS = Math.min(1, (scroller.clientWidth - 2) / cur.w); if (was) fit(); } });

  // ---------- 追踪依赖 + 提示 ----------
  function trace(id) {
    clearTrace();
    if (!cur || !cur.pos[id]) return;
    const anc = ancestors(id), on = new Set([...anc, id]), next = new Set(dependents(id));
    X.classList.add("tracing");
    stage.querySelectorAll(".tn").forEach((n) => {
      n.classList.toggle("hl", on.has(n.dataset.node));
      n.classList.toggle("hl2", next.has(n.dataset.node));
    });
    svg.querySelectorAll(".e").forEach((p) => {
      p.classList.toggle("hl", on.has(p.dataset.from) && on.has(p.dataset.to));
      p.classList.toggle("hl2", p.dataset.from === id && next.has(p.dataset.to));
    });
    showTip(id);
  }
  function clearTrace() {
    X.classList.remove("tracing");
    stage.querySelectorAll(".hl, .hl2").forEach((n) => n.classList.remove("hl", "hl2"));
    const tip = stage.querySelector(".tx-tip"); if (tip) tip.hidden = true;
  }
  function showTip(id) {
    const tip = stage.querySelector(".tx-tip"), n = D.nodes[id], p = cur.pos[id];
    tip.innerHTML = `<p class="tt-meta">${badge(n.status)}<span class="nt-l">${esc(L.nature[n.nature])}</span></p><b>${esc(n.name)}</b><span>${esc(n.summary)}</span><small>${esc(L.open_node)} →</small>`;
    const right = p.x + W + 12 + 280 <= cur.w;
    tip.style.left = (right ? p.x + W + 12 : p.x - 12 - 280) + "px";
    tip.style.top = p.y + "px";
    tip.hidden = false;
  }
  stage.addEventListener("pointerover", (e) => { const n = e.target.closest(".tn"); if (n && e.pointerType !== "touch") trace(n.dataset.node); });
  stage.addEventListener("pointerout", (e) => { if (e.target.closest(".tn") && !e.relatedTarget?.closest?.(".tn")) clearTrace(); });
  stage.addEventListener("focusin", (e) => { const n = e.target.closest(".tn"); if (n) trace(n.dataset.node); });
  stage.addEventListener("focusout", (e) => { if (!stage.contains(e.relatedTarget)) clearTrace(); });

  // ---------- 宽屏：打开页面就画整棵树 ----------
  function failed() {
    sec.classList.remove("canvas-mode");
    X.hidden = true;
    if (sec.querySelector(".tx-failed")) return;
    const p = document.createElement("p");
    p.className = "note tx-failed"; p.textContent = L?.load_failed || (document.documentElement.lang.startsWith("zh") ? "战略数据加载失败，请刷新重试。" : "Couldn't load the tree data. Please refresh.");
    sec.querySelector(".phases").after(p);
  }
  let drawn = false;
  function ensureTree() {
    if (!wideMQ.matches) { sec.classList.remove("canvas-mode"); X.hidden = true; return Promise.resolve(false); }
    sec.classList.add("canvas-mode");
    return load().then(() => {
      X.hidden = false;
      if (!drawn) { draw(); drawn = true; } else fit();
      return true;
    }).catch((e) => { failed(); return false; });
  }
  wideMQ.addEventListener?.("change", ensureTree);

  // ---------- 跳到某个阶段 ----------
  function jump(phaseId, smooth = true) {
    ensureTree().then((wide) => {
      const t = wide ? document.getElementById("tree-" + phaseId) : document.getElementById("phase-" + phaseId);
      if (!t) return;
      if (!wide) t.open = true;
      t.scrollIntoView({ behavior: reduce || !smooth ? "auto" : "smooth", block: "start" });
      history.replaceState(null, "", "#phase-" + phaseId);
    });
  }
  sec.querySelector(".phases").addEventListener("click", (e) => {
    const a = e.target.closest("[data-phase]"); if (!a) return;
    e.preventDefault(); jump(a.dataset.phase);
  });

  // ---------- 详情 ----------
  const phaseOf = (id) => D.phases.find((p) => p.id === D.nodes[id].phase);
  function depItem(r) {
    const n = D.nodes[r];
    return `<li><button type="button" class="dep" data-node="${r}">${badge(n.status)} ${esc(n.name)}</button></li>`;
  }
  function sectionHTML(title, html) { return html ? `<section><h3>${esc(title)}</h3><div class="rt">${html}</div></section>` : ""; }
  function detail(id) {
    const n = D.nodes[id], p = phaseOf(id), PL = L.phases[p.id];
    let deps = "";
    if (n.anyOf.length) deps += `<p>${esc(L.anyof)}</p><ul class="deps">${n.anyOf.map(depItem).join("")}</ul>`;
    if (n.requires.length) deps += (n.requires.length > 1 ? `<p>${esc(L.all_required)}</p>` : "") + `<ul class="deps">${n.requires.map(depItem).join("")}</ul>`;
    if (!deps) deps = `<p>${esc(L.no_deps)}</p>`;
    if (p.gate && id !== p.end && !(p.gates || []).includes(id)) deps += `<p class="gate">${esc(L.gate_note.replace("{gate}", D.nodes[p.gate].name))}</p>`;
    let call = "";
    if (n.nature === "external") call = `<p class="callout c-ext">${esc(L.external_self)}</p>`;
    else if (n.externals.length && (n.status === "vision" || n.status === "planned"))
      call = `<p class="callout c-ext">${esc(L.external_callout.replace("{list}", n.externals.map((x) => D.nodes[x].name).join(", ")))}</p>`;
    if (n.nature === "milestone") call += `<p class="callout">${esc(n.anyOf.length ? L.milestone_calc_any : L.milestone_calc)}</p>`;
    let prog = "";
    if (n.done.length || n.remaining.length) {
      prog = `<section class="nd-prog"><h3>${esc(L.progress)}</h3><ul class="ok">${n.done.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` +
        (n.remaining.length ? `<h3>${esc(n.status === "completed" ? L.followups : L.remaining)}</h3><ul class="todo">${n.remaining.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : "") +
        (n.evidence ? `<p class="ev">${esc(L.code_evidence)}: <code>${esc(n.evidence)}</code></p>` : "") + `</section>`;
    }
    let rel = "";
    if (n.related) {
      const R = n.related, S = R.showcase;
      rel = `<section class="nd-rel"><h3>${esc(L.related)} · ${esc(R.name)}</h3>` +
        (S ? `<p>${esc(S.lead)}</p><dl class="feat">${S.features.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` +
          `<div class="nstats">${S.stats.map(([k, v]) => `<div><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join("")}</div><p class="note">${esc(S.beta)}</p>` : "") +
        (R.note ? `<p class="note">${esc(R.note)}</p>` : "") +
        `<p class="go"><a class="btn" href="${esc(R.app)}">${esc(R.app_label)}<small>${esc(R.host)}</small></a>` +
        (R.page ? `<a class="btn ghost" href="${esc(R.page)}">${esc(L.product_page)}</a>` : "") + `</p></section>`;
    }
    const tech = [["t_when", n.when], ["t_dur", n.dur], ["t_mode", n.mode], ["t_pre", n.pre], ["t_sci", n.sci], ["t_open", n.open], ["t_unlock", n.unlock], ["t_man", n.man],
      ["t_tags", [n.tag, ...(n.tags || [])].filter(Boolean).map(esc).join(" · ")]]
      .filter(([, v]) => v).map(([k, v]) => `<div><dt>${esc(L[k])}</dt><dd>${v}</dd></div>`).join("");
    return `<header class="nd-head"><p class="nd-meta">${badge(n.status)}<span class="nt-l n-${n.nature}">${esc(L.nature[n.nature])}</span><span>${esc(L.in_phase)} 0${p.n} · ${esc(p.key)} · ${esc(PL.sub)}</span></p>
      <h2 id="nd-title">${esc(n.name)}</h2><p class="nd-sum">${esc(n.summary)}</p>
      <button type="button" class="nd-x" aria-label="${esc(L.close)}">×</button></header>
      <div class="nd-body">${call}${prog}${rel}
      ${sectionHTML(L.what, n.body)}${sectionHTML(L.why, n.val)}${sectionHTML(L.deps, deps)}${sectionHTML(L.outcome, n.cap)}${sectionHTML(L.evidence, n.pass)}
      <details class="nd-tech"><summary>${esc(L.technical)}</summary>${L.t_translated ? `<p class="note">${esc(L.t_translated)}</p>` : ""}<dl>${tech}</dl></details></div>`;
  }
  let opener = null;
  function open(id) {
    load().then(() => {
      L = D.labels;
      if (!D.nodes[id]) return;
      if (!dlg.open) opener = document.activeElement;
      box.innerHTML = detail(id);
      box.scrollTop = 0;
      if (!dlg.open) dlg.showModal();
      box.querySelector(".nd-x").focus();
      history.replaceState(null, "", "#node-" + id);
    }).catch(failed);
  }
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.closest(".nd-x")) dlg.close();  // 点遮罩或 × 关闭
  });
  dlg.addEventListener("close", () => {
    history.replaceState(null, "", location.pathname + location.search + "#tree");
    opener?.focus?.({ preventScroll: true });
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-node]");
    if (!b) return;
    e.preventDefault();
    open(b.dataset.node);
  });

  // ---------- 深链接：#node-xxx 直接打开详情，#phase-xxx 跳到那一段 ----------
  function route() {
    const h = location.hash.slice(1);
    if (h.startsWith("node-")) {
      const id = h.slice(5);
      ensureTree().then((wide) => {
        if (wide) stage.querySelector(`.tn[data-node="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "center" });
        open(id);
      });
    } else if (h.startsWith("phase-")) jump(h.slice(6), false);
  }
  addEventListener("hashchange", route);  // 页面内点了 #node-xxx / #phase-xxx 链接
  ensureTree().then(route);
})();
