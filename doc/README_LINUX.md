
# 域感智能 - Linux 环境

&gt; 智能无人机数据管理与仓库巡检系统

## 📦 项目结构

```
域感智能/
├── drone-db-prototype/       # 无人机数据系统
│   ├── backend/             # 后端服务
│   ├── database/            # 数据库相关
│   └── frontend/            # 前端
├── warehouse-inspection-system/  # 仓库巡检系统
│   └── backend/             # 后端服务
├── api-gateway/             # API 网关
├── desktop-app/             # 桌面应用
├── systemd/                 # systemd 服务文件
├── docker-compose.yml       # Docker 编排
├── Makefile                # Make 工具
├── 启动.sh                 # Linux 启动脚本
├── deploy-linux.sh         # 一键部署脚本
└── LINUX_DEPLOYMENT.md     # Linux 部署文档
```

## 🚀 快速开始

### 方式一：一键部署（推荐）

```bash
# 1. 赋予执行权限
chmod +x deploy-linux.sh

# 2. 运行部署脚本
./deploy-linux.sh
```

### 方式二：使用 Makefile

```bash
# 安装所有依赖
make install

# 启动各个服务（不同终端）
make drone      # 终端1：无人机数据系统
make warehouse  # 终端2：仓库巡检系统
make gateway    # 终端3：API 网关
make desktop    # 终端4：桌面应用
```

### 方式三：手动启动

```bash
# 无人机数据系统
cd drone-db-prototype/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 仓库巡检系统（新终端）
cd warehouse-inspection-system/backend
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload

# API 网关（新终端）
cd api-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# 桌面应用（新终端）
cd desktop-app
npm install
npm run dev
```

### 方式四：使用 Docker

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 📱 访问地址

| 服务 | 地址 |
|------|------|
| 无人机数据系统 API | http://localhost:8000 |
| 无人机数据系统文档 | http://localhost:8000/docs |
| 仓库巡检系统 API | http://localhost:8001 |
| 仓库巡检系统文档 | http://localhost:8001/docs |
| API 网关 | http://localhost:8080 |
| API 网关文档 | http://localhost:8080/docs |

## 🔧 配置说明

### 环境变量配置

复制示例配置：
```bash
cd drone-db-prototype/backend
cp .env.example.linux .env
```

编辑 `.env` 文件，根据需要修改配置。

### 数据库配置

项目默认使用 SQLite（无需额外安装）。

如需使用 PostgreSQL：
```bash
# 安装 PostgreSQL
sudo apt install postgresql postgresql-contrib  # Debian/Ubuntu
sudo dnf install postgresql-server              # Fedora/RHEL
sudo pacman -S postgresql                       # Arch

# 创建数据库和用户
sudo -u postgres psql
CREATE USER yugan WITH PASSWORD 'yugan123';
CREATE DATABASE yugan_db OWNER yugan;
\q

# 修改配置
# .env 中的 DATABASE_URL
DATABASE_URL=postgresql://yugan:yugan123@localhost:5432/yugan_db
```

## 🔄 Systemd 服务（生产环境）

### 安装服务

```bash
# 复制服务文件
sudo cp systemd/*.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload
```

### 管理服务

```bash
# 启动服务
sudo systemctl start yugan-drone
sudo systemctl start yugan-warehouse

# 设置开机自启
sudo systemctl enable yugan-drone
sudo systemctl enable yugan-warehouse

# 查看状态
sudo systemctl status yugan-drone

# 查看日志
sudo journalctl -u yugan-drone -f
```

## 🐛 故障排查

### 端口被占用

```bash
# 查看端口占用
netstat -tlnp | grep -E '8000|8001|8080'
# 或
lsof -i :8000

# 结束进程
kill -9 &lt;PID&gt;
```

### 权限问题

```bash
# 确保脚本有执行权限
chmod +x 启动.sh deploy-linux.sh

# 确保当前用户对项目目录有读写权限
chmod -R 755 /path/to/yugan-intelligence
```

### 依赖问题

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 在虚拟环境中安装依赖
pip install -r requirements.txt
```

### 清理缓存

```bash
make clean
```

## 📚 更多文档

- [Linux 部署指南](./LINUX_DEPLOYMENT.md) - 详细的 Linux 部署说明
- [后端完善文档](./BACKEND_IMPROVEMENTS.md) - 后端功能说明

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
