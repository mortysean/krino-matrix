// krinomatrix.com 公司门户的小脚本：语言切换、Cookie 提示、像素字、像素图标、翻页。没有统计、没有第三方。
(() => {
  const store = {  // 只存这两样：语言、Cookie 提示关没关。无痕模式拿不到也照常显示
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* 无痕模式 */ } },
  };
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- 语言 ----------
  const saved = store.get("km_lang");
  let lang = saved || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en");
  function setLang(l) {
    lang = l;
    document.documentElement.dataset.lang = l;
    document.documentElement.lang = l === "zh" ? "zh-CN" : "en";
    const t = document.querySelector(`meta[name="title-${l}"]`);
    if (t) document.title = t.content;
    document.querySelectorAll(".lang").forEach((b) => (b.innerHTML = l === "zh" ? "<b>中</b> / EN" : "中 / <b>EN</b>"));
    document.querySelectorAll("canvas[data-pixel]").forEach(drawPixelText);
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest(".lang")) { setLang(lang === "zh" ? "en" : "zh"); store.set("km_lang", lang); }
  });

  // ---------- Cookie 提示：本站不用追踪 Cookie，告诉一声就行 ----------
  const bn = document.querySelector(".cookie");
  if (bn && !store.get("km_cookie_ok")) bn.hidden = false;
  bn?.querySelector("button")?.addEventListener("click", () => { bn.hidden = true; store.set("km_cookie_ok", "1"); });

  // ---------- 像素字：5×7 点阵，自己画（不依赖字体文件） ----------
  const G = {
    A: ".###.#...##...#######...##...##...#", B: "####.#...##...#####.#...##...#####.", C: ".#####....#....#....#....#.....####",
    D: "####.#...##...##...##...##...#####.", E: "######....#....####.#....#....#####", F: "######....#....####.#....#....#....",
    G: ".#####....#....#..###...##...#.####", H: "#...##...##...#######...##...##...#", I: "#####..#....#....#....#....#..#####",
    J: "..###...#....#....#....#.#..#..##..", K: "#...##..#.#.#..##...#.#..#..#.#...#", L: "#....#....#....#....#....#....#####",
    M: "#...###.###.#.##.#.##...##...##...#", N: "#...###..##.#.##..###...##...##...#", O: ".###.#...##...##...##...##...#.###.",
    P: "####.#...##...#####.#....#....#....", Q: ".###.#...##...##...##.#.##..#..##.#", R: "####.#...##...#####.#.#..#..#.#...#",
    S: ".#####....#.....###.....#....#####.", T: "#####..#....#....#....#....#....#..", U: "#...##...##...##...##...##...#.###.",
    V: "#...##...##...##...##...#.#.#...#..", W: "#...##...##...##.#.##.#.###.###...#", X: "#...##...#.#.#...#...#.#.#...##...#",
    Y: "#...##...#.#.#...#....#....#....#..", Z: "#####....#...#...#...#...#....#####", " ": "...................................",
    "-": "...............###...............", ".": "..............................##...",
  };
  function drawPixelText(cv) {
    let text = (cv.dataset[lang === "zh" ? "pixelZh" : "pixel"] || cv.dataset.pixel).toUpperCase();
    if (innerWidth > 760) text = text.replace("|", " ");  // 宽屏一行，窄屏两行
    const lines = text.split("|");
    const cols = Math.max(...lines.map((l) => l.length * 6 - 1)), rows = lines.length * 9 - 2;
    const cell = 4;  // 一个像素点画 4×4（再加 1 的间隙），CSS 再整体缩放
    cv.width = cols * cell; cv.height = rows * cell;
    const g = cv.getContext("2d");
    const dots = [];
    lines.forEach((line, li) => [...line].forEach((ch, i) => {
      const bits = G[ch] || G[" "];
      for (let y = 0; y < 7; y++) for (let x = 0; x < 5; x++) if (bits[y * 5 + x] === "#") dots.push([i * 6 + x, li * 9 + y]);
    }));
    cv._dots = dots; cv._cell = cell;
    cv._split = lines.length === 1 && text.includes(" ") ? text.indexOf(" ") * 6 : 0;
    if (reduce || cv._drawn) return paint(cv, 1);
    cv._drawn = true;
    const order = dots.map((_, i) => i).sort(() => Math.random() - 0.5);  // 像素一个个亮起来
    const t0 = performance.now(), dur = 900;
    (function step(now) {
      const k = Math.min(1, (now - t0) / dur);
      paint(cv, k, order);
      if (k < 1) requestAnimationFrame(step); else glitchLoop(cv);
    })(t0);
  }
  function paint(cv, k, order) {
    const g = cv.getContext("2d"), c = cv._cell, dots = cv._dots;
    g.clearRect(0, 0, cv.width, cv.height);
    const n = Math.floor(dots.length * k);
    const show = order ? order.slice(0, n) : dots.map((_, i) => i);
    for (const i of show) {
      const [x, y] = dots[i];
      const hue = (cv._split ? x >= cv._split : y >= 7) ? "#3df5ff" : "#ecebf5";  // 第二个词用青色
      g.fillStyle = hue; g.fillRect(x * c, y * c, c - 1, c - 1);
    }
  }
  function glitchLoop(cv) {  // 每隔几秒闪一下：一条横带错位，青 / 品红分色
    if (reduce) return;
    const g = cv.getContext("2d");
    setInterval(() => {
      if (document.hidden) return;
      const h = cv.height, w = cv.width, band = Math.max(4, Math.floor(h * (0.12 + Math.random() * 0.2))), y = Math.floor(Math.random() * (h - band));
      const shift = (Math.random() < 0.5 ? -1 : 1) * cv._cell * (2 + Math.floor(Math.random() * 4));
      const img = g.getImageData(0, y, w, band);
      g.clearRect(0, y, w, band);
      g.putImageData(img, shift, y);
      g.globalCompositeOperation = "source-atop";
      g.fillStyle = Math.random() < 0.5 ? "rgba(255,61,154,.85)" : "rgba(61,245,255,.85)";
      g.fillRect(0, y, w, band);
      g.globalCompositeOperation = "source-over";
      setTimeout(() => paint(cv, 1), 120 + Math.random() * 120);
    }, 3200 + Math.random() * 1600);
  }

  // ---------- 像素图标：8×8 点阵 ----------
  const ICONS = {
    brain: ["..####..", ".#.##.#.", "#..##..#", "#.####.#", "#..##..#", ".#.##.#.", "..####..", "...##..."],
    chip: [".#.##.#.", "########", "#......#", "#.####.#", "#.####.#", "#......#", "########", ".#.##.#."],
    memory: ["########", "#......#", "#.#..#.#", "#......#", "#.####.#", "#......#", "########", "..#..#.."],
    wave: ["........", "...#....", "...#..#.", ".#.#..#.", ".#.##.#.", "##.####.", "########", "........"],
  };
  document.querySelectorAll("canvas[data-icon]").forEach((cv) => {
    const rows = ICONS[cv.dataset.icon], c = 5;
    cv.width = cv.height = 8 * c;
    const g = cv.getContext("2d");
    rows.forEach((r, y) => [...r].forEach((b, x) => {
      if (b !== "#") return;
      g.fillStyle = (x + y) % 5 === 0 ? "#ff3d9a" : "#3df5ff";
      g.fillRect(x * c, y * c, c - 1, c - 1);
    }));
  });

  setLang(lang);
  let wide = innerWidth > 760;
  addEventListener("resize", () => {  // 跨过宽窄分界才重画像素字
    if ((innerWidth > 760) !== wide) { wide = !wide; document.querySelectorAll("canvas[data-pixel]").forEach(drawPixelText); }
  });

  // ---------- 翻页 ----------
  const deck = document.querySelector(".deck");
  if (!deck) return;
  const slides = [...deck.querySelectorAll(".slide")];
  const pager = document.querySelector(".pager"), count = document.querySelector(".count");
  slides.forEach((s, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("aria-label", `${i + 1}`);
    b.innerHTML = `<span>${String(i + 1).padStart(2, "0")} ${s.dataset.name || ""}</span>`;
    b.onclick = () => go(i);
    pager?.appendChild(b);
  });
  let cur = 0;
  function mark(i) {
    cur = i;
    slides.forEach((s, j) => s.classList.toggle("on", j === i || s.classList.contains("on") && j < i));
    slides[i].classList.add("on");
    pager?.querySelectorAll("button").forEach((b, j) => b.classList.toggle("on", j === i));
    if (count) count.innerHTML = `<b>${String(i + 1).padStart(2, "0")}</b> / ${String(slides.length).padStart(2, "0")}`;
  }
  function go(i) { i = Math.max(0, Math.min(slides.length - 1, i)); slides[i].scrollIntoView({ behavior: reduce ? "auto" : "smooth" }); }
  const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) mark(slides.indexOf(e.target)); }), { root: deck, threshold: 0.55 });
  slides.forEach((s) => io.observe(s));
  mark(0);
  addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (["ArrowDown", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(cur + 1); }
    if (["ArrowUp", "PageUp"].includes(e.key)) { e.preventDefault(); go(cur - 1); }
    if (e.key === "Home") { e.preventDefault(); go(0); }
    if (e.key === "End") { e.preventDefault(); go(slides.length - 1); }
  });
  document.querySelectorAll("[data-go]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); go(+a.dataset.go); }));
})();
