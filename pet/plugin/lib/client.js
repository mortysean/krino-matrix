// KRINO 娘桌宠 · 浏览器端（DSH web）。手写的普通 JS，不需要打包。
//
// 动画：每个动作是一段透明 WebM，全部从同一个基础姿势开始、回到同一个姿势结束，所以任意两段首尾相接都不跳。
// 两个 <video> 叠在一起轮流用：一段快放完时，把“下一段”提前装进背后那个并停在第一帧，放完瞬间换到前面，
// 中间再淡入淡出 0.12 秒，看起来是一条连续的动画。
//
// 编排：一张很小的状态表（思路同 XState 的状态机）。AI 的状态（服务端折算好）+ 你的操作（点她、很久没动）
// → 当前心情（rest 平时 / busy 陪你干活 / ask 等你确认 / cheer 做完了 / oops 出错 / sleep 睡着）
// → 每段放完时按心情挑下一段。平时和睡着时的动作随时可以打断，其他动作放完再换，保证不突兀。
window.__ModuleLoader__.load({
  id: "dsh-pet-krino",
  factory: () => {
    var module = { exports: {} };
    var exports = module.exports;

    const PREFIX = "/dsh-pet-krino";
    const POS_KEY = "dsh-pet-krino:pos";
    const SLEEP_AFTER = 3 * 60 * 1000; // 多久没动静就打瞌睡
    const POLL_MS = 900;

    // 每种心情下：开场动作、循环时从哪些动作里挑、说什么
    const MOODS = {
      rest: { pool: ["idle"], flourish: ["glasses", "look", "stretch"] },
      busy: { enter: "nod", pool: ["think", "read", "type", "read"], say: ["我陪你一起看～", "交给我，嗯。", "让我想想……"] },
      ask: { pool: ["wave"], say: ["需要你确认一下哦～", "这一步要你点头才行。"] },
      cheer: { enter: "done", say: ["搞定啦！", "完成～✌"] },
      oops: { enter: "think", say: ["唔，好像出了点问题……", "卡住了，要不要看看？"] },
      sleep: { pool: ["doze"], say: ["Zzz……"] },
    };
    const POKE = ["surprised", "happy", "wave", "glasses"];
    const POKE_SAY = ["诶？戳我干嘛……", "嗯哼，我在～", "想要一个自己的伙伴吗？点上面的按钮～", "今天也一起加油吧！"];
    const CALM = new Set(["idle", "doze"]); // 这些动作可以随时打断

    const pick = (arr, not) => {
      const xs = arr.filter((x) => x !== not);
      return (xs.length ? xs : arr)[Math.floor(Math.random() * (xs.length ? xs.length : arr.length))];
    };
    const base = () => new URL(document.baseURI).pathname.replace(/\/+$/, "") + PREFIX;
    const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent); // Safari 不支持 WebM 透明

    const CSS = `
.kp-root{position:fixed;z-index:2147483000;user-select:none;-webkit-user-select:none;touch-action:none;pointer-events:none}
.kp-pet{position:relative;width:100%;height:100%}
.kp-hit{position:absolute;left:30%;right:17%;top:3%;bottom:3%;pointer-events:auto;cursor:grab;border-radius:40% 40% 20% 20%}
.kp-root.dragging .kp-hit{cursor:grabbing}
.kp-pet video,.kp-pet img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;object-position:bottom;
  opacity:0;transition:opacity .12s linear;pointer-events:none;filter:url(#kp-alpha-fix) drop-shadow(0 6px 10px rgba(0,0,0,.18))}
.kp-pet .front{opacity:1}
.kp-pet img.front{animation:kp-bob 3.2s ease-in-out infinite;transform-origin:50% 100%}
@keyframes kp-bob{50%{transform:translateY(-2%) scaleY(1.01)}}
.kp-bubble{position:absolute;left:50%;bottom:calc(100% - 6px);transform:translate(-50%,6px);max-width:220px;width:max-content;
  padding:7px 12px;border-radius:14px;background:#fff;color:#222;font:13px/1.5 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  box-shadow:0 4px 16px rgba(0,0,0,.14);opacity:0;transition:opacity .25s,transform .25s;pointer-events:none}
.kp-bubble::after{content:"";position:absolute;left:50%;top:100%;margin-left:-6px;border:6px solid transparent;border-top-color:#fff}
.kp-bubble.on{opacity:1;transform:translate(-50%,0)}
.kp-go{position:absolute;left:50%;top:4px;transform:translate(-50%,-100%);white-space:nowrap;border:0;border-radius:999px;
  padding:5px 12px;background:#16161c;color:#fff;font:12px/1.4 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  cursor:pointer;opacity:0;transition:opacity .2s;box-shadow:0 3px 10px rgba(0,0,0,.2);pointer-events:auto}
.kp-root:hover .kp-go{opacity:.92}
.kp-root.dragging .kp-go,.kp-root.talking .kp-go{opacity:0}
.kp-go:hover{opacity:1!important;background:#2a2a35}
@media (prefers-reduced-motion:reduce){.kp-pet img.front{animation:none}}`;

    function apply(ctx) {
      const style = document.createElement("style");
      style.dataset.plugin = "dsh-pet-krino";
      style.dataset.pluginCss = "pet";
      style.textContent = CSS;
      document.head.appendChild(style);

      // 去掉解码后背景残留的 1/255 透明度（不然在某些显卡上背景会有一层极淡的灰）
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("width", "0"); svg.setAttribute("height", "0"); svg.style.position = "absolute";
      svg.innerHTML = '<filter id="kp-alpha-fix"><feComponentTransfer><feFuncA type="linear" slope="1" intercept="-0.0039215686"/></feComponentTransfer></filter>';
      document.body.appendChild(svg);

      const root = document.createElement("div");
      root.className = "kp-root";
      // 只有她身体那一块（kp-hit）接鼠标，旁边透明的地方点击会穿过去，不挡下面的界面
      root.innerHTML = '<button class="kp-go" type="button">捏一个自己的伙伴 ↗</button><div class="kp-pet"></div><div class="kp-hit"></div><div class="kp-bubble"></div>';
      const petEl = root.querySelector(".kp-pet"), hit = root.querySelector(".kp-hit"), bubble = root.querySelector(".kp-bubble"), goBtn = root.querySelector(".kp-go");
      document.body.appendChild(root);

      const S = { cfg: { size: 180, site: "https://www.krinomatrix.com", bubbles: true }, server: "idle", seq: -1, mood: "rest",
        clip: null, loops: 0, lastActive: Date.now(), queue: null, blobs: {}, gen: 0, alive: true };

      // ---------- 位置和大小（拖到哪里记住哪里） ----------
      const ASPECT = 373 / 400;
      function place(x, y) {
        const w = S.cfg.size * ASPECT, h = S.cfg.size;
        x = Math.min(Math.max(0, x), innerWidth - w); y = Math.min(Math.max(0, y), innerHeight - h);
        Object.assign(root.style, { width: w + "px", height: h + "px", left: x + "px", top: y + "px" });
        return { x, y };
      }
      function restore() {
        let p = null;
        try { p = JSON.parse(localStorage.getItem(POS_KEY) || "null"); } catch {}
        const w = S.cfg.size * ASPECT;
        place(p ? p.rx * innerWidth - w / 2 : innerWidth - w - 24, p ? p.ry * innerHeight - S.cfg.size : innerHeight - S.cfg.size - 16);
      }
      function save() {
        const r = root.getBoundingClientRect();
        try { localStorage.setItem(POS_KEY, JSON.stringify({ rx: (r.left + r.width / 2) / innerWidth, ry: r.bottom / innerHeight })); } catch {}
      }
      restore();
      const onResize = () => { const r = root.getBoundingClientRect(); place(r.left, r.top); };
      addEventListener("resize", onResize);

      // ---------- 气泡 ----------
      let bubbleTimer;
      function say(text, ms = 3200) {
        if (!text || !S.cfg.bubbles) return;
        bubble.textContent = text; bubble.classList.add("on"); root.classList.add("talking");
        clearTimeout(bubbleTimer);
        bubbleTimer = setTimeout(() => { bubble.classList.remove("on"); root.classList.remove("talking"); }, ms);
      }

      // ---------- 播放：两个 video 轮流 ----------
      const vids = [0, 1].map(() => {
        const v = document.createElement("video");
        v.muted = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
        petEl.appendChild(v);
        return v;
      });
      let front = 0, staged = null; // staged：背后那个已经装好的动作名
      const src = (name) => S.blobs[name] || `${base()}/clips/${name}.webm`;

      function stage(name) { // 把下一段装进背后的 video，停在第一帧
        const v = vids[1 - front];
        if (staged === name && v.readyState >= 2) return;
        staged = name;
        v.onended = null; v.pause(); v.src = src(name); v.currentTime = 0; v.load();
      }
      function show(name) { // 换到 name（如果已经装好就是瞬间）
        const gen = ++S.gen;
        const back = vids[1 - front], cur = vids[front];
        if (staged !== name) { staged = name; back.src = src(name); back.load(); }
        back.currentTime = 0;
        back.onended = () => { if (gen === S.gen) onEnded(); };
        const go = () => {
          if (gen !== S.gen) return;
          back.classList.add("front"); cur.classList.remove("front");
          cur.onended = null;
          setTimeout(() => { if (gen === S.gen) cur.pause(); }, 140);
          front = 1 - front; staged = null; S.clip = name;
          if (S.pendingSay && S.pendingSay.clip === name) { say(S.pendingSay.text, S.pendingSay.ms); S.pendingSay = null; }
          root.dataset.clip = name; root.dataset.mood = S.mood; // 方便调试和测试
          setTimeout(() => { if (gen === S.gen && S.alive) stage(predict()); }, 400); // 提前装好下一段
        };
        back.play().then(go, () => { // 浏览器不让自动播放（很少见）：退回静态图
          if (gen === S.gen) fallback();
        });
      }

      // ---------- 编排 ----------
      function moodOf() {
        if (S.server === "waiting") return "ask";
        if (S.server === "working") return "busy";
        if (Date.now() - S.lastActive > SLEEP_AFTER) return "sleep";
        return "rest";
      }
      function nextClip(commit) { // 这一段放完之后放什么；commit = 真要放了（会更新计数），否则只是预判
        if (S.queue) { const q = S.queue; if (commit) S.queue = null; return q; }
        let mood = S.mood;
        if (mood === "cheer" || mood === "oops") { mood = moodOf(); if (commit) S.mood = mood; } // 庆祝 / 出错只放一段
        const m = MOODS[mood];
        if (mood === "rest") {
          const loops = S.clip === "idle" ? S.loops + 1 : 0;
          const flourish = loops >= 2 && Math.random() < 0.45;
          if (commit) S.loops = flourish ? 0 : loops;
          return flourish ? pick(m.flourish, S.clip) : "idle";
        }
        return pick(m.pool, S.clip);
      }
      const predict = () => nextClip(false);
      function onEnded() { if (S.alive) show(nextClip(true)); }

      function setMood(m) {
        if (m === S.mood) return;
        S.mood = m;
        const def = MOODS[m];
        const first = def.enter || def.pool[0];
        S.pendingSay = def.say ? { clip: first, text: pick(def.say), ms: m === "ask" ? 6000 : 3200 } : null;
        if (CALM.has(S.clip) || !S.clip) { S.queue = null; show(first); } // 平时的动作直接换
        else S.queue = first;                                            // 正在做动作：做完再换
      }

      // AI 状态变化 → 心情
      function onServer(state, seq) {
        const changed = seq !== S.seq;
        S.seq = seq;
        if (S.server !== state) S.lastActive = Date.now();
        S.server = state;
        if (state === "done" && changed) return setMood("cheer");
        if (state === "error" && changed) return setMood("oops");
        if (S.mood === "cheer" || S.mood === "oops") return; // 庆祝 / 出错的那一段先放完
        setMood(moodOf());
      }

      // ---------- 你的操作：点她、拖她 ----------
      let down = null;
      hit.addEventListener("pointerdown", (e) => {
        const r = root.getBoundingClientRect();
        down = { x: e.clientX, y: e.clientY, dx: e.clientX - r.left, dy: e.clientY - r.top, moved: false };
        hit.setPointerCapture(e.pointerId);
      });
      hit.addEventListener("pointermove", (e) => {
        if (!down) return;
        if (!down.moved && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 5) return;
        down.moved = true; root.classList.add("dragging");
        place(e.clientX - down.dx, e.clientY - down.dy);
      });
      hit.addEventListener("pointerup", () => {
        if (!down) return;
        const moved = down.moved; down = null; root.classList.remove("dragging");
        if (moved) return save();
        poke();
      });
      function poke() {
        S.lastActive = Date.now();
        if (S.mood === "sleep") S.mood = "rest";
        const clip = S.clip === "surprised" ? pick(POKE, "surprised") : pick(POKE, S.clip);
        if (S.mood === "ask") return say(pick(MOODS.ask.say), 4000); // 等你确认时不闹
        S.pendingSay = { clip, text: pick(POKE_SAY), ms: 3200 };
        if (CALM.has(S.clip)) show(clip); else S.queue = clip;
      }
      goBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const url = S.cfg.site.replace(/\/+$/, "") + "/?from=dsh-pet#workbench";
        window.open(url, "_blank", "noopener,noreferrer");
        say("在工作台里，灵魂和样子都可以自己定～", 4000);
      });
      const active = () => { S.lastActive = Date.now(); if (S.mood === "sleep") setMood(moodOf()); };
      addEventListener("keydown", active, true);
      addEventListener("pointerdown", active, true);

      // ---------- 静态图兜底（Safari 不支持透明 WebM） ----------
      function fallback() {
        if (petEl.querySelector("img")) return;
        vids.forEach((v) => v.remove());
        const img = document.createElement("img");
        img.src = `${base()}/clips/idle.png`; img.className = "front"; img.alt = "";
        petEl.appendChild(img);
      }

      // ---------- 启动 ----------
      async function preload(clips) { // 所有动作先下载成本地 blob：之后切换不用等网络
        for (const name of ["idle", ...clips.filter((c) => c !== "idle")]) {
          if (!S.alive) return;
          try { S.blobs[name] = URL.createObjectURL(await (await fetch(`${base()}/clips/${name}.webm`)).blob()); } catch {}
          if (name === "idle" && !S.clip) show("idle");
        }
      }
      let timer = null;
      async function poll() {
        if (!S.alive) return;
        try {
          const r = await fetch(`${base()}/state`, { cache: "no-store" });
          if (r.ok) {
            const d = await r.json();
            const first = S.seq < 0;
            if (first || d.config.size !== S.cfg.size) { S.cfg = d.config; restore(); }
            S.cfg = d.config;
            if (first) {
              if (isSafari) fallback(); else preload(d.clips);
              S.seq = d.seq; S.server = d.state;
              setTimeout(() => say("你好，我是 KRINO～有事叫我。", 3600), 900);
            } else onServer(d.state, d.seq);
          }
        } catch {}
        timer = setTimeout(poll, document.visibilityState === "visible" ? POLL_MS : 4000);
      }
      poll();

      const dispose = () => {
        S.alive = false; clearTimeout(timer); clearTimeout(bubbleTimer);
        removeEventListener("resize", onResize); removeEventListener("keydown", active, true); removeEventListener("pointerdown", active, true);
        vids.forEach((v) => { v.pause(); v.removeAttribute("src"); v.load(); });
        Object.values(S.blobs).forEach((u) => URL.revokeObjectURL(u));
        root.remove(); svg.remove(); style.remove();
      };
      if (ctx && typeof ctx.effect === "function") ctx.effect(() => dispose, "krino pet ui");
      else if (ctx && typeof ctx.on === "function") ctx.on("dispose", dispose);
      return dispose;
    }

    exports.name = "dsh-pet-krino";
    exports.inject = [];
    exports.apply = apply;
    return module.exports;
  },
});
