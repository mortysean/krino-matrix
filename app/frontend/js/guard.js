// 未成年人保护和《人工智能拟人化互动服务管理暂行办法》的前端部分（后端在 app/backend/app/guard.py）。
// - 第一次用：补出生年月；国内版还要紧急联系人；不满 14 岁要监护人同意（填好之前挡住整个应用）
// - 每分钟报一次心跳记使用时长；未成年人每 30 分钟提醒一次现实，时间用完或到了夜里挡住应用（监护人可以调）
// - 国内版：连续使用每 2 小时提醒一次；用得太多时提醒注意沉迷；聊天下方一直提示“对方是 AI”
// - 聊天里：退出（停掉语音对话和主动搭话）、危机时的求助电话卡片、疑似未成年人的说明和申诉
// - 设置页里的“未成年人模式”“聊天记录”“投诉与反馈”三块也在这里画
import { $, $$, S, api, bus, confirmBox, esc, fail, fmtTime, modal, storeGet, storeSet, t, toast, tr } from "./core.js";
import { getLocale } from "./i18n.js";

// ---------- 出生年月：两个下拉框（月、年） ----------
// 按美国 FTC《COPPA 规则》（2025 修订）和 COPPA FAQ D.7 的“中性年龄筛查”：让人如实填出生年月，不预设年龄、年份列表包括所有年龄，
// 不用“我已满 X 岁”的勾选框，也不在填之前说出年龄门槛（免得引导谎报）。不用浏览器自带的月份选择器：它的文字跟着浏览器语言走
// （英文站在中文浏览器里会显示中文），Safari、Firefox 桌面版也不支持。月份名按网站语言显示。
export function dobFields(id, value = "") {
  const [vy, vm] = (value || "").split("-").map(Number);
  const loc = getLocale() === "en" ? "en-US" : "zh-CN";
  const months = Array.from({ length: 12 }, (_, i) => new Date(2000, i, 1).toLocaleString(loc, { month: "long" }));
  const now = new Date().getFullYear();
  const years = Array.from({ length: 111 }, (_, i) => now - i);
  return `<div class="dob" id="${id}">
    <select data-dob="m" aria-label="${esc(t("月"))}" ${value ? "disabled" : ""}><option value="">${esc(t("月"))}</option>${months.map((m, i) => `<option value="${i + 1}" ${vm === i + 1 ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>
    <select data-dob="y" aria-label="${esc(t("年"))}" ${value ? "disabled" : ""}><option value="">${esc(t("年"))}</option>${years.map((y) => `<option value="${y}" ${vy === y ? "selected" : ""}>${y}</option>`).join("")}</select>
  </div>`;
}
export function readDob(root) {  // "YYYY-MM"；没选全就是 null
  const m = root?.querySelector('[data-dob="m"]')?.value, y = root?.querySelector('[data-dob="y"]')?.value;
  return m && y ? `${y}-${String(m).padStart(2, "0")}` : null;
}

// ---------- 登录和注册时的弹窗：先是要点，再是两个附件（服务条款、隐私政策全文），最后勾选 ----------
// 两个版本都只为成年人提供服务。登录：勾“已满 18 岁”和“同意”；注册：改填出生年月（国内版还有紧急联系人），再勾“同意”
// 要点是两份文件里最要紧的几条，改了条款或隐私政策（app/landing_src/content/）记得同步这里
const policyUrl = (doc) => `/${S.site?.edition === "cn" ? "cn" : "global"}/${doc}/`;
const policyLink = (doc, name) => `<a href="${policyUrl(doc)}" target="_blank" rel="noopener">${esc(t(name))}</a>`;
const policyAgree = () => t("我已阅读并同意{terms}和{privacy}", { terms: policyLink("terms", "《服务条款》"), privacy: policyLink("privacy", "《隐私政策》") });
function consentHTML(prefix, { ageBox = true } = {}) {
  const cn = S.site?.edition === "cn";
  const points = [
    "KRINO WORLD 只面向年满 18 周岁的用户。",
    "这里所有角色都是人工智能，不是真人。她们说的话可能不准确，不能当作医疗、法律、心理或财务建议；遇到危机请联系急救或心理援助热线。",
    "你和角色的聊天、你创建的角色、角色记下的关于你的事会被保存，用来让角色记得你；你可以随时查看、纠正、删除，注销账号时一并删除。",
    "麦克风和摄像头只在你点开后才使用，原始录音和画面不保存。我们不出售你的个人信息，也不用你的聊天训练模型。",
    cn ? "生成回复时，对话内容会经 OpenRouter 发往境外的模型服务处理。" : "语音、图片理解和形象生成在中国境内处理；生成回复时，对话内容会发往 OpenRouter 转接的模型服务。",
    "不得以真实人物为原型创建角色，不得发布色情、违法、仇恨或骚扰内容。",
  ];
  return `<div class="consent">
    <ul class="consent-points">${points.map((x) => `<li>${esc(t(x))}</li>`).join("")}</ul>
    <div class="consent-docs"><span class="mono">${esc(t("附件"))}</span>
      <a href="${policyUrl("terms")}" target="_blank" rel="noopener">${esc(t("《服务条款》"))} ↗</a>
      <a href="${policyUrl("privacy")}" target="_blank" rel="noopener">${esc(t("《隐私政策》"))} ↗</a></div>
    ${ageBox ? `<label class="check"><input type="checkbox" id="${prefix}-age"> ${esc(t("我已年满 18 周岁"))}</label>` : ""}
    <label class="check"><input type="checkbox" id="${prefix}-agree"> <span>${policyAgree()}</span></label>
  </div>`;
}
// 登录：返回要带给 /api/auth/login 的 { agree, of_age }，取消时为 null
export function consentBox() {
  return modal("欢迎来到 KRINO WORLD", `${consentHTML("c")}<p class="error" id="c-err"></p>`, (el) => {
    if (!$("#c-age", el).checked || !$("#c-agree", el).checked) { $("#c-err", el).textContent = t("请勾选以上各项"); return false; }
    return { agree: true, of_age: true };
  }, { okText: "同意并进入" });
}

// 注册：出生年月、紧急联系人（国内版）在这里登记，进了产品就不再问。返回要带给 /api/auth/register 的字段，取消时为 null
export function registerBox() {
  const cn = S.site?.edition === "cn";
  return modal("注册 KRINO WORLD", `
    <label>${t("出生年月")}${dobFields("r-birth")}</label>
    ${cn ? `<div class="section-title mono">${t("紧急联系人")}</div><p class="muted small">${t("你遇到危险时我们会联系的人。")}</p>
      <div class="row"><input id="r-cname" maxlength="20" placeholder="${esc(t("姓名"))}"><input id="r-cphone" maxlength="20" inputmode="tel" placeholder="${esc(t("电话"))}"></div>` : ""}
    ${consentHTML("r", { ageBox: false })}<p class="error" id="r-err"></p>`, (el) => {
    const err = (m) => { $("#r-err", el).textContent = t(m); return false; };
    const birth = readDob($("#r-birth", el));
    if (!birth) return err("请选择出生年月");
    const body = { birth, agree: true, of_age: true };
    if (cn) {
      body.contact = { name: $("#r-cname", el).value.trim(), phone: $("#r-cphone", el).value.trim() };
      if (!body.contact.name || !body.contact.phone) return err("请填写紧急联系人的姓名和电话");
    }
    if (!$("#r-agree", el).checked) return err("请勾选以上各项");
    return body;
  }, { okText: "同意并注册" });
}

export const G = { st: null, timer: null };
const isCn = () => (G.st?.edition || S.site?.edition) === "cn";

export async function refreshGuard() {
  try { G.st = await api("/api/guard"); } catch { return null; }
  apply();
  return G.st;
}

function apply() {
  const st = G.st;
  if (!st) return;
  document.documentElement.classList.toggle("minor-mode", st.minor);
  $("#ai-note")?.classList.toggle("hidden", st.edition !== "cn");
  if (st.needs.length) return gate();
  $("#guard-gate")?.remove();
  if (st.service_block) return ageBlock();
  $("#guard-age")?.remove();
  if (st.minor && (st.curfew_now || st.remaining_minutes === 0)) return lock();
  $("#guard-lock")?.remove();
}

// ---------- 第一次用：补信息（挡住整个应用） ----------
function ageOf(ym) {
  if (!/^\d{4}-\d{2}$/.test(ym || "")) return null;
  const [y, m] = ym.split("-").map(Number), d = new Date();
  return d.getFullYear() - y - (d.getMonth() + 1 < m ? 1 : 0);
}

function gate() {
  if ($("#guard-gate")) return;
  const st = G.st, cn = isCn();
  if (st.needs.includes("of_age")) return ageGate();
  const el = document.createElement("div");
  el.id = "guard-gate"; el.className = "guard-cover";
  el.innerHTML = `<form class="guard-card" novalidate>
    <h2>${t("开始之前")}</h2>
    <p class="muted small">${t("按照国家对人工智能拟人化互动服务和未成年人网络保护的要求，需要先登记年龄和紧急联系人。信息只用于保护你，不会公开。")}</p>
    <label>${t("出生年月")}${dobFields("g-birth", st.birth || "")}</label>
    <div id="g-contact" class="hidden"><div class="section-title mono">${t("紧急联系人")}</div>
      <p class="muted small">${t("你遇到危险时我们会联系的人。")}</p>
      <div class="row"><input id="g-cname" maxlength="20" placeholder="${esc(t("姓名"))}"><input id="g-cphone" maxlength="20" inputmode="tel" placeholder="${esc(t("电话"))}"></div></div>
    <div id="g-guardian" class="hidden"><div class="section-title mono">${t("监护人")}</div>
      <p class="muted small" id="g-gnote"></p>
      <div class="row"><input id="g-gname" maxlength="20" placeholder="${esc(t("监护人姓名"))}"><input id="g-gphone" maxlength="20" inputmode="tel" placeholder="${esc(t("监护人电话"))}"></div>
      <label>${t("监护人密码（4–6 位数字，监护人自己设，用来查看使用情况、调整限制）")}<input id="g-pin" type="password" inputmode="numeric" maxlength="6"></label>
      <label class="check"><input type="checkbox" id="g-consent"> ${t("我是监护人，已了解这个产品是和 AI 角色聊天，同意孩子在未成年人模式下使用")}</label></div>
    <p class="error" id="g-err"></p>
    <div class="row"><button type="submit">${t("确定")}</button><span class="grow"></span><button type="button" class="link small" id="g-logout">${t("退出登录")}</button></div>
  </form>`;
  document.body.appendChild(el);
  const sync = () => {
    const a = ageOf(readDob($("#g-birth", el)));
    const minor = a !== null && a < 18, under14 = a !== null && a < 14;
    // 国内版：成年人留紧急联系人，未成年人留监护人；国际站：只有不满 14 岁要监护人，14–17 岁可以不填
    $("#g-contact", el).classList.toggle("hidden", !(cn && a !== null && !minor));
    $("#g-guardian", el).classList.toggle("hidden", !(cn && minor));  // 国际站没有监护人这一套：不满 18 岁就不提供服务
    $("#g-gnote", el).textContent = under14 ? t("不满 14 周岁需要监护人同意才能使用。请让爸爸妈妈或其他监护人来填。")
      : t(cn ? "未满 18 周岁：请留监护人的联系方式，并由监护人设置密码。" : "Under 18: a parent or guardian can add their details here (optional).");
  };
  $("#g-birth", el).onchange = sync; sync();
  $("#g-logout", el).onclick = () => bus.emit("logout");
  el.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    const birth = readDob($("#g-birth", el)), a = ageOf(birth), body = {};
    if (!st.birth) { if (a === null || a < 0) return ($("#g-err", el).textContent = t("请填写出生年月")); body.birth = birth; }
    if (!$("#g-contact", el).classList.contains("hidden")) body.contact = { name: $("#g-cname", el).value, phone: $("#g-cphone", el).value };
    if (!$("#g-guardian", el).classList.contains("hidden") && ($("#g-gname", el).value || (a ?? 99) < 14 || cn)) {
      body.guardian = { name: $("#g-gname", el).value, phone: $("#g-gphone", el).value };
      body.guardian_consent = $("#g-consent", el).checked; body.pin = $("#g-pin", el).value;
    }
    try {
      G.st = await api("/api/guard/profile", { body });
      if (G.st.needs.length) { $("#g-err", el).textContent = t("还有信息没填完"); return; }
      el.remove(); apply(); toast("好了，开始吧");
    } catch (err) { $("#g-err", el).textContent = tr(err.message); }
  };
}

// 这个账号还没确认过已满 18 岁、同意条款（比如这个浏览器替别的账号确认过、没弹窗）：挡住应用，内容和登录弹窗一样，确认一次就不再出现
function ageGate() {
  const el = document.createElement("div");
  el.id = "guard-gate"; el.className = "guard-cover";
  el.innerHTML = `<form class="guard-card" novalidate>
    <h2>${t("欢迎来到 KRINO WORLD")}</h2>
    ${consentHTML("g")}
    <p class="error" id="g-err"></p>
    <div class="row"><button type="submit">${t("同意并进入")}</button><span class="grow"></span><button type="button" class="link small" id="g-logout">${t("退出登录")}</button></div>
  </form>`;
  document.body.appendChild(el);
  $("#g-logout", el).onclick = () => bus.emit("logout");
  el.querySelector("form").onsubmit = async (e) => {
    e.preventDefault();
    if (!$("#g-age", el).checked || !$("#g-agree", el).checked) return ($("#g-err", el).textContent = t("请勾选以上各项"));
    try {
      G.st = await api("/api/guard/profile", { body: { of_age: true, agree: true } });
      if (G.st.needs.length) { $("#g-err", el).textContent = t("还有信息没填完"); return; }
      el.remove(); apply();
    } catch (err) { $("#g-err", el).textContent = tr(err.message); }
  };
}

// ---------- 国际站：只为成年人提供服务 ----------
function ageBlock() {
  if ($("#guard-age")) return;
  const st = G.st, el = document.createElement("div");
  el.id = "guard-age"; el.className = "guard-cover";
  el.innerHTML = `<div class="guard-card"><h2>${t("无法继续使用")}</h2>
    <p>${t(st.service_block === "minor" ? "很抱歉，这个账号不能使用 KRINO WORLD。" : "从你的聊天看，你可能未满 18 周岁，服务已暂停。如果判断错了，请提交申诉，我们核实后会恢复。")}</p>
    ${st.service_block === "suspected" ? (st.appealed ? `<p class="muted small">${t("申诉已提交，核实后处理")}</p>`
      : `<textarea id="ag-text" rows="3" maxlength="500" placeholder="${esc(t("说明一下情况（比如你的真实年龄、刚才说的是别人），我们核实后会处理。"))}"></textarea>
         <div class="row"><button class="ghost small" id="ag-appeal">${t("提交申诉")}</button></div>`) : ""}
    <div class="row"><span class="grow"></span><button class="link small" id="ag-logout">${t("退出登录")}</button></div></div>`;
  document.body.appendChild(el);
  $("#ag-logout", el).onclick = () => bus.emit("logout");
  $("#ag-appeal", el)?.addEventListener("click", async () => {
    const content = $("#ag-text", el).value.trim();
    if (content.length < 2) return toast("写一句说明吧");
    try { await api("/api/guard/appeal", { body: { content } }); await refreshGuard(); el.remove(); apply(); } catch (e) { fail(e); }
  });
}

// ---------- 未成年人：时间到了 / 夜里 ----------
function lock() {
  $("#guard-lock")?.remove();
  const st = G.st, el = document.createElement("div");
  el.id = "guard-lock"; el.className = "guard-cover";
  const why = st.curfew_now ? t("现在是休息时间（{a}:00–{b}:00），早点睡吧，明天再来。", { a: st.curfew_hours[0], b: st.curfew_hours[1] })
    : t("今天的使用时间（{n} 分钟）到了，去做点别的吧，明天再来。", { n: st.limits.daily });
  el.innerHTML = `<div class="guard-card"><h2>${t("今天先到这里")}</h2><p>${esc(why)}</p>
    <div class="row">${st.has_pin ? `<button class="ghost small" id="l-guardian">${t("监护人设置")}</button>` : ""}<span class="grow"></span>
    <button class="link small" id="l-logout">${t("退出登录")}</button></div></div>`;
  document.body.appendChild(el);
  $("#l-logout", el).onclick = () => bus.emit("logout");
  $("#l-guardian", el)?.addEventListener("click", () => guardianPanel());
}

// ---------- 心跳和提醒 ----------
const today = () => new Date().toISOString().slice(0, 10);
function once(key) {  // 每个提醒一天只弹一次（同一个门槛）
  const k = `krino_remind_${today()}_${key}`;
  if (storeGet(k)) return false;
  storeSet(k, "1"); return true;
}

function remind(st) {
  const r = st.reminders || {}, streak = st.streak_minutes;
  if (r.long_use && streak >= r.long_use && once(`long${Math.floor(streak / r.long_use)}`)) {
    modal("休息一下", `<p>${t("你已经连续使用 {h} 小时了。站起来走走、喝点水、看看远处，过会儿再来。", { h: Math.floor(streak / 60) })}</p>`, null, { okText: "好的", cancel: false });
  } else if (r.reality && streak >= r.reality && once(`real${Math.floor(streak / r.reality)}`)) {
    modal("提醒", `<p>${t("你已经聊了 {m} 分钟了。她是 AI，现实里的朋友和家人也在等你。起来活动一下吧。", { m: streak })}</p>`, null, { okText: "知道了", cancel: false });
  }
  if (r.dependence && (st.used_minutes >= r.dependence.day || st.avg7_minutes >= r.dependence.avg) && once("dep")) {
    modal("注意别太依赖", `<p>${t("你最近花在这里的时间挺多的（今天 {d} 分钟，最近一周平均每天 {a} 分钟）。她是 AI，不能代替现实里的人。多和朋友、家人待一会儿吧；如果最近心情不好，也可以找信任的人或专业的人聊聊。", { d: st.used_minutes, a: st.avg7_minutes })}</p>`, null, { okText: "知道了", cancel: false });
  }
  if (st.minor && st.remaining_minutes !== null && st.remaining_minutes <= 5 && st.remaining_minutes > 0 && once("left5")) {
    toast(t("今天还能用 {n} 分钟", { n: st.remaining_minutes }), 5000);
  }
}

async function ping() {
  if (document.hidden || !S.token || !S.me) return;
  try {
    G.st = await api("/api/guard/ping", { body: { tz: -new Date().getTimezoneOffset() } });
    apply(); if (!G.st.needs.length) remind(G.st);
  } catch { /* 网络断了：下一分钟再说 */ }
}

export function startGuard() {
  clearInterval(G.timer);
  G.timer = setInterval(ping, 60_000);
  refreshGuard().then(() => ping());
}
bus.on("logout", () => { clearInterval(G.timer); G.st = null; $("#guard-gate")?.remove(); $("#guard-lock")?.remove(); });
bus.on("guard:refresh", () => refreshGuard());

// ---------- 聊天里的行为 ----------
export function helpCard(a) {  // 危机时：求助电话（可以直接点着拨号）
  const div = document.createElement("div");
  div.className = "help-card";
  div.innerHTML = `<b>${t(a.kind === "fraud" ? "遇到诈骗或损失，请马上求助" : "你不是一个人，现在就可以找人帮你")}</b>
    ${a.lines.map(([who, num]) => `<div class="row"><span>${esc(t(who))}</span><a href="tel:${esc(num.split(" ")[0].replace(/[^\d]/g, ""))}">${esc(num)}</a></div>`).join("")}`;
  $("#messages")?.appendChild(div);
  div.scrollIntoView({ block: "end", behavior: "smooth" });
}

export async function minorNotice() {
  await refreshGuard();
  if (G.st?.service_block) return null;  // 国际站：直接挡住（ageBlock），不再弹未成年人模式的说明
  const ok = await modal("已切换到未成年人模式", `<p>${t("从刚才的聊天看，你可能还未满 18 周岁，已经为你打开未成年人模式：她只会以朋友的身份陪你，每天的使用时间和夜间使用会受到限制。")}</p>
    <p class="muted small">${t("如果判断错了，可以在“设置 → 未成年人模式”里申诉，我们核实后会帮你恢复。")}</p>`, null, { okText: "知道了", cancel: false });
  return ok;
}

// ---------- 设置页 ----------
export async function settingsSections(host) {
  const st = G.st || (await refreshGuard());
  if (!st || !host) return;
  const cn = st.edition === "cn";
  if (!cn) { host.innerHTML = ""; return; }  // 国际站：没有未成年人模式、聊天记录和投诉这几块
  const reason = { age: t("你未满 18 周岁，未成年人模式一直开着。"), detected: t("系统判断你可能未满 18 周岁，已打开未成年人模式。"),
    voluntary: t("你自己打开了未成年人模式。") }[st.minor_reason] || t("没有开启。");
  host.innerHTML = `
    <div class="section-title mono">MINOR · ${t("未成年人模式")}</div>
    <p class="muted small">${esc(reason)} ${st.minor ? esc(t("今天已用 {u} / {d} 分钟；{a}:00–{b}:00 不能使用。", { u: st.used_minutes, d: st.limits.daily, a: st.curfew_hours[0], b: st.curfew_hours[1] })) : ""}</p>
    <div class="row">
      ${st.minor_reason === null || st.minor_reason === "voluntary" ? `<button class="ghost small" id="m-toggle">${t(st.minor ? "关闭未成年人模式" : "打开未成年人模式")}</button>` : ""}
      ${st.has_pin ? `<button class="ghost small" id="m-guardian">${t("监护人设置")}</button>` : st.minor ? `<button class="ghost small" id="m-add-guardian">${t("添加监护人")}</button>` : ""}
      ${st.suspected && !st.appealed ? `<button class="link small" id="m-appeal">${t("判断错了？申诉")}</button>` : ""}
      ${st.appealed ? `<span class="muted small">${t("申诉已提交，核实后处理")}</span>` : ""}
    </div>
    ${cn ? `<div class="section-title mono">CHATS · ${t("聊天记录")}</div>
    <div class="row"><button class="ghost small" id="c-export">${t("导出全部聊天记录")}</button><button class="link small danger-link" id="c-delete">${t("删除全部聊天记录")}</button></div>
    <div class="section-title mono">FEEDBACK · ${t("投诉与反馈")}</div>
    <div id="r-box"><p class="muted small">${t("加载中…")}</p></div>` : ""}`;
  $("#m-toggle", host)?.addEventListener("click", async () => {
    try { G.st = await api("/api/guard/minor-mode", { body: { on: !st.minor } }); apply(); settingsSections(host); } catch (e) { fail(e); }
  });
  $("#m-guardian", host)?.addEventListener("click", () => guardianPanel());
  $("#m-add-guardian", host)?.addEventListener("click", () => addGuardian(host));
  $("#m-appeal", host)?.addEventListener("click", async () => {
    const text = await modal("申诉", `<p class="muted small">${t("说明一下情况（比如你的真实年龄、刚才说的是别人），我们核实后会处理。")}</p><textarea id="ap-text" rows="3" maxlength="500"></textarea>`,
      (b) => $("#ap-text", b).value.trim() || false, { okText: "提交" });
    if (!text) return;
    try { await api("/api/guard/appeal", { body: { content: text } }); toast("已提交"); await refreshGuard(); settingsSections(host); } catch (e) { fail(e); }
  });
  if (cn) {
    $("#c-export", host).onclick = async () => {
      try {
        const res = await api("/api/me/chats/export", { raw: true });
        const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await res.blob()), download: "krino-chats.json" });
        a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      } catch (e) { fail(e); }
    };
    $("#c-delete", host).onclick = async () => {
      if (!(await confirmBox("删除全部聊天记录", `<p>${t("所有角色的全部对话都会删除，不能恢复。她记得的事不受影响（在“她记得的”里管理）。")}</p>`, "全部删除"))) return;
      try { const r = await api("/api/me/chats", { method: "DELETE" }); toast(t("删除了 {n} 段对话", { n: r.sessions })); bus.emit("character"); } catch (e) { fail(e); }
    };
    reportsBox($("#r-box", host));
  }
}

async function addGuardian(host) {
  const ok = await modal("添加监护人", `<p class="muted small">${t("请监护人来填，并设置一个监护人密码（4–6 位数字），用来查看使用情况、调整限制。")}</p>
    <div class="row"><input id="ag-name" maxlength="20" placeholder="${esc(t("监护人姓名"))}"><input id="ag-phone" maxlength="20" inputmode="tel" placeholder="${esc(t("监护人电话"))}"></div>
    <label>${t("监护人密码")}<input id="ag-pin" type="password" inputmode="numeric" maxlength="6"></label>
    <label class="check"><input type="checkbox" id="ag-consent"> ${t("我是监护人，同意孩子在未成年人模式下使用")}</label>`,
  async (b) => {
    try {
      G.st = await api("/api/guard/profile", { body: { guardian: { name: $("#ag-name", b).value, phone: $("#ag-phone", b).value },
        guardian_consent: $("#ag-consent", b).checked, pin: $("#ag-pin", b).value } });
      return true;
    } catch (e) { fail(e); return false; }
  }, { okText: "保存" });
  if (ok) settingsSections(host);
}

async function guardianPanel() {
  const pin = await modal("监护人", `<label>${t("监护人密码")}<input id="gp-pin" type="password" inputmode="numeric" maxlength="6" autofocus></label>`,
    (b) => $("#gp-pin", b).value || false, { okText: "进入" });
  if (!pin) return;
  let ov;
  try { ov = await api("/api/guard/guardian/overview", { body: { pin } }); } catch (e) { return fail(e); }
  const st = ov.status, max = Math.max(30, ...ov.usage.map((u) => u.minutes));
  const RISK = { self_harm: t("流露过轻生或自伤的念头"), fraud: t("提到被骗或钱财损失") };
  const saved = await modal("监护人设置", `
    <div class="section-title mono">${t("最近 7 天的使用时长（分钟）")}</div>
    <div class="usage-bars">${ov.usage.map((u) => `<div title="${u.day}"><i style="height:${Math.round((u.minutes / max) * 100)}%"></i><b>${u.minutes}</b><span>${u.day.slice(5)}</span></div>`).join("")}</div>
    <div class="section-title mono">${t("聊过的角色（最近 7 天，只看次数，不看内容）")}</div>
    <p class="small">${ov.characters.length ? ov.characters.map((c) => `${esc(c.name)} · ${c.messages}`).join("　") : t("没有")}</p>
    <div class="section-title mono">${t("风险提醒（最近 30 天）")}</div>
    <p class="small">${ov.risks.length ? ov.risks.map((r) => `${fmtTime(r.at)} ${esc(RISK[r.kind] || r.kind)}`).join("<br>") : t("没有")}</p>
    <div class="section-title mono">${t("限制")}</div>
    <label>${t("每天最多用多少分钟（0–180）")}<input type="number" id="gs-daily" min="0" max="180" value="${st.limits.daily}"></label>
    <label class="check"><input type="checkbox" id="gs-curfew" ${st.limits.curfew ? "checked" : ""}> ${t("{a}:00–{b}:00 不能使用", { a: st.curfew_hours[0], b: st.curfew_hours[1] })}</label>
    <div class="section-title mono">${t("屏蔽角色（勾上的不能聊）")}</div>
    ${ov.all_characters.map((c) => `<label class="check"><input type="checkbox" data-block="${esc(c.id)}" ${st.blocked.includes(c.id) ? "checked" : ""}> ${esc(c.name)}</label>`).join("")}
    <p class="muted small">${t("这个产品目前没有充值和付费功能。")}</p>`,
  async (b) => {
    try {
      G.st = await api("/api/guard/guardian/settings", { body: { pin, daily: +$("#gs-daily", b).value, curfew: $("#gs-curfew", b).checked,
        blocked: $$("[data-block]", b).filter((x) => x.checked).map((x) => x.dataset.block) } });
      return true;
    } catch (e) { fail(e); return false; }
  }, { okText: "保存", wide: true });
  if (saved) { apply(); toast("已保存"); }
}

const KINDS = [["content", "内容有问题"], ["service", "服务问题"], ["privacy", "隐私和个人信息"], ["other", "其他"]];
async function reportsBox(box, messageId = null) {
  if (!box) return;
  let data;
  try { data = await api("/api/reports"); } catch (e) { box.innerHTML = `<p class="muted small">${esc(tr(e.message))}</p>`; return; }
  box.innerHTML = `<p class="muted small">${t("投诉、举报、意见都可以在这里提，我们会在 {n} 个工作日内处理并在这里答复。", { n: data.reply_days })}</p>
    <div class="row"><button class="ghost small" id="r-new">${t("提交投诉或举报")}</button></div>
    ${data.reports.length ? `<div class="key-list">${data.reports.map((r) => `<div class="key-row"><div><b>${esc(t(KINDS.find((k) => k[0] === r.kind)?.[1] || "申诉"))}</b> <span class="muted small">${fmtTime(r.created_at)}</span>
      <div class="small">${esc(r.content)}</div>${r.reply ? `<div class="small report-reply">${t("答复：")}${esc(r.reply)}</div>` : `<div class="muted small">${t("处理中")}</div>`}</div></div>`).join("")}</div>` : ""}`;
  $("#r-new", box).onclick = () => reportForm(null).then((ok) => ok && reportsBox(box));
}

export async function reportForm(messageId) {
  return modal(messageId ? "举报这条回复" : "投诉与举报", `
    <label>${t("类型")}<select id="rp-kind">${KINDS.map(([k, l]) => `<option value="${k}">${esc(t(l))}</option>`).join("")}</select></label>
    <label>${t("说明")}<textarea id="rp-text" rows="4" maxlength="1000" placeholder="${esc(t("发生了什么？越具体越好"))}"></textarea></label>`,
  async (b) => {
    const content = $("#rp-text", b).value.trim();
    if (content.length < 2) { toast("写一句说明吧"); return false; }
    try { const r = await api("/api/reports", { body: { kind: $("#rp-kind", b).value, content, message_id: messageId } });
      toast(t("已提交，我们会在 {n} 个工作日内答复（设置 → 投诉与反馈）", { n: r.reply_days }), 5000); return true; }
    catch (e) { fail(e); return false; }
  }, { okText: "提交" });
}
