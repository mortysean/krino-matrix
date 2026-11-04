// 鲸鱼娘立绘（沿用 Whale Girl 原有美术资源）：钴蓝底 + 银色线刻。3D 不可用时作为平面立绘。
// 线稿是透明 PNG，只用作 mask，颜色、光泽、颗粒都由 CSS 控制。
(function () {
  const LINES = ["灯塔的灯亮了。", "欢迎来到 KRINO WORLD。", "嗯？你在看哪里。", "再陪我一会儿。", "我是 AI，也是你的领航员。"];

  const plate = (cls = "") => `
    <div class="plate ${cls}">
      <div class="plate-fig"></div>
      <div class="plate-scan"></div>
    </div>`;
  const head = () => '<span class="fig-head"></span>';

  function mount(root = document) {
    root.querySelectorAll("[data-mascot]").forEach((el) => {
      if (el.dataset.mounted) return;
      el.dataset.mounted = "1";
      el.innerHTML = el.dataset.mascot === "head" ? head() : plate(el.dataset.mascot) + (el.hasAttribute("data-talk") ? '<div class="say hidden"></div>' : "");
      if (el.hasAttribute("data-talk")) el.onclick = () => talk(el);
    });
  }

  function talk(el, text) {
    const say = el.querySelector(".say");
    if (!say) return;
    say.textContent = text || LINES[Math.floor(Math.random() * LINES.length)];
    say.classList.remove("hidden", "in"); void say.offsetWidth; say.classList.add("in");
    clearTimeout(el._t); el._t = setTimeout(() => say.classList.add("hidden"), 2800);
  }

  // 按钮按下时的一圈墨水波纹
  function ripple(el) {
    const r = el.getBoundingClientRect();
    const i = document.createElement("i");
    i.className = "ripple";
    i.style.cssText = `left:${r.left + r.width / 2}px;top:${r.top + r.height / 2}px`;
    document.body.appendChild(i);
    setTimeout(() => i.remove(), 800);
  }

  mount();
  window.Mascot = { plate, head, mount, talk, ripple };
})();
