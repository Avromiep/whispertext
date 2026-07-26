/**
 * WhisperText — Electron main process.
 * Owns: Python backend lifecycle, system tray, settings window, and the
 * transparent always-on-top recording overlay.
 */
const { app, BrowserWindow, Tray, Menu, ipcMain, shell, nativeImage, screen, Notification } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const http = require("http");
const net = require("net");
const { planBackendRestart } = require("./backend-supervisor.cjs");

const BACKEND_PORT = 43117;
const DEV = !!process.env.WT_DEV;
const DEV_URL = "http://localhost:5173";

let settingsWin = null;
let overlayWin = null;
let tray = null;
let backendProc = null;
let quitting = false;

// Windows shows this as the source name on desktop notifications and groups
// taskbar windows by it. Without it, renderer-fired Notifications are
// attributed to "electron.app.Electron". Packaged builds must match the NSIS
// shortcut's AppUserModelID (the electron-builder appId) so the shortcut's
// "WhisperText" display name is used; unpackaged dev has no shortcut, so a
// friendly literal is shown directly.
app.setAppUserModelId(app.isPackaged ? "com.whispertext.app" : "WhisperText");

// ---------------------------------------------------------------- single lock
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => showSettings());
}

// ------------------------------------------------------------------- backend
// The backend owns port 43117. An earlier version respawned it on every
// non-zero exit with no limit, and decided whether to spawn purely from a
// /health probe. When the port was already held — a second instance, or a dev
// server whose backend was still warming up (loading the Whisper model, so
// /health hadn't come up yet) — Electron spawned a fresh backend every few
// seconds forever, each one briefly installing and tearing down the global
// keyboard hook. Now we never spawn while something is already listening on
// the port (we adopt it), and cap consecutive failed restarts with backoff.
// The restart decision itself lives in backend-supervisor.cjs (unit-tested).
let backendRestarts = 0;
let backendStartedAt = 0;

// Anything listening on the port? A raw TCP connect is reliable even while the
// backend is warming up, unlike a /health request that needs the app ready.
function backendPortInUse(cb) {
  const socket = net.connect({ host: "127.0.0.1", port: BACKEND_PORT });
  let done = false;
  const finish = (inUse) => { if (!done) { done = true; socket.destroy(); cb(inUse); } };
  socket.setTimeout(1000);
  socket.on("connect", () => finish(true));
  socket.on("timeout", () => finish(false));
  socket.on("error", () => finish(false)); // ECONNREFUSED = nothing there
}

function spawnBackend() {
  let cmd, args, cwd;
  if (DEV || !app.isPackaged) {
    cwd = path.resolve(__dirname, "..", "..");
    cmd = path.join(cwd, ".venv", "Scripts", "python.exe");
    args = ["-m", "backend.app"];
  } else {
    cwd = path.join(process.resourcesPath, "backend");
    cmd = path.join(cwd, "whispertext-backend.exe");
    args = [];
  }
  if (!fs.existsSync(cmd)) {
    console.error("Backend executable not found:", cmd);
    return;
  }
  backendStartedAt = Date.now();
  backendProc = spawn(cmd, args, { cwd, stdio: "ignore", windowsHide: true });
  backendProc.on("exit", (code) => {
    const ranMs = Date.now() - backendStartedAt;
    backendProc = null;
    backendPortInUse((portInUse) => {
      const plan = planBackendRestart({ quitting, exitCode: code, ranMs,
                                        restarts: backendRestarts, portInUse });
      backendRestarts = plan.restarts;
      if (plan.action === "retry") {
        setTimeout(startBackend, plan.delayMs);
      } else if (plan.action === "giveup") {
        console.error("Backend keeps exiting without staying up; not retrying.");
        notifyBackendDown();
      }
      // "adopt" / "none": leave the running backend (or shutdown) as-is.
    });
  });
}

function startBackend() {
  if (backendProc) return;               // already managing a backend
  backendPortInUse((inUse) => {
    if (inUse) return;                    // adopt whatever already owns the port
    spawnBackend();
  });
}

