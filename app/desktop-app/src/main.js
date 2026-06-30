const { app, BrowserWindow, Menu, Tray, ipcMain, shell, dialog, nativeImage } = require('electron');
const path = require('path');
const http = require('http');
const log = require('electron-log');

// 配置日志
log.transports.file.level = 'info';
log.transports.file.maxSize = 10 * 1024 * 1024; // 10MB
log.info('应用程序启动...');

// 全局引用
let mainWindow = null;
let tray = null;

// 服务连接状态
let connectionStatus = {
    droneDb: { connected: false, url: null, error: null },
    warehouseInspection: { connected: false, url: null, error: null }
};

// 项目路径配置
const PROJECTS = {
    'drone-db': {
        name: '无人机数据库系统',
        description: '无人机数据管理、SKU管理、视频/图像/RFID数据管理',
        path: path.join(__dirname, '..', '..', 'drone-db-prototype', 'frontend', 'src', 'index.html'),
        icon: '🚁',
        backend: {
            port: 8000,
            healthEndpoint: '/health',
            // 直连模式的API路径前缀
            apiBase: '/api',
            // 通过网关时的API路径前缀
            gatewayApiBase: '/api/drone'
        }
    },
    'warehouse-inspection': {
        name: '仓库巡检系统',
        description: '仓库巡检、无人机管理、数据接收网关',
        path: path.join(__dirname, '..', '..', 'warehouse-inspection-system', 'frontend', 'index.html'),
        icon: '📦',
        backend: {
            port: 8001,
            healthEndpoint: '/health',
            // 直连模式的API路径前缀
            apiBase: '/api/v1',
            // 通过网关时的API路径前缀
            gatewayApiBase: '/api/warehouse'
        }
    }
};

// 网关端口（统一入口）
const GATEWAY_PORT = 8080;

// 获取本机 IP 地址
function getLocalIP() {
    const os = require('os');
    const interfaces = os.networkInterfaces();
    const addresses = [];

    for (const name of Object.keys(interfaces)) {
        for (const iface of interfaces[name]) {
            if (iface.family === 'IPv4' && !iface.internal) {
                addresses.push(iface.address);
            }
        }
    }

    return addresses;
}

// 扫描常用端口范围
function getCommonPorts() {
    return [
        8000, 8001, 8002, 8080, 8081, 3000, 3001, 5000, 5001, 7000, 7443
    ];
}

// 检测后端服务（支持直连和网关模式）
async function detectBackend(projectId) {
    const project = PROJECTS[projectId];
    if (!project) return null;

    const { port, healthEndpoint } = project.backend;
    const localIPs = getLocalIP();

    log.info(`开始检测 ${project.name} 后端服务...`);

    // 策略1: 尝试直连（优先，速度最快）
    const directHosts = ['127.0.0.1', 'localhost', ...localIPs];
    for (const host of directHosts) {
        const url = `http://${host}:${port}${healthEndpoint}`;
        try {
            const result = await healthCheck(url, 2000);
            if (result.ok) {
                log.info(`[直连] ${project.name} 后端已找到: ${url}`);
                return {
                    host,
                    port,
                    baseUrl: `http://${host}:${port}`,
                    url,
                    isGateway: false,
                    apiBase: project.backend.apiBase
                };
            }
        } catch (e) {
            // 继续尝试下一个
        }
    }

    // 策略2: 尝试通过API网关连接
    for (const host of ['127.0.0.1', 'localhost', ...localIPs]) {
        const url = `http://${host}:${GATEWAY_PORT}${healthEndpoint}`;
        try {
            const result = await healthCheck(url, 2000);
            if (result.ok) {
                log.info(`[网关] 通过网关找到后端: ${url}, 项目: ${project.name}`);
                return {
                    host,
                    port: GATEWAY_PORT,
                    baseUrl: `http://${host}:${GATEWAY_PORT}`,
                    url,
                    isGateway: true,
                    apiBase: project.backend.gatewayApiBase
                };
            }
        } catch (e) {
            // 继续
        }
    }

    // 策略3: 端口扫描兜底
    log.info('标准端口未响应，开始端口扫描...');
    const scanPorts = [8000, 8001, 8002, 8080, 8081, 3000, 5000];
    for (const scanPort of scanPorts) {
        for (const host of ['127.0.0.1', 'localhost']) {
            const url = `http://${host}:${scanPort}${healthEndpoint}`;
            try {
                const result = await healthCheck(url, 1500);
                if (result.ok) {
                    const isGatewayMode = (scanPort === GATEWAY_PORT);
                    log.info(`[扫描] 找到后端: ${url} (网关模式: ${isGatewayMode})`);
                    return {
                        host,
                        port: scanPort,
                        baseUrl: `http://${host}:${scanPort}`,
                        url,
                        isGateway: isGatewayMode,
                        apiBase: isGatewayMode ? project.backend.gatewayApiBase : project.backend.apiBase
                    };
                }
            } catch (e) {
                // 继续
            }
        }
    }

    log.warn(`未找到 ${project.name} 后端服务`);
    return null;
}

