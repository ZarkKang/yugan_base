# 仓库巡检系统 - 后续开发手册

## 项目概述

基于无人机与基站的高效化仓库巡检联合系统的数据库接收与处理基站后端服务。

## 项目结构

```
warehouse-inspection-system/
├── backend/
│   ├── src/
│   │   ├── api/              # FastAPI路由
│   │   │   ├── inspection.py  # 巡检记录接口
│   │   │   ├── drones.py      # 无人机管理接口
│   │   │   └── gateway.py     # 数据接收网关
│   │   ├── services/         # 业务逻辑层
│   │   │   └── inspection_service.py
│   │   ├── models/           # SQLAlchemy模型
│   │   │   └── models.py
│   │   ├── schemas/          # Pydantic schemas
│   │   │   └── schemas.py
│   │   ├── hardware/         # 硬件通信模块
│   │   │   ├── serial.py     # 串口通信
│   │   │   ├── ethernet.py   # 以太网通信
│   │   │   └── sbus.py       # SBUS协议
│   │   ├── image/            # 图像处理
│   │   │   ├── qr_code.py    # 二维码识别
│   │   │   └── crop.py      # 图像裁剪
│   │   ├── db/              # 数据库相关
│   │   │   ├── database.py   # SQLAlchemy配置
│   │   │   └── redis.py      # Redis封装
│   │   ├── core/            # 核心配置
│   │   │   └── config.py    # 应用配置
│   │   └── main.py          # FastAPI入口
│   └── requirements.txt
├── frontend/                 # Vue3前端（待创建）
├── docs/                     # 文档
│   └── database_schema.md   # 数据库设计
└── docker-compose.yml        # 容器编排
```

## 快速开始

### 1. 环境要求

- Python 3.11+
- Docker & Docker Compose
- PostgreSQL 15 (可选，使用Docker)
- Redis (可选，使用Docker)

### 2. 本地开发

```bash
# 进入后端目录
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
copy .env.example .env
# 编辑 .env 文件配置数据库连接

# 启动服务
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Docker部署

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f backend

# 停止服务
docker-compose down
```

### 4. API文档

启动服务后访问: http://localhost:8000/docs

## 模块开发指南

### 硬件通信模块 (hardware/)

#### 串口通信 (serial.py)

```python
from src.hardware.serial import SerialComm, SerialConfig, list_available_ports

# 配置串口
config = SerialConfig(
    port="/dev/ttyUSB0",
    baudrate=9600
)

# 创建连接
comm = SerialComm(config)
comm.connect()

# 读取数据
data = comm.read_line()

# 断开连接
comm.disconnect()

# 列出可用串口
ports = list_available_ports()
```

#### SBUS协议 (sbus.py)

```python
from src.hardware.sbus import SBUSDecoder, SBUSEncoder, SBUSProcessor

# 创建处理器
processor = SBUSProcessor()

# 解码传入数据
frame = processor.process_incoming(raw_bytes)
if frame:
    print(f"通道1: {frame.channels[0]}")

# 创建并编码帧
frame = processor.create_frame([1000]*16)
data = processor.frame_to_bytes(frame)
```

#### 以太网通信 (ethernet.py)

```python
from src.hardware.ethernet import AsyncEthernetComm, EthernetConfig

# 异步方式
comm = AsyncEthernetComm(EthernetConfig(host="192.168.1.100", port=8080))
await comm.connect()
await comm.send(b"data")
data = await comm.receive()
await comm.disconnect()
```

### 图像处理模块 (image/)

#### 二维码识别 (qr_code.py)

```python
from src.image.qr_code import QRCodeDecoder, preprocess_image

decoder = QRCodeDecoder()

# 从文件识别
codes = decoder.decode_image("path/to/image.jpg")

# 从字节数据识别
codes = decoder.decode_bytes(image_bytes)

# 图像预处理后识别
from src.image.qr_code import preprocess_image
img = preprocess_image("path/to/image.jpg", grayscale=True, denoise=True)
codes = decoder.decode_frame(img)
```

### 业务服务层 (services/)

#### 巡检服务 (inspection_service.py)

```python
from src.services.inspection_service import InspectionService

# 创建服务实例
service = InspectionService(db)

# 处理二维码
codes = service.process_qr_code("path/to/image.jpg")

# 创建巡检记录
record = service.create_inspection_record(
    drone_id=1,
    record_code="REC-001",
    qr_codes=["QR-001"],
    rfid_tags=["RFID-001"],
    shelf_id=1
)

# 推送到消息队列
service.push_to_queue("inspection_data", {"type": "qr_code", "data": codes})
```

### API路由 (api/)

#### 添加新接口

