// KRINO GLASSES 桌面测试版（Windows）。一个透明、无边框、置顶的窗口当作眼镜镜片，加载服务器上的 /device 页面：
// 她站在你的桌面上，字幕和面板浮在旁边；没画东西的地方鼠标点穿到下面的程序。设备协议、AR 显示、朗读都在页面里
// （app/frontend/js/device.js + glassesclient.js），这里只做桌面那部分：窗口、点穿、全局快捷键、托盘、权限、登录窗口。
//
//   Ctrl+Alt+Space  说一句（再按一次说完）      Ctrl+Alt+V  语音对话（免按键，随时打断她）
//   Ctrl+Alt+←→↑↓   转头                         Ctrl+Alt+0  回正        Ctrl+Alt+P  把她放在正看着的地方
//   Ctrl+Alt+H      显示 / 隐藏镜片
// 启动参数（可选）：--server=https://…/products/world/ 直接连这个地址；--profile=目录 用另一份配置和登录状态（同时开两副眼镜测试）
const { app, BrowserWindow, Menu, Tray, globalShortcut, ipcMain, nativeImage, screen, session, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");

const arg = (name) => process.argv.find((a) => a.startsWith(`--${name}=`))?.slice(name.length + 3);
if (arg("profile")) app.setPath("userData", path.resolve(arg("profile")));
const CONFIG = path.join(app.getPath("userData"), "config.json");
const ICON = path.join(__dirname, "assets", "icon.png");
let cfg = { server: "", mousePose: false, onTop: true, bounds: null };
try { cfg = { ...cfg, ...JSON.parse(fs.readFileSync(CONFIG, "utf8")) }; } catch { /* 第一次打开 */ }
if (arg("server")) cfg.server = arg("server").replace(/\/?$/, "/");
const save = () => { try { fs.mkdirSync(path.dirname(CONFIG), { recursive: true }); fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2)); } catch { /* 写不了也能用 */ } };

let lens = null, login = null, setup = null, tray = null, poseTimer = null;
const origin = () => { try { return new URL(cfg.server).origin; } catch { return ""; } };
const fromServer = (u) => { try { return new URL(u).origin === origin(); } catch { return false; } };

if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => { lens?.show(); lens?.focus(); });

// ---------- 镜片 ----------
function createLens() {
  const wa = screen.getPrimaryDisplay().workArea;
  const b = cfg.bounds || { width: 380, height: 600, x: wa.x + wa.width - 400, y: wa.y + wa.height - 620 };
  lens = new BrowserWindow({
    ...b, minWidth: 300, minHeight: 360, frame: false, transparent: true, hasShadow: false, resizable: true,
    alwaysOnTop: cfg.onTop, skipTaskbar: false, title: "KRINO GLASSES", icon: ICON, backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, nodeIntegration: false, sandbox: true, backgroundThrottling: false },
  });
  if (cfg.onTop) lens.setAlwaysOnTop(true, "floating");
  lens.setIgnoreMouseEvents(true, { forward: true });  // 默认点穿；页面在鼠标移到工具栏上时再要回鼠标
  const keep = () => { if (!lens.isDestroyed()) { cfg.bounds = lens.getBounds(); save(); } };
  lens.on("moved", keep); lens.on("resized", keep);
  lens.on("closed", () => { lens = null; app.quit(); });
  lens.webContents.setWindowOpenHandler(({ url }) => { openExternal(url); return { action: "deny" }; });
  lens.webContents.on("will-navigate", (e, url) => { if (!fromServer(url)) { e.preventDefault(); openExternal(url); } });
  lens.webContents.on("did-fail-load", (_e, code, desc, url, isMain) => {
    if (isMain && code !== -3) openSetup(`连不上 ${cfg.server}（${desc}）`);
  });
  lens.webContents.on("did-finish-load", () => {
    // 服务器还没有 /device 页面（没部署新版本）时会是 404 的 JSON
    lens.webContents.executeJavaScript("document.body?.classList.contains('device') || false").then((ok) => {
      if (!ok) openSetup(`${cfg.server}device 不是眼镜页面：服务器可能还没部署眼镜桌面版这一版`);
    }).catch(() => {});
  });
  lens.loadURL(cfg.server + "device");
}

function openExternal(url) { if (/^https?:/.test(url)) shell.openExternal(url); }

// ---------- 第一次打开 / 换服务器 ----------
function openSetup(error = "") {
  if (setup) { setup.focus(); return; }
  setup = new BrowserWindow({ width: 460, height: 430, resizable: false, title: "KRINO GLASSES", icon: ICON, autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, sandbox: true } });
  setup.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith("krino-setup://save")) return;
    e.preventDefault();
    cfg.server = new URL(url).searchParams.get("server");
    save();
    setup.close();
    if (lens) lens.loadURL(cfg.server + "device"); else createLens();
  });
  setup.on("closed", () => { setup = null; if (!cfg.server) app.quit(); });
  setup.loadFile(path.join(__dirname, "setup.html"), { query: { server: cfg.server || "", error } });
}

