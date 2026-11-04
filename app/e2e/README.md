# 浏览器端到端测试

对着一个**已经启动**的 KRINO WORLD 跑主要流程（注册 → 3D 形象 → 流式聊天 → 预设互动 → 语音切换 → 记忆 → 人格编辑影响表达 → 现实/虚构标注与删除 → 创意工坊发布浏览 → 眼镜模拟器 AR 事件 → 设置与策略测试 → 断网提示 → 窄屏），每步截图到 `shots/`。

```bash
LLM_PROVIDER=mock scripts/world.sh start     # 用离线模型，结果可重复
scripts/world.sh e2e                         # 首次会 npm install playwright-core
```

- 浏览器：默认用 Playwright 缓存里的 Chromium（`~/.cache/ms-playwright/chromium-*`），或设置 `CHROME=/path/to/chrome`。
- 没有 GPU 的机器用 SwiftShader 软件渲染 WebGL，3D 会慢但能跑；摄像头和麦克风用 Chromium 的假设备。
- Linux 上缺系统库（libnss3、libasound）或中文字体时，设置 `LD_LIBRARY_PATH` 和 `FONTCONFIG_FILE` 指向自备的库和字体。