在 `api/` 目录下创建新的路由文件，例如 `shelves.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.db.database import get_db
from src.schemas.schemas import ShelfCreate, ShelfResponse

router = APIRouter(prefix="/shelves", tags=["货架管理"])

@router.post("/", response_model=ShelfResponse)
def create_shelf(shelf: ShelfCreate, db: Session = Depends(get_db)):
    # 实现逻辑
    pass
```

然后在 `main.py` 中注册路由:

```python
from .api import shelves
app.include_router(shelves.router, prefix="/api/v1")
```

### 数据模型 (models/)

#### 添加新表

1. 在 `models/models.py` 中添加模型类:

```python
class NewModel(Base):
    __tablename__ = "new_models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

2. 运行迁移创建表:

```bash
# 自动创建所有表
python -c "from src.db.database import init_db; init_db()"
```

### Schemas (schemas/)

#### 定义请求/响应模型

```python
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class NewModelBase(BaseModel):
    name: str

class NewModelCreate(NewModelBase):
    pass

class NewModelUpdate(BaseModel):
    name: Optional[str] = None

class NewModelResponse(NewModelBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
```

## 数据库操作

### 创建会话

```python
from src.db.database import get_db

# FastAPI依赖注入方式
@router.get("/items")
def get_items(db: Session = Depends(get_db)):
    items = db.query(Item).all()
    return items
```

### 基础CRUD操作

```python
# 查询
item = db.query(Item).filter(Item.id == 1).first()

# 创建
new_item = Item(name="test")
db.add(new_item)
db.commit()
db.refresh(new_item)

# 更新
item.name = "updated"
db.commit()

# 删除
db.delete(item)
db.commit()
```

### 使用Redis

```python
from src.db.redis import redis_client, RedisStream

# 初始化连接
redis_client.connect()

# 基本操作
redis_client.set("key", "value", ex=3600)  # 1小时过期
value = redis_client.get("key")
redis_client.delete("key")

# JSON操作
redis_client.set_json("data", {"name": "test"})
data = redis_client.get_json("data")

# Stream队列
stream = RedisStream(redis_client.client)
stream.xadd("my_stream", {"type": "event", "data": "value"})
messages = stream.xread({"my_stream": "0"}, count=10)
```

## 下一步开发任务清单

### P0 - 核心功能（必须实现）

- [ ] 实现巡检记录CRUD API
- [ ] 实现无人机CRUD API
- [ ] 实现货架CRUD API
- [ ] 实现RFID标签CRUD API
- [ ] 实现任务管理CRUD API
- [ ] 完善数据接收网关逻辑
- [ ] 实现二维码处理完整流程
- [ ] 实现RFID数据解析
- [ ] 实现数据比对逻辑
- [ ] 编写单元测试

### P1 - 重要功能

- [ ] 添加WebSocket支持实时推送
- [ ] 实现消息队列消费者(Worker)
- [ ] 添加图片上传接口
- [ ] 实现日志记录中间件
- [ ] 添加API认证授权

### P2 - 增强功能

- [ ] 创建前端管理界面
- [ ] 实现巡检数据统计报表
- [ ] 添加地图可视化
- [ ] 实现无人机路径规划
- [ ] 添加告警通知功能

## 代码规范

### Python代码风格

遵循PEP 8规范，使用black格式化代码:

```bash
pip install black
black src/
```

### 类型提示

所有函数应包含类型提示:

```python
def process_data(data: str, count: int = 10) -> Optional[dict]:
    pass
```

### 日志记录

```python
import logging

logger = logging.getLogger(__name__)

logger.info("信息日志")
logger.warning("警告日志")
logger.error("错误日志", exc_info=True)
```

## 测试

### 运行测试

```bash
# 安装测试依赖
pip install pytest pytest-asyncio

# 运行所有测试
pytest

# 运行指定测试
pytest tests/test_inspection.py -v
```

### 编写测试

```python
import pytest
from src.services.inspection_service import InspectionService

def test_qr_code_processing():
    service = InspectionService(db)
    codes = service.process_qr_code("tests/fixtures/qr_test.png")
    assert len(codes) > 0
```

## 部署检查清单

1. 修改默认密码
2. 配置生产环境CORS
3. 启用HTTPS
4. 配置日志级别为INFO
5. 设置数据库连接池
6. 配置Redis持久化
7. 添加监控和告警

## 常见问题

### Q: 串口无法连接？
A: 检查端口权限(Linux: `sudo chmod 666 /dev/ttyUSB0`)

### Q: OpenCV找不到图像？
A: 确保使用绝对路径，Windows路径需要双反斜杠

### Q: Redis连接失败？
A: 检查Docker是否运行，端口是否被占用