// HTTP 健康检查
function healthCheck(url, timeout = 2000) {
    return new Promise((resolve, reject) => {
        const req = http.get(url, { timeout }, (res) => {
            if (res.statusCode >= 200 && res.statusCode < 300) {
                resolve({ ok: true, status: res.statusCode });
            } else {
                resolve({ ok: false, status: res.statusCode });
            }
        });

        req.on('error', reject);
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('Timeout'));
        });
    });
}

// 自动检测所有后端服务
async function detectAllBackends() {
    log.info('开始自动检测所有后端服务...');

    const results = {};

    for (const projectId of Object.keys(PROJECTS)) {
        const result = await detectBackend(projectId);
        results[projectId] = result;
    }

    return results;
}

// 创建主窗口
function createWindow() {
    log.info('创建主窗口...');

    mainWindow = new BrowserWindow({
        width: 1400,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        title: '域感智能',
        icon: path.join(__dirname, 'icon.png'),
        frame: true, // 使用系统原生窗口边框
        autoHideMenuBar: true, // 自动隐藏菜单栏
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            contextIsolation: true,
            nodeIntegration: false,
            webSecurity: true
        },
        show: false,
        backgroundColor: '#1a1e28'
    });

    loadLauncher();

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        log.info('主窗口已显示');
    });

    mainWindow.on('close', (event) => {
        if (!app.isQuitting) {
            event.preventDefault();
            mainWindow.hide();
        }
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

// 加载启动选择器
function loadLauncher() {
    const launcherPath = path.join(__dirname, 'launcher.html');
    mainWindow.loadFile(launcherPath);
    log.info('加载启动器页面');
}

// 加载指定项目
function loadProject(projectId) {
    const project = PROJECTS[projectId];
    if (!project) {
        log.error(`项目不存在: ${projectId}`);
        return;
    }

    log.info(`加载项目: ${project.name}`);

    if (mainWindow) {
        mainWindow.loadFile(project.path);
        mainWindow.setTitle(`域感智能 - ${project.name}`);
    }
}

// 创建系统托盘
function createTray() {
    const iconPath = path.join(__dirname, 'icon.png');
    let trayIcon;

    try {
        trayIcon = nativeImage.createFromPath(iconPath);
        if (trayIcon.isEmpty()) {
            trayIcon = nativeImage.createEmpty();
        }
    } catch (e) {
        trayIcon = nativeImage.createEmpty();
    }

    tray = new Tray(trayIcon);

    const contextMenu = Menu.buildFromTemplate([
        {
            label: '显示主窗口',
            click: () => {
                if (mainWindow) mainWindow.show();
            }
        },
        {
            label: '无人机数据库系统',
            click: () => loadProject('drone-db')
        },
        {
            label: '仓库巡检系统',
            click: () => loadProject('warehouse-inspection')
        },
        { type: 'separator' },
        {
            label: '退出',
            click: () => {
                app.isQuitting = true;
                app.quit();
            }
        }
    ]);

    tray.setToolTip('域感智能');
    tray.setContextMenu(contextMenu);

    tray.on('double-click', () => {
        if (mainWindow) mainWindow.show();
    });

    log.info('系统托盘已创建');
}

// IPC 处理器 - 窗口控制
ipcMain.handle('window-minimize', () => {
    if (mainWindow) mainWindow.minimize();
});

ipcMain.handle('window-maximize', () => {
    if (mainWindow) {
        if (mainWindow.isMaximized()) {
            mainWindow.unmaximize();
        } else {
            mainWindow.maximize();
        }
    }
});

ipcMain.handle('window-close', () => {
    if (mainWindow) mainWindow.hide();
});

ipcMain.handle('window-is-maximized', () => {
    return mainWindow ? mainWindow.isMaximized() : false;
});

// IPC 处理器 - 导航
ipcMain.handle('go-home', () => {
    log.info('返回主页');
    loadLauncher();
    return true;
});

ipcMain.handle('go-back', () => {
    log.info('返回上一页');
    if (mainWindow && mainWindow.webContents.canGoBack()) {
        mainWindow.webContents.goBack();
    } else {
        loadLauncher();
    }
    return true;
});

// IPC 处理器 - 项目
ipcMain.handle('load-project', async (event, projectId) => {
    loadProject(projectId);
    return true;
});

ipcMain.handle('get-projects', async () => {
    return Object.entries(PROJECTS).map(([id, data]) => ({
        id,
        name: data.name,
        description: data.description,
        icon: data.icon
    }));
});

ipcMain.handle('detect-backends', async () => {
    log.info('手动触发后端检测...');
    const results = await detectAllBackends();

    for (const [projectId, result] of Object.entries(results)) {
        if (result) {
            const apiUrl = `${result.baseUrl}${result.apiBase}`;
            connectionStatus[projectId] = {
                connected: true,
                url: result.baseUrl,
                apiUrl: apiUrl,
                isGateway: result.isGateway,
                error: null
            };
        } else {
            connectionStatus[projectId] = {
                connected: false,
                url: null,
                apiUrl: null,
                isGateway: false,
                error: '服务未找到'
            };
        }
    }

    return results;
});

ipcMain.handle('get-backend-url', async (event, projectId) => {
    if (connectionStatus[projectId]?.connected && connectionStatus[projectId]?.apiUrl) {
        return connectionStatus[projectId].apiUrl;
    }

    const result = await detectBackend(projectId);
    if (result) {
        // 构建完整API地址: baseUrl + apiBase
        const apiUrl = `${result.baseUrl}${result.apiBase}`;
        connectionStatus[projectId] = {
            connected: true,
            url: result.baseUrl,
            apiUrl: apiUrl,
            isGateway: result.isGateway,
            error: null
        };
        log.info(`${projectId} API地址: ${apiUrl} (网关模式: ${result.isGateway})`);
        return apiUrl;
    }

    return null;
});

ipcMain.handle('get-connection-status', async () => {
    return connectionStatus;
});

ipcMain.handle('open-external', async (event, url) => {
    await shell.openExternal(url);
    return true;
});

ipcMain.handle('show-save-dialog', async (event, options) => {
    const result = await dialog.showSaveDialog(mainWindow, options);
    return result;
});

ipcMain.handle('show-open-dialog', async (event, options) => {
    const result = await dialog.showOpenDialog(mainWindow, options);
    return result;
});

ipcMain.handle('quit-app', () => {
    app.isQuitting = true;
    app.quit();
});

// 应用事件
app.whenReady().then(async () => {
    log.info('应用准备就绪');

    // 启动时自动检测后端服务
    log.info('开始启动时后端检测...');
    const detectionResults = await detectAllBackends();

    for (const [projectId, result] of Object.entries(detectionResults)) {
        if (result) {
            const apiUrl = `${result.baseUrl}${result.apiBase}`;
            connectionStatus[projectId] = {
                connected: true,
                url: result.baseUrl,
                apiUrl: apiUrl,
                isGateway: result.isGateway,
                error: null
            };
            log.info(`${projectId} 后端已连接: ${result.baseUrl} (API: ${apiUrl}, 网关: ${result.isGateway})`);
        } else {
            connectionStatus[projectId] = {
                connected: false,
                url: null,
                apiUrl: null,
                isGateway: false,
                error: '服务未找到，请确保后端已启动'
            };
            log.warn(`${projectId} 后端未连接`);
        }
    }

    createWindow();
    createTray();

    if (mainWindow) {
        mainWindow.webContents.once('did-finish-load', () => {
            mainWindow.webContents.send('connection-status', connectionStatus);
        });
    }
});

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit();
    }
});

app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
    }
});

app.on('before-quit', () => {
    log.info('应用程序即将退出');
    app.isQuitting = true;
});

process.on('uncaughtException', (error) => {
    log.error('未捕获的异常:', error);
});

process.on('unhandledRejection', (reason, promise) => {
    log.error('未处理的 Promise 拒绝:', reason);
});
