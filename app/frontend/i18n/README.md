# 界面翻译

做法和 gettext 一样：**中文原文就是键**。代码里写 `t("新话题")`，国内版原样显示，海外版查 `en.json` 里 `"新话题": "New topic"`。

- 带变量的句子用 `{名字}` 占位：`t("和 {name} 打个招呼", { name })` ↔ `"Say hi to {name}"`。
- HTML 里的静态文字加 `data-i18n`（文字）、`data-i18n-ph`（placeholder）、`data-i18n-title`（title），启动时自动翻译。
- 后端返回的错误信息（`detail`）在海外版由服务端按同一张表翻译（`app/backend/app/i18n.py`）；带变量的报错用 `{x}` 占位写一条即可匹配。
- 没翻译的句子会原样显示中文。`node scripts/i18n_check.mjs` 列出还缺英文的句子。
