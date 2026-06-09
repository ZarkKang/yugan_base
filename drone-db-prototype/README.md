# 域感智能 - 无人机数据管理系统

基于 FastAPI + PostgreSQL 的全栈项目，实现无人机数据（视频、图片、RFID）管理和多SKU管理。

## 项目结构

```
drone-db-prototype/
├── backend/
│   ├── app/
│   │   ├── core/          # 核心配置、数据库、安全
│   │   ├── models/        # SQLAlchemy 模型
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── routers/       # API 路由
│   │   └── main.py        # FastAPI 应用入口
│   ├── requirements.txt   # Python 依赖
│   └── .env.example       # 环境变量示例
├── database/
│   └── migrations/
│       └── init.sql       # 数据库初始化脚本
├── frontend/
│   └── src/
│       └── index.html     # 前端页面
└── README.md
```

## 快速启动

### 1. 环境要求

- Python 3.9+
- PostgreSQL 13+
- Node.js (可选，用于前端开发)

### 2. 数据库设置

```bash
# 创建数据库
psql -U postgres
CREATE DATABASE drone_db;
\q

# 运行初始化脚本
psql -U postgres -d drone_db -f database/migrations/init.sql
```

### 3. 后端启动

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制并编辑环境变量
copy .env.example .env
# 编辑 .env 中的数据库连接信息

# 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 前端访问

直接用浏览器打开 `frontend/src/index.html` 即可。

或使用任意静态文件服务器：
```bash
cd frontend/src
python -m http.server 3000
```

访问 http://localhost:3000

### 5. 默认账号

- 用户名: admin
- 密码: admin123

**注意**: 首次使用需要先在数据库中创建 admin 用户，或修改注册接口允许公开注册。

## API 接口

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | /api/auth/login | 用户登录 |
| POST | /api/auth/register | 用户注册 |
| GET | /api/users/me | 获取当前用户 |
| GET | /api/skus/ | SKU列表 |
| POST | /api/skus/ | 创建SKU |
| GET | /api/drones/ | 无人机列表 |
| POST | /api/drones/ | 创建无人机 |
| GET | /api/videos/ | 视频列表 |
| POST | /api/videos/ | 上传视频 |
| GET | /api/images/ | 图片列表 |
| POST | /api/images/ | 上传图片 |
| GET | /api/rfid/ | RFID列表 |
| POST | /api/rfid/ | 创建RFID数据 |

## 数据库模型

### User (用户)
- 用户名、邮箱、密码哈希
- 角色: admin / operator / viewer

### SKU
- SKU编码、名称、分类、单位
- 与无人机一一对应

### Drone (无人机)
- 编号、名称、型号、制造商
- 状态: idle / flying / maintenance / retired
- 位置信息、飞行参数

### VideoData (视频数据)
- 文件名、路径、大小、时长
- 分辨率、帧率、编码格式
- 拍摄位置、时间

### ImageData (图片数据)
- 文件名、路径、大小
- 宽高、格式
- 拍摄位置、时间

### RFIDData (RFID数据)
- 标签ID、类型
- 位置、信号强度
- 检测时间
