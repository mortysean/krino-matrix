// 从长期科技树的 HTML（docs/长期科技树V5(1).html 等）抽出数据对象（只执行到数据定义为止，DOM 全部用空桩）。
// 用法：node extract_tree.js 长期科技树V5.html 输出.json。build 用的 data/tree/nodes.zh.json 就是它的输出加上 _note / source；
// 出新版时重跑本脚本再覆盖，然后把改动的字段同步翻译进 nodes.en.json。
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[2], "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const stub = new Proxy(function () {}, { get: (t, k) => (k === Symbol.toPrimitive ? () => "" : stub), apply: () => stub, construct: () => stub });
const ctx = { document: stub, window: stub, addEventListener() {}, requestAnimationFrame() {}, setTimeout() {}, console, matchMedia: () => ({ matches: false, addEventListener() {} }) };
vm.createContext(ctx);
for (const s of scripts) { try { vm.runInContext(s, ctx); } catch (e) { console.error("script err:", e.message.slice(0, 120)); } }
const out = {};
for (const k of ["NODES", "SCI", "OPEN", "UNLOCK", "DUR", "TAGS", "MULTI", "MULTI_EDGES", "CLS_BADGE"]) out[k] = vm.runInContext(`typeof ${k} !== "undefined" ? ${k} : null`, ctx);
fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 1));
console.log(Object.fromEntries(Object.entries(out).map(([k, v]) => [k, v ? Object.keys(v).length : null])));
