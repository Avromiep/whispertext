const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("whispertext", {
  showOverlay: () => ipcRenderer.send("overlay:show"),
  hideOverlay: () => ipcRenderer.send("overlay:hide"),
  openSettings: () => ipcRenderer.send("app:open-settings"),
  openExternal: (url) => ipcRenderer.send("app:open-external", url),
  restart: () => ipcRenderer.send("app:restart"),
  getLoginItem: () => ipcRenderer.invoke("app:get-login-item"),
  setLoginItem: (v) => ipcRenderer.invoke("app:set-login-item", v),
  checkUpdates: () => ipcRenderer.invoke("updates:check"),
  getUpdateState: () => ipcRenderer.invoke("updates:get-state"),
  installUpdate: () => ipcRenderer.send("updates:install"),
  onNavigate: (cb) => ipcRenderer.on("navigate", (_e, page) => cb(page)),
  onUpdateState: (cb) => ipcRenderer.on("update-state", (_e, state) => cb(state)),
});