function stopBackend() {
  if (backendProc) { backendProc.kill(); backendProc = null; }
}

function notifyBackendDown() {
  try {
    new Notification({
      title: "WhisperText",
      body: "The backend didn't start. Try restarting the app.",
    }).show();
  } catch { /* notifications unavailable */ }
}

// -------------------------------------------------------------------- windows
function pageUrl(page) {
  return DEV ? `${DEV_URL}/${page}` : `file://${path.join(__dirname, "..", "dist", page)}`;
}

function showSettings() {
  if (settingsWin && !settingsWin.isDestroyed()) {
    settingsWin.show(); settingsWin.focus(); return;
  }
  settingsWin = new BrowserWindow({
    width: 1080, height: 720, minWidth: 900, minHeight: 600,
    title: "WhisperText",
    icon: path.join(__dirname, "..", "assets", "icon.ico"),
    backgroundColor: "#f3ead9", // matches the default tan theme — avoids a color flash on launch
    autoHideMenuBar: true,
    show: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true },
  });
  settingsWin.loadURL(pageUrl("index.html"));
  settingsWin.once("ready-to-show", () => settingsWin.show());
  // Closing the window hides the app to tray — it keeps running.
  settingsWin.on("close", (e) => {
    if (!quitting) { e.preventDefault(); settingsWin.hide(); }
  });
}

function ensureOverlay() {
  if (!overlayWin || overlayWin.isDestroyed()) createOverlay();
  return overlayWin;
}

function createOverlay() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const W = 360, H = 120;
  overlayWin = new BrowserWindow({
    width: W, height: H,
    x: Math.round((width - W) / 2), y: height - H - 24,
    frame: false, transparent: true, resizable: false, movable: false,
    alwaysOnTop: true, skipTaskbar: true, focusable: false, show: false,
    hasShadow: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true },
  });
  overlayWin.setAlwaysOnTop(true, "screen-saver");
  overlayWin.setIgnoreMouseEvents(true);
  overlayWin.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWin.loadURL(pageUrl("overlay.html"));
  // A crashed or failed-to-load renderer leaves a live but blank window that
  // never reacts to the hotkey again. Reload it instead of leaving it stranded.
  overlayWin.webContents.on("render-process-gone", () => {
    if (!quitting && overlayWin && !overlayWin.isDestroyed()) overlayWin.reload();
  });
  overlayWin.webContents.on("did-fail-load", () => {
    if (!quitting && overlayWin && !overlayWin.isDestroyed()) {
      setTimeout(() => overlayWin?.loadURL(pageUrl("overlay.html")), 1000);
    }
  });
}

