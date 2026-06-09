const { contextBridge, ipcRenderer } = require('electron');

// 暴露安全的 API 到渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
    // 窗口控制
    windowMinimize: () => ipcRenderer.invoke('window-minimize'),
    windowMaximize: () => ipcRenderer.invoke('window-maximize'),
    windowClose: () => ipcRenderer.invoke('window-close'),
    windowIsMaximized: () => ipcRenderer.invoke('window-is-maximized'),

    // 导航
    goHome: () => ipcRenderer.invoke('go-home'),
    goBack: () => ipcRenderer.invoke('go-back'),

    // 项目
    loadProject: (projectId) => ipcRenderer.invoke('load-project', projectId),
    getProjects: () => ipcRenderer.invoke('get-projects'),

    // 后端检测
    getBackendUrl: (projectId) => ipcRenderer.invoke('get-backend-url', projectId),
    getConnectionStatus: () => ipcRenderer.invoke('get-connection-status'),
    detectBackends: () => ipcRenderer.invoke('detect-backends'),

    // 系统
    openExternal: (url) => ipcRenderer.invoke('open-external', url),
    showSaveDialog: (options) => ipcRenderer.invoke('show-save-dialog', options),
    showOpenDialog: (options) => ipcRenderer.invoke('show-open-dialog', options),
    quitApp: () => ipcRenderer.invoke('quit-app'),

    // 事件监听
    onConnectionStatus: (callback) => {
        ipcRenderer.on('connection-status', (event, status) => callback(status));
    },
    onShowMessage: (callback) => {
        ipcRenderer.on('show-message', (event, message) => callback(message));
    },

    // 信息
    platform: process.platform,
    versions: {
        node: process.versions.node,
        chrome: process.versions.chrome,
        electron: process.versions.electron
    }
});

console.log('Preload script loaded successfully');
