// 给镜片页面（/device）用的一小组桌面能力。只暴露这几个函数，页面拿不到 Node 和文件系统。
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("krinoDesktop", {
  platform: process.platform,
  setInteractive: (on) => ipcRenderer.send("interactive", !!on),       // 鼠标在工具栏 / 字幕上时接鼠标，其余地方点穿
  openLogin: () => ipcRenderer.send("open-login"),                       // 打开 KRINO WORLD 登录窗口（登录状态和镜片共用）
  onCommand: (fn) => ipcRenderer.on("command", (_e, cmd) => fn(cmd)),   // 全局快捷键、托盘菜单
  onCursorPose: (fn) => ipcRenderer.on("cursor-pose", (_e, p) => fn(p)), // “用鼠标位置当头部朝向”
});
