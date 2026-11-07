// KRINO 娘桌宠 · 服务端（DSH host）
// 1. 把动作视频（assets/clips/*.webm）通过 DSH 的网页服务发给浏览器；
// 2. 听 DSH 里 AI 的工作状态（session/event），折算成桌宠能看懂的几种状态，浏览器每隔一会儿来取一次。
// 只读：没有任何会改东西的接口。
import z from "schemastery";
import { createReadStream, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const name = "dsh-pet-krino";
export const inject = ["webServer"];

export const Config = z.object({
  size: z.natural().min(100).max(400).default(180).description("桌宠高度（像素）"),
  site: z.string().default("https://www.krinomatrix.com").description("“捏一个自己的伙伴”打开的网站"),
  bubbles: z.boolean().default(true).description("显示她的小气泡"),
});

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const CLIPS = join(ROOT, "assets", "clips");
const PREFIX = "/dsh-pet-krino";
const TYPES = { ".webm": "video/webm", ".png": "image/png", ".json": "application/json" };

// AI 的状态：idle 没事 / working 在干活 / waiting 等你确认或回答 / done 刚做完 / error 出错了
// 多个会话同时在跑时，优先级：waiting > working > done/error > idle
const RANK = { waiting: 4, working: 3, error: 2, done: 2, idle: 0 };
const DONE_MS = 6000; // “做完了”保持几秒，之后回到 idle

export function apply(ctx, config = {}) {
  const sessions = new Map(); // 会话 ID → { state, at }
  let seq = 0;
  let last = "idle";

  const current = () => {
    const now = Date.now();
    let best = "idle";
    for (const [id, s] of sessions) {
      if ((s.state === "done" || s.state === "error") && now - s.at > DONE_MS) { sessions.delete(id); continue; }
      if (RANK[s.state] > RANK[best]) best = s.state;
    }
    return best;
  };
  const set = (id, state) => {
    if (state === "idle") sessions.delete(id);
    else sessions.set(id, { state, at: Date.now() });
    const now = current();
    if (now !== last || state === "done") { last = now; seq++; }
  };

  ctx.on("session/event", (session, event) => {
    const h = session?.header || {};
    if (h.origin === "subagent" || (h.delegationDepth || 0) > 0) return; // 子任务不算
    const id = h.id ?? session?.id ?? "default";
    const d = event?.data || {};
    switch (event?.type) {
      case "turn/start": set(id, "working"); break;
      case "tool/call": set(id, d.name === "ask_user_question" ? "waiting" : "working"); break;
      case "approval/asked": set(id, "waiting"); break;
      case "approval/decided": set(id, "working"); break;
      case "turn/end": {
        const k = d.reason?.kind;
        set(id, k === "completed" ? "done" : k === "blocked" ? "waiting" : ["error", "max-tokens", "timeout"].includes(k) ? "error" : "idle");
        break;
      }
    }
  });
  ctx.on("session/disposed", (session) => { sessions.delete(session?.header?.id ?? session?.id); });

  const clips = readdirSync(CLIPS).filter((f) => f.endsWith(".webm")).map((f) => f.slice(0, -5)).sort();

  ctx.effect(() => ctx.webServer.register({
    kind: "prefix",
    path: PREFIX,
    handler(req, res) {
      if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405).end(); return; }
      const url = new URL(req.url || "/", "http://x");
      const sub = url.pathname.slice(url.pathname.indexOf(PREFIX) + PREFIX.length);
      if (sub === "/state") {
        const body = JSON.stringify({ seq, state: current(), clips,
          config: { size: config.size ?? 180, site: config.site || "https://www.krinomatrix.com", bubbles: config.bubbles !== false } });
        res.writeHead(200, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
        res.end(req.method === "HEAD" ? undefined : body);
        return;
      }
      const m = /^\/clips\/([a-z0-9-]+\.(webm|png))$/.exec(sub); // 只认文件名，不认路径
      if (!m) { res.writeHead(404).end(); return; }
      const file = join(CLIPS, m[1]);
      let st;
      try { st = statSync(file); } catch { res.writeHead(404).end(); return; }
      res.writeHead(200, { "content-type": TYPES["." + m[2]], "content-length": st.size, "cache-control": "public, max-age=86400" });
      if (req.method === "HEAD") { res.end(); return; }
      createReadStream(file).pipe(res);
    },
  }), "krino pet routes");
}
