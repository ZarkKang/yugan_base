
# ========================================
#      域感智能 - Linux 部署文件清单
# ========================================
# 最后更新: 2026-06-08
#
# 使用说明:
#   1. 给脚本添加执行权限: chmod +x *.sh
#   2. 运行一键部署: ./deploy-linux.sh
#   3. 或使用 Makefile: make help
#

# 项目根目录文件
.
├── README_LINUX.md           # Linux 项目说明
├── LINUX_DEPLOYMENT.md      # Linux 详细部署文档
├── BACKEND_IMPROVEMENTS.md  # 后端功能说明
├── QUICK_START.md           # 快速启动指南
├── Makefile                 # Make 构建工具
├── 启动.bat                 # Windows 启动脚本
├── 启动.sh                  # Linux 启动脚本 ✅
├── deploy-linux.sh          # Linux 一键部署 ✅
├── docker-compose.yml       # Docker 编排
└── .gitignore               # Git 忽略配置

# API 网关
api-gateway/
├── main.py                  # 网关主程序
├── requirements.txt         # Python 依赖
└── Dockerfile               # Docker 构建文件

# 无人机数据系统
drone-db-prototype/
└── backend/
    ├── app/
    │   ├── core/
    │   │   ├── config.py         # 配置文件 (已改为 SQLite)
    │   │   ├── permissions.py    # RBAC 权限系统 ✨
    │   │   └── security.py
    │   ├── routers/
    │   │   └── admin.py          # 管理 API ✨
    │   └── services/
    │       ├── qr_service.py     # 二维码识别 ✨
    │       ├── backup_service.py # 数据备份恢复 ✨
    │       ├── websocket_service.py # WebSocket ✨
    │       └── tracing_service.py # 链路追踪 ✨
    ├── requirements.txt       # 依赖 (已更新)
    ├── .env.example.linux     # Linux 环境配置 ✅
    └── Dockerfile             # Docker 构建文件

# 仓库巡检系统
warehouse-inspection-system/
└── backend/
    ├── src/
    │   └── main.py
    ├── requirements.txt
    └── Dockerfile

# 桌面应用
desktop-app/
├── src/
│   ├── main.js              # 主进程 (已更新)
│   ├── preload.js           # 预加载 (已更新)
│   └── launcher.html        # 启动器界面 (已更新)
├── package.json
└── dist/
    └── win-unpacked/
        └── 域感智能.exe     # Windows 可执行文件

# Systemd 服务 (Linux 系统服务)
systemd/
├── yugan-drone.service      # 无人机数据系统服务 ✅
└── yugan-warehouse.service  # 仓库巡检系统服务 ✅

# ========================================
#         ✨ 新增/更新的文件
# ========================================
#
# - 启动.sh                    Linux 菜单启动脚本
# - deploy-linux.sh            Linux 一键部署脚本
# - Makefile                   Make 构建工具
# - README_LINUX.md            Linux 项目说明
# - LINUX_DEPLOYMENT.md        Linux 详细文档
# - .gitignore                 Git 配置
# - systemd/*.service          Linux 系统服务
# - drone-db-prototype/backend/app/core/permissions.py
# - drone-db-prototype/backend/app/services/*
# - drone-db-prototype/backend/app/routers/admin.py
# - drone-db-prototype/backend/.env.example.linux
# - drone-db-prototype/backend/app/main.py (已更新)
# - desktop-app/src/main.js (已更新)
# - desktop-app/src/preload.js (已更新)
# - desktop-app/src/launcher.html (已更新)
# - docker-compose.yml (已修复)
#
# ========================================
