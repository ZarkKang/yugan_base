# 域感智能桌面应用程序

基于 Electron 的桌面应用程序，整合了无人机数据库系统和仓库巡检系统。

## 功能特性

- 统一的桌面应用，替代浏览器访问
- 项目选择器，快速切换不同系统
- 系统托盘支持，最小化到托盘运行
- 原生窗口控制（最小化、最大化、关闭）
- 应用菜单和快捷键支持
- 跨平台支持（Windows、macOS、Linux）

## 项目结构

```
desktop-app/
├── package.json          # 项目配置和依赖
├── src/
│   ├── main.js          # Electron 主进程
│   ├── preload.js       # 预加载脚本（安全桥接）
│   ├── launcher.html    # 项目选择器界面
│   └── icon.png         # 应用图标
└── README.md
```

## 安装和运行

### 前置要求

- Node.js 18+ 版本
- npm 或 yarn

### 安装依赖

```bash
cd desktop-app
npm install
```

### 运行开发模式

```bash
npm run dev
```

### 运行生产版本

```bash
npm start
```

### 构建安装包

```bash
# Windows
npm run build:win

# macOS
npm run build:mac

# Linux
npm run build:linux

# 所有平台
npm run build
```

## 使用说明

1. **启动应用**: 运行后显示项目选择器
2. **选择项目**: 点击卡片进入对应系统
3. **返回选择器**: 菜单栏 → 文件 → 返回选择器
4. **最小化到托盘**: 关闭窗口会自动最小化到托盘
5. **托盘操作**: 双击托盘图标可恢复窗口

## 集成项目

桌面应用整合了以下项目:

1. **无人机数据库系统** (`drone-db-prototype`)
   - SKU 管理
   - 无人机管理
   - 视频/图像/RFID 数据管理

2. **仓库巡检系统** (`warehouse-inspection-system`)
   - 数据面板
   - 无人机管理
   - 巡检记录
   - 数据接收网关

## 自定义图标

应用图标位于 `src/icon.png` (256x256 PNG 格式)

如需生成新图标，可修改 `src/generate-icon.js` 并运行:

```bash
node src/generate-icon.js
```

## 配置说明

### 主进程配置 (main.js)

- `width/height`: 窗口默认尺寸
- `minWidth/minHeight`: 窗口最小尺寸
- `PROJECTS`: 项目路径配置

### 打包配置 (package.json build)

可根据需要修改 `appId`、`productName` 等配置。

## 常见问题

**Q: 窗口无法显示内容？**
A: 检查项目路径是否正确，确保前端文件存在于指定位置。

**Q: 托盘图标不显示？**
A: 确保 `src/icon.png` 存在且格式正确。

**Q: 如何添加新的项目？**
A: 在 `main.js` 的 `PROJECTS` 对象中添加新项目配置。

## 技术栈

- Electron 28.x
- electron-builder 24.x
- electron-log 5.x
