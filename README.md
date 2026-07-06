# Warehouse Inspection System / 仓库巡检系统

A drone-based warehouse inspection platform with real-time video streaming, QR code recognition, and automated inventory management.

基于无人机的仓库巡检平台，支持实时视频流传输、二维码识别及自动化库存管理。

---

## Features / 主要功能

- **Drone Patrol / 无人机巡检** – Automated flight missions along predefined waypoints.  
  按预设航点执行自动化飞行巡检任务。
- **Real-time Video / 实时视频** – WebSocket-based video streaming with waypoint clipping.  
  基于 WebSocket 的视频流传输，支持航点视频截取。
- **QR Code Recognition / 二维码识别** – Multi-camera QR scanning for shelf & SKU tracking.  
  多摄像头二维码扫描，实现货架与 SKU 追踪。
- **RFID Integration / RFID 集成** – RFID tag reading for inbound/outbound verification.  
  RFID 标签读取，用于出入库校验。
- **Inventory Management / 入库管理** – Digital shelf management and inbound record tracking.  
  数字化货架管理与入库记录追踪。
- **Connection Monitoring / 连接监控** – Real-time drone and hardware status monitoring.  
  实时无人机与硬件状态监控。

---

## Tech Stack / 技术栈

| Layer / 层级 | Technology / 技术 |
|-------------|------------------|
| Backend / 后端 | Python, FastAPI, SQLAlchemy, Alembic |
| Database / 数据库 | PostgreSQL / SQLite, Redis |
| Frontend / 前端 | HTML, JavaScript |
| Hardware / 硬件 | RFID, SBUS, Serial, Ethernet |
| Deployment / 部署 | Docker, Docker Compose, systemd |

---

## Quick Start / 快速开始

```bash
# 1. Clone & enter project / 克隆并进入项目
cd /workspace

# 2. Copy environment config / 复制环境配置
cp .env.prod.example .env

# 3. Start services / 启动服务
docker-compose up -d

# Or use helper scripts / 或使用辅助脚本
./start.sh
```

---

## Project Structure / 项目结构

```
/workspace
├── station/warehouse-inspection-system/   # Base station service / 基站端服务
│   ├── backend/                           # FastAPI backend / FastAPI 后端
│   ├── frontend/                          # Web frontend / Web 前端
│   └── docs/                              # Documentation / 文档
├── app/                                   # App gateway & scripts / 应用网关与脚本
├── doc/                                   # Project docs / 项目文档
├── docker-compose.yml                     # Orchestration / 编排配置
└── setup.sh / start.sh                    # Setup & run helpers / 安装与启动脚本
```

---

## Documentation / 相关文档

- [Linux Deployment Guide](doc/LINUX_DEPLOYMENT.md) / Linux 部署指南
- [System Architecture](doc/specs/系统技术架构文档.md) / 系统技术架构文档
- [Drone API Outline](doc/无人机端API大纲.md) / 无人机端 API 大纲
- [Development Guide](station/warehouse-inspection-system/docs/development_guide.md) / 开发指南

---

## License / 许可证

This project is proprietary and confidential. / 本项目为专有及机密项目。
