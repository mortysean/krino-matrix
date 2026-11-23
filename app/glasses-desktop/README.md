# KRINO GLASSES 桌面测试版（Windows）

一个透明、无边框、置顶的小窗口当作眼镜镜片：她站在你的桌面上，字幕和面板浮在旁边；没画东西的地方鼠标点穿到下面的程序。
它接入 KRINO WORLD 的眼镜设备协议（`/api/devices/ws`，设备类型 `glasses-desktop`），用电脑的麦克风、摄像头、扬声器当眼镜的输入输出。
真机眼镜做出来之前，用它测试眼镜这条链路：说话 → 她回答（字幕边生成边出、朗读、口型）→ 转头时她留在原地 → 不在视野里时走到你眼前。

窗口里加载的是服务器上的 `/device` 页面（`app/frontend/device.html` + `js/device.js`，和设置页里的浏览器模拟器共用 `js/glassesclient.js`），
所以页面改动部署到服务器就生效，不用重新打包。这个外壳只负责桌面那部分：窗口、点穿、全局快捷键、托盘、权限、登录窗口。

## 使用

1. 解压 `KRINO-GLASSES-win32-x64.zip`，运行 `KRINO GLASSES.exe`。
2. 第一次打开选服务器（国内版 / 海外版 / 本机开发服务器 / 其他地址）。之后托盘菜单“服务器地址…”可以改。
3. 点“登录”，在弹出的 KRINO WORLD 窗口里登录；登录状态和镜片共用，关掉登录窗口镜片就连上了。
4. 底部工具栏：选角色 · 打字说话 · 麦克风（点一下说、再点一下说完）· 语音对话（免按键，随时开口打断）· 眼睛（拍一帧摄像头给她看）· 定位针（把她放在你正看着的地方）· 扬声器开关。

| 快捷键（全局） | |
| --- | --- |
| Ctrl+Alt+Space | 说一句（再按一次说完） |
| Ctrl+Alt+V | 语音对话 开 / 关 |
| Ctrl+Alt+← → ↑ ↓ | 转头（窗口有焦点时直接按方向键） |
| Ctrl+Alt+0 | 回正 |
| Ctrl+Alt+P | 把她放在正看着的地方（窗口有焦点时按 P） |
| Ctrl+Alt+H | 显示 / 隐藏镜片 |

托盘菜单里可以打开“用鼠标位置当头部朝向”：整块屏幕当作你眼前，鼠标在哪就是在看哪。

摄像头、麦克风只允许服务器上的页面使用；拍给她看要先在网站“设置 → 隐私”里允许摄像头。页面拿不到 Node 和文件系统（`contextIsolation` + `sandbox`，只暴露 `preload.js` 里的几个函数）。

启动参数（可选）：`--server=https://…/products/world/` 直接连这个地址；`--profile=目录` 用另一份配置和登录状态（同时开两副眼镜测试）。

## 服务器要求

服务器需要有这一版的 `/device` 页面和设备协议（`glasses-desktop` 设备类型、`delta` 流式字幕、`anchor.set`）。
没部署时窗口会提示“不是眼镜页面”，并打开服务器设置。本机测试：`LLM_PROVIDER=mock scripts/world.sh start`，服务器选“本机开发服务器”。

## 开发与打包

```bash
cd app/glasses-desktop
npm install                 # 网络要走代理时：NODE_USE_ENV_PROXY=1 npm install
npm start                   # 在本机（Linux / Windows）直接跑
npm run pack:win            # 打 Windows x64 包到 dist/（Linux 上也能打）
```

在 Linux 上打的包，exe 文件图标是 Electron 默认的（改图标要 Wine + rcedit）；窗口和托盘用的是 `assets/` 里的 KRINO 图标。
