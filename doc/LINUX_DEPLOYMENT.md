
# 域感智能 - Linux 部署指南

## 🚀 快速开始

### 方式一：使用启动脚本（推荐）
```bash
chmod +x 启动.sh
./启动.sh
```

### 方式二：单独启动各服务

#### 1. 启动无人机数据系统
```bash
cd drone-db-prototype/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. 启动仓库巡检系统
```bash
cd warehouse-inspection-system/backend

# 如果有虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

#### 3. 启动 API 网关
```bash
cd api-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

#### 4. 启动桌面应用
```bash
cd desktop-app
npm install
npm run dev
```

## 🐳 使用 Docker Compose

```bash
# 构建并启动所有服务
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

## 📱 访问地址

| 服务 | 地址 |
|------|------|
| 无人机数据系统 | http://localhost:8000 |
| 仓库巡检系统 | http://localhost:8001 |
| API 网关 | http://localhost:8080 |
| 桌面应用 | 本地运行 |

## 📦 依赖安装

### Python 依赖
```bash
# 为所有项目安装依赖
cd drone-db-prototype/backend && pip install -r requirements.txt
cd ../../warehouse-inspection-system/backend && pip install -r requirements.txt
cd ../../api-gateway && pip install -r requirements.txt
```

### Node.js 依赖（桌面应用）
```bash
cd desktop-app
npm install
```

## 🔧 配置说明

### 数据库配置
无人机数据系统已配置为使用 SQLite，无需额外安装数据库。

如需使用 PostgreSQL，修改 `drone-db-prototype/backend/app/core/config.py`：
```python
DATABASE_URL: str = "postgresql://user:password@localhost:5432/yugan_db"
```

## 🐛 故障排查

### 端口被占用
```bash
# 查看端口占用
netstat -tlnp | grep -E '8000|8001|8080'

# 或使用 lsof
lsof -i :8000
```

### 权限问题
```bash
# 确保启动脚本有执行权限
chmod +x 启动.sh

# 确保目录可写
chmod -R 755 .
```

### 虚拟环境问题
```bash
# 创建新虚拟环境
cd warehouse-inspection-system/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
