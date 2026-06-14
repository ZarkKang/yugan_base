# 域感智能 — Linux 使用手册

> 基于无人机 + RFID 的仓库智能巡检一体化系统

## 项目结构

```
域感智能/
├── drone-db-prototype/              # 无人机数据系统 (端口 8000)
│   ├── backend/                     # FastAPI + SQLite + Redis
│   └── frontend/                    # 前端页面
├── warehouse-inspection-system/     # 仓库巡检系统 (端口 8001)
│   ├── backend/                     # FastAPI + PostgreSQL + Redis
│   │   └── src/
│   │       ├── api/                 # API 路由
│   │       ├── hardware/            # RFID 驱动 (PRE 模块 V2.2)
│   │       ├── services/            # 业务逻辑
│   │       └── models/              # 数据模型
│   ├── frontend/                    # 前端页面 (16 页)
│   ├── docker-compose.yml           # Docker 编排
│   └── .env                         # 环境变量配置
├── api-gateway/                     # API 网关 (端口 8080)
├── desktop-app/                     # 桌面启动器 (Electron)
├── 引导.sh                          # 交互式引导菜单
├── 启动.sh                          # 命令行启动/管理
├── deploy-linux.sh                  # 一键部署脚本
└── doc/                             # 文档
```

---

## 快速开始

### 方式一：引导菜单（推荐首次使用）

```bash
chmod +x 引导.sh 启动.sh
./引导.sh
```

交互式菜单包含：环境检查 → 依赖安装 → 数据库初始化 → 服务部署 → 功能测试

### 方式二：一键启动（日常使用）

```bash
./启动.sh start          # 启动全部服务
./启动.sh status         # 查看状态
./启动.sh stop           # 停止全部服务
```

### 方式三：Docker 生产模式

```bash
cd warehouse-inspection-system
# 编辑 .env 配置 RFID 串口路径
docker compose up -d
```

---

## 三种运行模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| **hybrid**（默认） | 数据库用 Docker，后端用本地 | 开发调试（含 RFID 硬件） |
| **local** | 全部本地运行 | 纯软件功能开发 |
| **docker** | 全部 Docker 容器化 | 生产部署 |

```bash
# 切换模式
./引导.sh  →  环境部署  →  切换运行模式

# 或直接指定
MODE=docker ./启动.sh start
```

---

## 启动脚本命令参考

```bash
./启动.sh start      # 一键启动 (hybrid 模式)
./启动.sh docker     # Docker 模式启动
./启动.sh daemon     # 守护进程模式 (自动重启)
./启动.sh status     # 服务状态总览
./启动.sh stop       # 停止所有服务
./启动.sh help       # 帮助信息
```

启动时自动执行：
- 基础设施检测 (PostgreSQL + Redis)
- RFID 串口设备探测
- 权限检查与修复 (dialout 组 / 设备权限)
- 虚拟环境创建与依赖安装
- 日志轮转

---

## 引导菜单功能

```
┌────────────────────────────┐
│   域感智能 - 引导菜单       │
├────────────────────────────┤
│ 1. 环境部署                │
│    ├─ 环境检查             │
│    ├─ 安装依赖             │
│    ├─ 初始化数据库         │
│    ├─ 配置 pip 镜像        │
│    ├─ 切换运行模式         │
│    └─ 快速部署 (一键)      │
│ 2. 服务管理                │
│    ├─ 启动服务             │
│    ├─ 停止服务             │
│    └─ 查看日志             │
│ 3. 功能测试                │
│    ├─ RFID 测试            │
│    ├─ QR 识别测试          │
│    ├─ API 连通性测试       │
│    └─ 数据库测试           │
│ 4. 系统维护                │
│    ├─ 清理虚拟环境         │
│    ├─ 清理日志             │
│    ├─ 重置数据库           │
│    └─ 更新代码             │
│ 5. 数据库管理              │
│    ├─ 启停 PostgreSQL      │
│    ├─ 启停 Redis           │
│    ├─ SQL Shell            │
│    └─ 查看数据表           │
│ 6. 系统信息                │
│ 0. 退出                    │
└────────────────────────────┘
```

---

## RFID 设置

### 串口配置

在 `warehouse-inspection-system/.env` 中配置：

```bash
# Linux 原生
RFID_DEVICE=/dev/ttyUSB0

# WSL 环境
RFID_DEVICE=/dev/ttyS6

# 不启用 RFID
RFID_DEVICE=
```

启动脚本会自动检测串口并写入 `.env`，同时检查并修复权限。

### Docker 模式串口直通

```yaml
# docker-compose.yml 已配置
devices:
  - "${RFID_DEVICE:-/dev/null}:/dev/ttyUSB0"
environment:
  RFID_SERIAL_PORT: "${RFID_DEVICE:-/dev/null}"
```

### RFID 参数设置

Web 前端 → RFID 设置页面，支持全部 30 条 PRE 模块协议命令：

| 分类 | 功能 |
|------|------|
| 基本 | 工作地区、发射功率、FHSS、CW 载波 |
| Query | DR/M/TRext/Sel/Session/Target/Q |
| 高级 | Modem 参数、盘存模式、环境模式、RF 信道 |
| Select | ISO18000-6C Select 参数 |
| 系统 | NV 配置保存/加载、重启、休眠 |
| 诊断 | 干扰扫描、RSSI 扫描、模块信息 |
| 标签 | NXP G2X、Monza QT |

---

## 访问地址

| 服务 | 地址 |
|------|------|
| 无人机数据系统 API | http://localhost:8000 |
| 无人机数据系统文档 | http://localhost:8000/docs |
| 仓库巡检系统 API | http://localhost:8001 |
| 仓库巡检系统文档 | http://localhost:8001/docs |
| API 网关 | http://localhost:8080 |
| API 网关文档 | http://localhost:8080/docs |
| 前端页面 | `warehouse-inspection-system/frontend/index.html` |

---

## 环境依赖

| 组件 | 必需 | 说明 |
|------|:--:|------|
| Python 3.11+ | Y | 后端服务 |
| PostgreSQL | Y | 仓库巡检系统数据库 |
| Redis | N | 缓存（可选） |
| Docker | N | Docker 模式需要 |
| CP2102 驱动 | Y | RFID 模块 USB 驱动 |

---

## 权限要求

```bash
# 串口设备访问
sudo usermod -aG dialout $USER

# Docker 访问（Docker 模式）
sudo usermod -aG docker $USER

# 重新登录后生效
```

启动脚本会自动检测并提示修复。

---

## 故障排查

### 端口被占用

```bash
lsof -i :8000
lsof -i :8001
lsof -i :8080
kill -9 <PID>
```

### RFID 模块未检测到

```bash
# 检查设备
ls -la /dev/ttyUSB* /dev/ttyACM*

# 检查驱动
lsusb | grep -i cp2102

# 检查权限
groups $USER | grep dialout
```

### Docker 容器日志

```bash
docker compose logs -f backend
docker compose logs -f postgres
```

### 服务启动失败

```bash
# 查看日志
cat logs/仓库巡检系统.log
cat logs/无人机数据系统.log
cat logs/API网关.log

# 或使用引导菜单
./引导.sh  →  服务管理  →  查看日志
```