// ---------- 登录：开一个普通窗口打开 KRINO WORLD，登录状态和镜片共用，镜片自己会刷新 ----------
function openLogin() {
  if (login) { login.focus(); return; }
  login = new BrowserWindow({ width: 1100, height: 760, title: "KRINO WORLD", icon: ICON, autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, sandbox: true } });
  login.webContents.setWindowOpenHandler(({ url }) => { openExternal(url); return { action: "deny" }; });
  login.on("closed", () => { login = null; lens?.reload(); });
  login.loadURL(cfg.server);
}

// ---------- 用鼠标位置当头部朝向：屏幕就是你眼前，鼠标在哪你就在看哪 ----------
function setMousePose(on) {
  cfg.mousePose = on; save();
  clearInterval(poseTimer); poseTimer = null;
  if (!on) { lens?.webContents.send("cursor-pose", { yaw: 0, pitch: 0 }); return; }
  let last = "";
  poseTimer = setInterval(() => {
    if (!lens) return;
    const p = screen.getCursorScreenPoint(), d = screen.getDisplayNearestPoint(p).bounds;
    const pose = { yaw: Math.round(((p.x - d.x) / d.width - 0.5) * 100), pitch: Math.round(-((p.y - d.y) / d.height - 0.5) * 50) };
    const k = pose.yaw + "," + pose.pitch;
    if (k !== last) { last = k; lens.webContents.send("cursor-pose", pose); }
  }, 50);
}

// ---------- 托盘、快捷键 ----------
const command = (cmd) => lens?.webContents.send("command", cmd);
function toggleLens() { if (!lens) return; lens.isVisible() ? lens.hide() : lens.showInactive(); buildTray(); }

function buildTray() {
  tray ||= new Tray(nativeImage.createFromPath(path.join(__dirname, "assets", "tray.png")));
  tray.setToolTip("KRINO GLASSES");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: lens?.isVisible() ? "隐藏镜片\tCtrl+Alt+H" : "显示镜片\tCtrl+Alt+H", click: toggleLens },
    { label: "置顶", type: "checkbox", checked: cfg.onTop, click: (i) => { cfg.onTop = i.checked; save(); lens?.setAlwaysOnTop(i.checked, "floating"); } },
    { label: "用鼠标位置当头部朝向", type: "checkbox", checked: cfg.mousePose, click: (i) => setMousePose(i.checked) },
    { type: "separator" },
    { label: "说一句\tCtrl+Alt+Space", click: () => command("mic") },
    { label: "语音对话\tCtrl+Alt+V", click: () => command("voice") },
    { label: "把她放在正看着的地方\tCtrl+Alt+P", click: () => command("place") },
    { label: "回正\tCtrl+Alt+0", click: () => command("center") },
    { type: "separator" },
    { label: "登录 / 打开 KRINO WORLD", click: openLogin },
    { label: "服务器地址…", click: () => openSetup() },
    { label: "刷新", click: () => lens?.reload() },
    { label: "开发者工具", click: () => lens?.webContents.openDevTools({ mode: "detach" }) },
    { type: "separator" },
    { label: "退出", click: () => app.quit() },
  ]));
  tray.on("click", toggleLens);
}

function shortcuts() {
  const keys = {
    "CommandOrControl+Alt+Space": "mic", "CommandOrControl+Alt+V": "voice", "CommandOrControl+Alt+P": "place", "CommandOrControl+Alt+0": "center",
    "CommandOrControl+Alt+Left": "turn-left", "CommandOrControl+Alt+Right": "turn-right", "CommandOrControl+Alt+Up": "look-up", "CommandOrControl+Alt+Down": "look-down",
  };
  for (const [k, cmd] of Object.entries(keys)) globalShortcut.register(k, () => command(cmd));  // 被别的程序占了就算了
  globalShortcut.register("CommandOrControl+Alt+H", toggleLens);
}

// 摄像头、麦克风只给自己的服务器页面
function permissions() {
  const ok = (perm, url) => ["media", "audioCapture", "videoCapture", "speaker-selection"].includes(perm) && fromServer(url);
  session.defaultSession.setPermissionRequestHandler((wc, perm, cb, details) => cb(ok(perm, details.requestingUrl || wc.getURL())));
  session.defaultSession.setPermissionCheckHandler((wc, perm, requestingOrigin) => ok(perm, requestingOrigin || wc?.getURL() || ""));
}

ipcMain.on("interactive", (e, on) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (w === lens) lens.setIgnoreMouseEvents(!on, { forward: true });
});
ipcMain.on("open-login", openLogin);

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  app.setAppUserModelId("com.krino.glasses");
  permissions();
  buildTray();
  shortcuts();
  if (cfg.server) createLens(); else openSetup();
  if (cfg.mousePose) setMousePose(true);
});
app.on("will-quit", () => globalShortcut.unregisterAll());
app.on("window-all-closed", () => { if (!lens) app.quit(); });
