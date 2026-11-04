// 检查海外版翻译：列出代码里用到、但 app/frontend/i18n/en.json 还没有英文的中文句子，以及表里已经没人用的条目。
//   node scripts/i18n_check.mjs          # 有缺失时退出码为 1
// 不依赖任何包。规则见 app/frontend/i18n/README.md：中文原文就是键，{x} 是占位。
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const FE = join(ROOT, "app/frontend");
const BE = join(ROOT, "app/backend/app");
const CJK = /[一-鿿]/;
const dict = JSON.parse(readFileSync(join(FE, "i18n/en.json"), "utf8"));

const used = new Map();  // 键 → 出处
const add = (k, where) => { if (k && CJK.test(k) && !used.has(k)) used.set(k, where); };
const unq = (s) => s.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\'/g, "'");
const STR = String.raw`"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'`;

// ---------- 前端 ----------
const html = readFileSync(join(FE, "index.html"), "utf8");
for (const m of html.matchAll(/<([a-z0-9]+)([^>]*\sdata-i18n(?:-ph|-title)?[^>]*)>([^<]*)/g)) {
  const attrs = m[2];
  if (/\sdata-i18n(\s|>|$)/.test(attrs + " ")) add(m[3].trim(), "index.html");
  if (/data-i18n-ph/.test(attrs)) add((/placeholder="([^"]*)"/.exec(attrs) || [])[1], "index.html");
  if (/data-i18n-title/.test(attrs)) add((/title="([^"]*)"/.exec(attrs) || [])[1], "index.html");
}
const jsFiles = readdirSync(join(FE, "js")).filter((f) => f.endsWith(".js") && f !== "i18n.js");
for (const f of jsFiles) {
  const src = readFileSync(join(FE, "js", f), "utf8").replace(/^\s*\/\/.*$/gm, "");
  // t("…")、tr("…")，以及会自动经过 tr() 的 toast / modal / confirmBox / okText
  for (const re of [new RegExp(String.raw`\bt\(\s*(?:${STR})`, "g"),
                    new RegExp(String.raw`\b(?:toast|modal|confirmBox)\(\s*(?:${STR})`, "g"),
                    new RegExp(String.raw`okText:\s*(?:${STR})`, "g"),
                    new RegExp(String.raw`confirmBox\([^;]*?,\s*(?:${STR})\)`, "g")]) {
    for (const m of src.matchAll(re)) add(unq(m[1] ?? m[2]), f);
  }
  // 三元表达式里交给 toast / modal 的两个分支：toast(a ? "x" : "y")
  for (const m of src.matchAll(new RegExp(String.raw`\b(?:toast|modal)\([^()]*?\?\s*(?:${STR})\s*:\s*(?:${STR})`, "g")))
    [m[1] ?? m[2], m[3] ?? m[4]].forEach((x) => add(unq(x), f));
  // t({ a: "x", … }[k]) 这种对照表，和标签常量（*_ZH、GESTURES、MAIN_FIELDS、PORTRAITS、caps 列表、排序 chips）
  for (const m of src.matchAll(/(?:t\(\{|_ZH = \{|GESTURES = |MAIN_FIELDS = |PORTRAITS = |\[\["camera"|\[\["hot"|\[\["", "全部"\]|sec\(|label: )([\s\S]{0,1200}?)(?:\}\[|\];|\}\);|\)\}|\n\n)/g))
    for (const s of m[1].matchAll(new RegExp(STR, "g"))) add(unq(s[1] ?? s[2]), f);
}

// ---------- 后端：返回给用户的报错 ----------
const backend = new Map();
const errRe = /(?:HTTPException\(\s*\d+\s*,|(?:PersonaError|WorkshopError|MemoryError_|ServiceError|LLMError|RuntimeError|ValueError)\()\s*(f?)"((?:[^"\\]|\\.)*)"/g;
for (const f of readdirSync(BE).filter((x) => x.endsWith(".py"))) {
  const src = readFileSync(join(BE, f), "utf8");
  for (const m of src.matchAll(errRe)) {
    if (!CJK.test(m[2])) continue;
    // f-string 的 {表达式} 统一换成 {x}，和表里的占位对齐（占位名不重要）
    const key = m[1] ? m[2].replace(/\{[^{}]+\}/g, "{x}") : m[2];
    backend.set(key, f);
  }
}
const asPattern = (k) => new RegExp("^" + k.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\\\{x\\\}|\{\w+\}/g, ".+?") + "$", "s");
const dictPatterns = Object.keys(dict).filter((k) => k.includes("{")).map((k) => [k, asPattern(k)]);
const covered = (k) => k in dict || dictPatterns.some(([, re]) => re.test(k)) ||
  // 后端 f-string：表里有同样结构（占位名不同）的条目也算
  (k.includes("{x}") && Object.keys(dict).some((d) => d.replace(/\{\w+\}/g, "{x}") === k));

const missingFe = [...used].filter(([k]) => !covered(k));
const missingBe = [...backend].filter(([k]) => !covered(k));
const allUsed = new Set([...used.keys(), ...backend.keys()]);
const unused = Object.keys(dict).filter((k) => !allUsed.has(k) && ![...allUsed].some((u) => u.replace(/\{\w+\}/g, "{x}") === k.replace(/\{\w+\}/g, "{x}")));

console.log(`en.json：${Object.keys(dict).length} 条；前端用到 ${used.size} 句，后端报错 ${backend.size} 句`);
if (missingFe.length) { console.log(`\n前端缺英文（${missingFe.length}）：`); missingFe.forEach(([k, f]) => console.log(`  ${f}: ${JSON.stringify(k)}`)); }
if (missingBe.length) { console.log(`\n后端报错缺英文（${missingBe.length}）：`); missingBe.forEach(([k, f]) => console.log(`  ${f}: ${JSON.stringify(k)}`)); }
if (unused.length) console.log(`\n表里没人用（${unused.length}，可能是后端返回的标签，确认后再删）：\n  ` + unused.slice(0, 40).map((k) => JSON.stringify(k)).join("\n  "));
if (!missingFe.length && !missingBe.length) console.log("\n✓ 没有缺失");
process.exit(missingFe.length || missingBe.length ? 1 : 0);
