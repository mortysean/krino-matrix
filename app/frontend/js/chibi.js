// Q 版小人：会做动作的 2D 形象（portrait.kind = "chibi"）。和 DSH 桌宠插件同一套做法：
//   每个动作是一段透明 WebM，全部从同一个基础姿势开始、回到同一个姿势结束，所以任意两段首尾相接都不跳；
//   两个 <video> 叠在一起轮流用，下一段提前装好停在第一帧，切换时只淡入淡出 0.12 秒。
// 角色的动作清单在 /static/chibi/<角色>/chibi.json：
//   { clips: { 动作名: 文件 }, idle: [...待机时随机插的小动作], talk: "说话时循环的动作",
//     moves: { 聊天里的动作名: [可选的片段...] }, faces: { 表情: [片段...] } }
// 编排：说话时循环“说话”；聊天给了动作就做那个动作（说话中途也会插进去，做完接着说）；
// 没动作只有表情就做对应表情的片段；什么都没有时待机，隔一会儿随机做个小动作，像活的一样。

const pick = (arr, not) => {
  const xs = (arr || []).filter((x) => x !== not);
  const from = xs.length ? xs : arr || [];
  return from[Math.floor(Math.random() * from.length)];
};

export function createChibi(box) {
  const S = { def: null, base: "", blobs: {}, clip: null, queue: [], talking: false, idleLoops: 0, gen: 0, alive: true, ready: false };
  const wrap = document.createElement("div");
  wrap.className = "chibi";
  const vids = [0, 1].map(() => {
    const v = document.createElement("video");
    v.muted = true; v.playsInline = true; v.preload = "auto";
    v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
    wrap.appendChild(v);
    return v;
  });
  let front = 0, staged = null;
  box.prepend(wrap);

  const url = (name) => S.blobs[name] || S.base + S.def.clips[name];
  const pickReady = (opts) => { const ready = (opts || []).filter((x) => S.blobs[x]); return pick(ready.length ? ready : opts); };
  const has = (name) => !!(name && S.def?.clips[name]);

  function stage(name) {  // 把下一段装进背后的 video，停在第一帧
    const v = vids[1 - front];
    if (!has(name) || staged === name) return;
    staged = name;
    v.onended = null; v.pause(); v.src = url(name); v.load();
  }

  // maxWait：这个片段多久还放不出来就算了（网慢时不让动作慢半拍地出现），在后台下好，下次就快了
  function show(name, { maxWait = 0 } = {}) {
    if (!has(name)) return;
    const gen = ++S.gen;
    const back = vids[1 - front], cur = vids[front];
    if (staged !== name) { staged = name; back.src = url(name); back.load(); }
    try { back.currentTime = 0; } catch { /* 还没加载 */ }
    back.onended = () => { if (gen === S.gen) next(); };
    let giveUp = 0;
    if (maxWait && !S.blobs[name] && back.readyState < 3) {
      giveUp = setTimeout(() => {
        if (gen !== S.gen) return;
        const g2 = ++S.gen;
        back.onended = null; back.pause(); back.removeAttribute("src"); back.load(); staged = null;
        cur.onended = () => { if (g2 === S.gen) next(); };  // 让正在放的这段照常接下去
        if (cur.ended || cur.paused) next();
        fetchClip(name);
      }, maxWait);
    }
    back.play().then(() => {
      clearTimeout(giveUp);
      if (gen !== S.gen) return;
      back.classList.add("front"); cur.classList.remove("front");
      cur.onended = null;
      setTimeout(() => { if (gen === S.gen) cur.pause(); }, 140);
      front = 1 - front; staged = null; S.clip = name;
      wrap.dataset.clip = name;
      setTimeout(() => { if (gen === S.gen && S.alive) stage(peek()); }, 300);  // 提前装好下一段
    }, () => {});
  }

  // 这一段放完之后放什么（peek 只预判，不改状态）
  function choose(commit) {
    if (S.queue.length) return commit ? S.queue.shift() : S.queue[0];
    if (S.talking && has(S.def.talk)) return S.def.talk;
    const idle = S.def.rest || "idle";
    const loops = S.clip === idle ? S.idleLoops + 1 : 0;
    const flourish = loops >= 2 && Math.random() < 0.4 && S.def.idle?.length;
    if (commit) S.idleLoops = flourish ? 0 : loops;
    return flourish ? pick(S.def.idle, S.clip) : idle;
  }
  const peek = () => choose(false);
  const next = () => { if (S.alive) show(choose(true)); };
  const calm = () => !S.clip || S.clip === (S.def.rest || "idle") || S.clip === S.def.talk;  // 待机和说话可以随时打断

  // 做一个动作：正在待机 / 说话就马上换；正在做别的动作就排在后面（最多排一个，不攒一串）
  function act(name, { strong = true } = {}) {
    if (!has(name)) return false;
    if (S.recent && performance.now() - S.recent.at < 400 && !strong) return true;  // 刚做了明确的动作：表情片段不去抢
    if (strong) S.recent = { at: performance.now() };
    if (calm()) { S.queue = []; show(name, { maxWait: 1500 }); }
    else if (strong || !S.queue.length) S.queue = [name];
    return true;
  }

  async function load(src) {
    const res = await fetch(src);
    if (!res.ok) throw new Error(`Q 版小人加载失败（${res.status}）`);
    S.def = await res.json();
    S.base = src.replace(/[^/]+$/, "");
    const first = S.def.rest || "idle";
    await new Promise((ok, bad) => {  // 第一段能播了才算加载好
      const v = vids[front];
      v.src = S.base + S.def.clips[first]; v.loop = false;
      v.onloadeddata = () => ok(); v.onerror = () => bad(new Error("Q 版小人的视频打不开"));
      v.load();
    });
    vids[front].classList.add("front");
    vids[front].onended = () => next();
    S.clip = first; wrap.dataset.clip = first;
    vids[front].play().catch(() => {});
    S.ready = true;
    // 高清片段每段 1 MB 多，不在后台一口气全下（会占满带宽，反而让你点的那个动作要等）：
    // 只提前下“说话”；其余的由视频边下边播，播放器背后那一个会提前装好下一段；浏览器会缓存，下次就快了
    fetchClip(S.def.talk);
  }

  const loading = {};
  function fetchClip(name) {  // 下载成本地 blob，之后切换不用等网络
    if (!has(name) || S.blobs[name]) return Promise.resolve();
    return (loading[name] ||= fetch(S.base + S.def.clips[name]).then((r) => r.blob()).then((b) => {
      if (S.alive) S.blobs[name] = URL.createObjectURL(b);
    }).catch(() => {}).finally(() => delete loading[name]));
  }

  return {
    load,
    // 聊天里的动作名（wave、nod、shy……）→ 这个角色对应的片段
    play(name) { return act(pickReady(S.def?.moves?.[name] || (has(name) ? [name] : []))); },
    // 表情 → 对应的片段（没有就不动）
    expression(name) { const c = pickReady(S.def?.faces?.[name]); return c ? act(c, { strong: false }) : false; },
    speaking(on) {
      S.talking = !!on;
      if (on && calm() && has(S.def?.talk) && S.clip !== S.def.talk) { S.queue = []; show(S.def.talk); }
    },
    moves: () => Object.keys(S.def?.moves || {}),
    destroy() {
      S.alive = false; S.gen++;
      vids.forEach((v) => { v.pause(); v.removeAttribute("src"); v.load(); });
      Object.values(S.blobs).forEach((u) => URL.revokeObjectURL(u));
      wrap.remove();
    },
  };
}
