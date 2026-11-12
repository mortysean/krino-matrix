// 从长期科技树V3.html 抽出数据对象（只执行到数据定义为止，DOM 全部用空桩）。用法：node extract_v3.js 长期科技树V3.html 输出.json
// 抽出来后由 build 用的 data/tree/v3.zh.json 只保留数据字段；V3 更新时重跑本脚本再覆盖。
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