// ------------------------------------------------------------------------ IPC
ipcMain.on("overlay:show", () => {
  // Recreate on demand: a renderer crash would otherwise leave the overlay
  // permanently invisible while dictation kept working in the background.
  const win = ensureOverlay();
  if (win && !win.isDestroyed()) {
    win.showInactive();
    win.setAlwaysOnTop(true, "screen-saver"); // reassert over fullscreen apps
  }
});
ipcMain.on("overlay:hide", () => {
  if (overlayWin && !overlayWin.isDestroyed()) overlayWin.hide();
});
ipcMain.on("app:open-settings", () => showSettings());
ipcMain.handle("app:get-login-item", () => app.getLoginItemSettings().openAtLogin);
ipcMain.handle("app:set-login-item", (_e, enabled) => {
  app.setLoginItemSettings({ openAtLogin: enabled, path: process.execPath });
  return app.getLoginItemSettings().openAtLogin;
});
ipcMain.on("app:restart", () => { quitting = true; stopBackend(); app.relaunch(); app.exit(0); });
ipcMain.on("app:open-external", (_e, url) => {
  if (/^https?:\/\//.test(url)) shell.openExternal(url);
});
// --------------------------------------------------------------------- updates
// The whole flow lives in-app: check → download (progress streamed to the
// renderer) → "ready" → silent install + relaunch. No browser hand-off.
let updateState = { state: app.isPackaged ? "idle" : "dev" };
let updaterInstance = null;

function setUpdateState(next) {
  updateState = next;
  if (settingsWin && !settingsWin.isDestroyed()) {
    settingsWin.webContents.send("update-state", updateState);
  }
}

function getUpdater() {
  if (updaterInstance) return updaterInstance;
  const { autoUpdater } = require("electron-updater");
  autoUpdater.autoDownload = true;
  autoUpdater.on("checking-for-update", () => setUpdateState({ state: "checking" }));
  autoUpdater.on("update-available", (info) =>
    setUpdateState({ state: "downloading", version: info.version, percent: 0 }));
  autoUpdater.on("update-not-available", () => setUpdateState({ state: "up-to-date" }));
  autoUpdater.on("download-progress", (p) => setUpdateState({
    state: "downloading", version: updateState.version,
    percent: p.percent, transferred: p.transferred, total: p.total,
    bytesPerSecond: p.bytesPerSecond,
  }));
  autoUpdater.on("update-downloaded", (info) =>
    setUpdateState({ state: "ready", version: info.version }));
  autoUpdater.on("error", (err) => setUpdateState({
    state: "error",
    message: String(err?.message || err).split("\n")[0],
  }));
  updaterInstance = autoUpdater;
  return autoUpdater;
}

function checkForUpdates() {
  if (!app.isPackaged) return;
  try { getUpdater().checkForUpdates().catch(() => {}); } catch { /* updater unavailable */ }
}

ipcMain.handle("updates:check", () => { checkForUpdates(); return updateState; });
ipcMain.handle("updates:get-state", () => updateState);
ipcMain.on("updates:install", () => {
  if (!app.isPackaged || updateState.state !== "ready") return;
  try {
    quitting = true;
    stopBackend();
    getUpdater().quitAndInstall(true, true); // silent install, relaunch when done
  } catch { /* keep running; the renderer still shows the ready state */ }
});

// ------------------------------------------------------------------------ tray
function apiPost(pathname) {
  const req = http.request({ host: "127.0.0.1", port: BACKEND_PORT, path: pathname, method: "POST" });
  req.on("error", () => {});
  req.end();
}

function navigateTo(page) {
  showSettings();
  const wc = settingsWin.webContents;
  if (wc.isLoading()) wc.once("did-finish-load", () => wc.send("navigate", page));
  else wc.send("navigate", page);
}

function trayIcon() {
  const p = path.join(__dirname, "..", "assets", "icon.png");
  const img = fs.existsSync(p) ? nativeImage.createFromPath(p) : nativeImage.createEmpty();
  return img.isEmpty() ? img : img.resize({ width: 16, height: 16 });
}

let hotkeysPaused = false;
function createTray() {
  tray = new Tray(trayIcon());
  tray.setToolTip("WhisperText — AI dictation");
  const rebuild = () => tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Start Dictation", click: () => apiPost("/dictation/toggle") },
    {
      label: hotkeysPaused ? "Resume" : "Pause",
      click: () => { hotkeysPaused = !hotkeysPaused; apiPost(`/dictation/pause?paused=${hotkeysPaused}`); rebuild(); },
    },
    { type: "separator" },
    { label: "Settings", click: () => showSettings() },
    { label: "History", click: () => navigateTo("history") },
    { type: "separator" },
    { label: "Check for Updates", click: () => { checkForUpdates(); navigateTo("about"); } },
    { label: "Restart", click: () => { quitting = true; stopBackend(); app.relaunch(); app.exit(0); } },
    { label: "Quit", click: () => { quitting = true; app.quit(); } },
  ]));
  rebuild();
  tray.on("double-click", () => showSettings());
}

// ----------------------------------------------------------------------- boot
app.whenReady().then(() => {
  startBackend();
  createOverlay();
  createTray();
  showSettings();

  checkForUpdates();
  setInterval(checkForUpdates, 6 * 3600 * 1000);
});

app.on("window-all-closed", () => { /* tray app: stay alive with no windows */ });
app.on("before-quit", () => { quitting = true; stopBackend(); });
