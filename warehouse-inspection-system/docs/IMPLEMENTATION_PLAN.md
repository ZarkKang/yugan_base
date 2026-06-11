# 仓库巡检系统 - 完整实现方案

> 无人机端（Jetson）：图像采集 + 实时图传（192.168.1.201）
> 基站端（Edge Server）：二维码识别 + 数据入库（192.168.1.200:8000）

---

## 一、系统架构

```
┌───────────────────────────────────────────────────────────────────┐
│                        局域网 (192.168.1.x)                         │
│                                                                    │
│  ┌────────────────────────────┐      ┌─────────────────────────┐ │
│  │  无人机端 (Jetson NX)       │      │  基站端 (Edge Server)    │ │
│  │  192.168.1.201             │◄────►│  192.168.1.200:8000     │ │
│  │                            │ HTTP │                         │ │
│  │  • 摄像头采集               │ 文件  │  • FastAPI 后端          │ │
│  │  • 激光雷达避障             │ 上传  │  • PostgreSQL 数据库     │ │
│  │  • SBUS 飞行控制            │ WebSocket │  • Redis 缓存        │ │
│  │  • 数据上传节点             │  图传  │  • 二维码识别服务        │ │
│  │                            │       │  • 巡检任务管理          │ │
│  └────────────────────────────┘      └─────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

**核心设计：无人机仅负责图像采集和视频图传，二维码识别与数据入库全部在基站端处理。**

---

## 二、数据流程图

```
无人机端 (192.168.1.201)
│
├── 获取巡检任务        GET /api/drones/{id}/tasks/available
├── 心跳上报            POST /api/drones/heartbeat (每5秒)
│
├── 图像采集循环
│   ├── 到达航点 → 采集 1-3 张高清图像
│   ├── 上传图像到基站   POST /api/images/upload (multipart/form-data)
│   │   └── 附带: 航点ID、位置、角度、时间戳、采集索引
│   ├── 接收基站响应: 图像已接收 → {image_id, status:"pending"}
│   └── 可选: 轮询识别结果  GET /api/images/{image_id}/result
│
└── 实时图传流 (WebSocket)
    └── ws://192.168.1.200:8000/ws/video/{drone_id}
        └── 持续发送 JPEG 帧 → 基站中继给前端监控

基站端 (192.168.1.200:8000)
│
├── POST /api/images/upload
│   ├── 接收 multipart 文件 (图像 + 元数据)
│   ├── 保存文件:  storage/images/{task_id}/{drone_id}/{waypoint_id}_{index}.jpg
│   ├── 写入 image_records 表 (status: "pending")
│   └── 触发后台 Worker: 异步二维码识别
│
├── 异步识别 Worker
│   ├── 读取待识别图像 (image_records where status="pending")
│   ├── 图像预处理: 去模糊 / 对比度增强 / 多尺度
│   ├── WeChatQRCode 解码 (cv2.wechat_qrcode)
│   ├── pyzbar 备用解码
│   ├── 图像质量评分 (Laplacian 方差)
│   └── 更新 image_records (status="processed", qr_data, confidence, quality)
│
├── 数据入库 (识别完成后)
│   ├── 从二维码解析 SKU
│   ├── 与巡检任务的预期货架比对
│   ├── 异常判定: normal / misplaced / extra / missing / duplicate
│   └── 写入 inventory_items 表
│
└── 巡检报告生成
    └── 汇总该任务的所有识别结果 → 异常清单 + 证据图
```

---

## 三、目录结构

```
warehouse-inspection-system/
├── backend/
│   ├── src/
│   │   ├── main.py                          # FastAPI 入口 (已有, 需扩展)
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── drones.py                    # 无人机管理 (已有)
│   │   │   ├── gateway.py                   # 网关 (已有)
│   │   │   ├── inspection.py                # 巡检管理 (已有, 需扩展)
│   │   │   └── images.py                    # 图像上传与识别 (新增)
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── config.py                    # 配置 (已有)
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── database.py                  # 数据库连接 (已有)
│   │   │   └── redis.py                     # Redis (已有)
│   │   ├── hardware/
│   │   │   ├── __init__.py
│   │   │   ├── ethernet.py                  # 以太网通信 (已有)
│   │   │   ├── sbus.py                      # SBUS 控制 (已有)
│   │   │   └── serial.py                    # 串口 (已有)
│   │   ├── image/
│   │   │   ├── __init__.py
│   │   │   ├── crop.py                      # 图像裁切 (已有)
│   │   │   ├── qr_code.py                   # 二维码识别 (已有, 需重写)
│   │   │   └── qr_worker.py                 # 异步识别 Worker (新增)
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── models.py                    # 数据模型 (已有, 需扩展)
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py                   # 请求/响应 schema (已有, 需扩展)
│   │   └── services/
│   │       ├── __init__.py
│   │       └── inspection_service.py        # 巡检业务 (已有, 需扩展)
│   ├── requirements.txt                     # 依赖 (需新增: opencv pyzbar)
│   ├── Dockerfile                           # Docker 镜像 (已有)
│   └── docker-compose.yml                   # 部署 (已有)
│
├── frontend/
│   └── index.html                           # 前端监控页面 (已有)
│
└── docs/
    ├── development_guide.md                 # 开发指南 (已有)
    ├── database_schema.md                   # 数据库 Schema (已有)
    └── IMPLEMENTATION_PLAN.md               # 本文档 (本文件)
```

---

## 四、数据库 Schema 扩展

在现有 `models/models.py` 基础上增加以下表：

```python
# ============================================================
# 已有表（无需修改）: users, drone_devices, inspection_tasks
# ============================================================

# ============================================================
# 新增表
# ============================================================

# 1. 航点表 (waypoints) — 每个巡检任务包含多个航点
# 2. 图像记录 (image_records) — 无人机上传的每张图像
# 3. 库存物品 (inventory_items) — 识别后自动入库
# 4. 巡检报告 (inspection_reports) — 任务完成后生成
```

**详细 SQL：**

```sql
-- 航点表: 每个巡检任务包含多个航点
CREATE TABLE IF NOT EXISTS waypoints (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) REFERENCES inspection_tasks(id) ON DELETE CASCADE,
    position_x REAL DEFAULT 0,
    position_y REAL DEFAULT 0,
    position_z REAL DEFAULT 0,
    camera_angle REAL DEFAULT 45.0,
    expected_sku VARCHAR(128),
    expected_location VARCHAR(256),
    status VARCHAR(16) DEFAULT 'pending',   -- pending / scanning / completed / aborted
    sort_order INTEGER DEFAULT 0,
    scanned_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_waypoints_task ON waypoints(task_id);

-- 图像记录表: 无人机上传的每张图像
CREATE TABLE IF NOT EXISTS image_records (
    id VARCHAR(128) PRIMARY KEY,              -- img_{时间戳}_{随机8位}
    drone_id VARCHAR(64) REFERENCES drone_devices(id),
    task_id VARCHAR(64) REFERENCES inspection_tasks(id) ON DELETE CASCADE,
    waypoint_id VARCHAR(64) REFERENCES waypoints(id),

    -- 文件存储
    file_path VARCHAR(512),                    -- 本地路径: storage/images/task_id/drone_id/xxx.jpg
    file_name VARCHAR(256),
    file_size INTEGER,
    file_format VARCHAR(8) DEFAULT 'jpeg',

    -- 采集元数据 (无人机上传)
    position_x REAL,
    position_y REAL,
    position_z REAL,
    camera_angle REAL,
    capture_index INTEGER DEFAULT 0,           -- 同一航点第几张 (0/1/2)
    rfid_tags VARCHAR(256),                    -- JSON 数组字符串，可选

    -- 识别状态
    status VARCHAR(16) DEFAULT 'pending',     -- pending / processing / processed / failed
    queued_at TIMESTAMP,
    processing_started_at TIMESTAMP,
    processed_at TIMESTAMP,
    error_message VARCHAR(512),

    -- 识别结果 (由 QR 识别 Worker 写入)
    qr_data VARCHAR(256),                       -- 二维码解码内容
    confidence REAL,                            -- 0-1 置信度
    image_quality_score REAL,                   -- 拉普拉斯方差 (图像清晰度)
    decoder_used VARCHAR(32),                   -- wechat_qrcode / pyzbar / none

    -- 入库状态 (识别后的业务判定)
    inventory_status VARCHAR(16),               -- normal / misplaced / extra / missing / duplicate
    expected_sku VARCHAR(128),                   -- 来自 waypoints.expected_sku
    inventory_message VARCHAR(512),              -- 业务说明

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_images_task ON image_records(task_id);
CREATE INDEX IF NOT EXISTS idx_images_waypoint ON image_records(waypoint_id);
CREATE INDEX IF NOT EXISTS idx_images_status ON image_records(status);

-- 库存物品表: 识别成功后自动入库，用于报告/统计
CREATE TABLE IF NOT EXISTS inventory_items (
    id VARCHAR(128) PRIMARY KEY,
    task_id VARCHAR(64) REFERENCES inspection_tasks(id) ON DELETE CASCADE,
    waypoint_id VARCHAR(64) REFERENCES waypoints(id),
    image_id VARCHAR(128) REFERENCES image_records(id),

    sku VARCHAR(128),                            -- 识别出的 SKU
    expected_sku VARCHAR(128),                   -- 预期 SKU
    expected_location VARCHAR(256),

    position_x REAL,
    position_y REAL,
    position_z REAL,

    status VARCHAR(16),                           -- normal / misplaced / extra / missing / duplicate
    message VARCHAR(512),

    confidence REAL,
    source_qr_data VARCHAR(256),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_inventory_task ON inventory_items(task_id);
CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory_items(sku);

-- 巡检报告: 任务完成后汇总
CREATE TABLE IF NOT EXISTS inspection_reports (
    id VARCHAR(128) PRIMARY KEY,
    task_id VARCHAR(64) REFERENCES inspection_tasks(id) ON DELETE CASCADE,
    warehouse_id VARCHAR(64),

    -- 统计汇总
    total_waypoints INTEGER,
    total_images INTEGER,
    total_recognized INTEGER,
    total_failed INTEGER,

    -- 状态分类统计
    normal_count INTEGER DEFAULT 0,
    misplaced_count INTEGER DEFAULT 0,
    missing_count INTEGER DEFAULT 0,
    extra_count INTEGER DEFAULT 0,
    duplicate_count INTEGER DEFAULT 0,

    accuracy REAL,                                 -- 识别准确率

    -- 异常明细 (JSON 数组)
    details TEXT,                                  -- JSON: [{sku, location, status, message, image_id}]

    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    generated_by VARCHAR(128)
);
CREATE INDEX IF NOT EXISTS idx_reports_task ON inspection_reports(task_id);
```

---

## 五、后端 API 扩展

### 5.1 已存在的 API (保持不变)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/drones` | 注册无人机 |
| GET | `/api/drones` | 无人机列表 |
| POST | `/api/drones/heartbeat` | 心跳上报 |
| POST | `/api/inspection/tasks` | 创建巡检任务 |
| GET | `/api/inspection/tasks` | 任务列表 |
| GET | `/api/inspection/tasks/{id}` | 任务详情 |

### 5.2 新增 API

```
┌──────────────────────────────────────────────────────────────┐
│  图像管理 (image_router)                                      │
├──────────────────────────────────────────────────────────────┤
│  POST /api/images/upload                接收无人机上传图像     │
│  GET  /api/images/{image_id}            获取图像元信息         │
│  GET  /api/images/{image_id}/file       下载图像文件           │
│  GET  /api/images/{image_id}/result     获取识别结果 (轮询)    │
│  GET  /api/images/task/{task_id}        任务的所有图像列表     │
│  POST /api/images/{image_id}/retry      手动重新识别           │
│                                                              │
│  (multipart/form-data) 上传字段:                              │
│    • image          File (JPEG/PNG)                           │
│    • drone_id       string                                   │
│    • task_id        string                                   │
│    • waypoint_id    string                                   │
│    • position_x     float                                    │
│    • position_y     float                                    │
│    • position_z     float                                    │
│    • camera_angle   float                                    │
│    • capture_index  int (0/1/2)                              │
│    • timestamp      string (ISO8601)                         │
│    • rfid_tags      string (JSON, 可选)                       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  任务/航点扩展 (inspection_router)                            │
├──────────────────────────────────────────────────────────────┤
│  GET  /api/drones/{id}/tasks/available   无人机获取可用任务   │
│  POST /api/drones/{id}/tasks/{task_id}/accept  接收任务       │
│  GET  /api/inspection/tasks/{task_id}/waypoints  获取航点列表 │
│  POST /api/inspection/tasks/{task_id}/progress  上报进度      │
│  POST /api/inspection/tasks/{task_id}/complete  标记任务完成 │
│  POST /api/inspection/tasks/{task_id}/report    生成报告      │
│  GET  /api/inspection/reports/{report_id}         获取报告    │
│  GET  /api/inspection/reports/{report_id}/export  导出报告    │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│  WebSocket (实时图传 + 识别结果推送)                           │
├──────────────────────────────────────────────────────────────┤
│  ws://host:8000/ws/video/{drone_id}     接收无人机视频流       │
│  ws://host:8000/ws/monitor              前端监控订阅所有消息   │
│  ws://host:8000/ws/results/{task_id}    推送该任务识别结果     │
└──────────────────────────────────────────────────────────────┘
```

---

## 六、新增/修改的核心文件

### 6.1 `api/images.py`（新增）— 图像上传与识别接口

```python
"""
图像管理路由:
  POST /api/images/upload                接收无人机上传 (multipart)
  GET  /api/images/{image_id}            元信息
  GET  /api/images/{image_id}/file       下载文件
  GET  /api/images/{image_id}/result     获取识别结果 (供无人机轮询)
  GET  /api/images/task/{task_id}        任务所有图像
  POST /api/images/{image_id}/retry      手动重新识别
"""

import os
import shutil
import uuid
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models.models import DroneDevice, InspectionTask, Waypoint, ImageRecord
from ..image.qr_worker import get_recognition_engine

router = APIRouter(prefix="/api/images", tags=["图像管理"])

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
IMAGES_DIR = os.path.join(STORAGE_ROOT, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


@router.post("/upload")
async def upload_image(
    image: UploadFile = File(...),
    drone_id: str = Form(...),
    task_id: str = Form(...),
    waypoint_id: str = Form(...),
    position_x: float = Form(0.0),
    position_y: float = Form(0.0),
    position_z: float = Form(0.0),
    camera_angle: float = Form(45.0),
    capture_index: int = Form(0),
    timestamp: Optional[str] = Form(None),
    rfid_tags: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # 1. 校验任务/航点/无人机是否存在
    task = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    wp = db.query(Waypoint).filter(Waypoint.id == waypoint_id).first()
    if not wp:
        raise HTTPException(status_code=404, detail=f"航点不存在: {waypoint_id}")

    # 2. 保存图像文件
    image_id = f"img_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task_dir = os.path.join(IMAGES_DIR, task_id, drone_id)
    os.makedirs(task_dir, exist_ok=True)
    file_name = f"{image_id}_{image.filename or 'image.jpg'}"
    file_path = os.path.join(task_dir, file_name)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    file_size = os.path.getsize(file_path)

    # 3. 写入数据库
    try:
        record = ImageRecord(
            id=image_id,
            drone_id=drone_id,
            task_id=task_id,
            waypoint_id=waypoint_id,
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_format="jpeg",
            position_x=position_x,
            position_y=position_y,
            position_z=position_z,
            camera_angle=camera_angle,
            capture_index=capture_index,
            rfid_tags=rfid_tags,
            status="pending",
            queued_at=datetime.utcnow(),
            expected_sku=wp.expected_sku,
        )
        db.add(record)
        task.pending_count = (task.pending_count or 0) + 1  # 扩展字段
        db.commit()
    except Exception as e:
        db.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"写入数据库失败: {e}")

    # 4. 触发异步识别
    try:
        engine = get_recognition_engine()
        engine.submit(image_id, file_path, expected_sku=wp.expected_sku)
    except Exception as e:
        print(f"[警告] 触发识别失败 (将由定时任务兜底): {e}")

    return {
        "image_id": image_id,
        "status": "pending",
        "file_name": file_name,
        "file_size": file_size,
        "message": "图像已接收，正在后台识别二维码",
    }


@router.get("/{image_id}/result")
async def get_result(image_id: str, db: Session = Depends(get_db)):
    """供无人机轮询识别结果。"""
    r = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="图像不存在")

    if r.status in ("pending", "processing"):
        return {
            "image_id": r.id,
            "status": r.status,
            "qr_data": None,
            "confidence": 0,
            "image_quality": None,
            "decoder_used": None,
            "inventory_status": None,
            "expected_sku": r.expected_sku,
            "message": "处理中，请继续轮询",
        }

    return {
        "image_id": r.id,
        "status": r.status,
        "qr_data": r.qr_data,
        "confidence": r.confidence or 0,
        "image_quality": r.image_quality_score,
        "decoder_used": r.decoder_used,
        "inventory_status": r.inventory_status,
        "expected_sku": r.expected_sku,
        "message": r.inventory_message or "",
    }


@router.get("/{image_id}/file")
async def download_image(image_id: str, db: Session = Depends(get_db)):
    r = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not r or not os.path.exists(r.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path=r.file_path, filename=r.file_name, media_type="image/jpeg")


@router.get("/task/{task_id}")
async def list_task_images(task_id: str, db: Session = Depends(get_db)):
    images = (
        db.query(ImageRecord)
        .filter(ImageRecord.task_id == task_id)
        .order_by(ImageRecord.created_at.desc())
        .all()
    )
    return [
        {
            "image_id": img.id,
            "waypoint_id": img.waypoint_id,
            "capture_index": img.capture_index,
            "status": img.status,
            "qr_data": img.qr_data,
            "confidence": img.confidence,
            "inventory_status": img.inventory_status,
            "file_size": img.file_size,
            "created_at": img.created_at.isoformat() if img.created_at else None,
        }
        for img in images
    ]


@router.post("/{image_id}/retry")
async def retry_recognition(image_id: str, db: Session = Depends(get_db)):
    r = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not r or not os.path.exists(r.file_path):
        raise HTTPException(status_code=404, detail="图像不存在")
    r.status = "pending"
    r.queued_at = datetime.utcnow()
    db.commit()
    try:
        engine = get_recognition_engine()
        engine.submit(r.id, r.file_path, expected_sku=r.expected_sku)
    except Exception as e:
        print(f"[警告] 重新触发失败: {e}")
    return {"image_id": r.id, "status": "pending", "message": "已重新提交识别"}
```

### 6.2 `image/qr_worker.py`（新增）— 异步识别引擎

```python
"""
二维码识别引擎（后台 Worker）

使用:
  • OpenCV 的 WeChatQRCode (主要) — 对模糊/变形图像更鲁棒
  • pyzbar (备用) — 对标准 QR 码识别速度快
  • 图像质量评分: Laplacian 方差

设计:
  1. 启动时初始化单例 engine
  2. 每次图像上传时调用 engine.submit(image_id, file_path, ...)
  3. 后台线程异步处理，完成后更新数据库并触发入库逻辑
  4. 定时任务兜底: 每 30 秒扫描一次 status="pending" 的图像
"""

import os
import cv2
import threading
import time
import queue
import numpy as np
from datetime import datetime
from typing import Optional, Tuple, List

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

from ..db.database import SessionLocal
from ..models.models import ImageRecord, Waypoint, InspectionTask, InventoryItem

# 全局单例，首次使用时懒初始化
_engine_instance = None


class QRRecognitionEngine:
    def __init__(self, max_workers: int = 2):
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._wechat = None
        self._init_lock = threading.Lock()
        self._threads: List[threading.Thread] = []
        self._running = True

        # 启动 worker 线程
        for i in range(max_workers):
            t = threading.Thread(target=self._worker, name=f"qr-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

        # 启动兜底扫描线程
        t = threading.Thread(target=self._rescue_worker, name="qr-rescue", daemon=True)
        t.start()
        self._threads.append(t)

        print("[QR引擎] 已启动 (workers=%d, pyzbar=%s)" % (max_workers, HAS_PYZBAR))

    # ------------------------------
    # 懒初始化 WeChatQRCode
    # ------------------------------
    def _get_wechat(self):
        if self._wechat is None:
            with self._init_lock:
                if self._wechat is None:
                    try:
                        # 不使用模型文件（纯 CPU 识别，兼容性好）
                        self._wechat = cv2.wechat_qrcode_WeChatQRCode()
                    except Exception as e:
                        print(f"[QR引擎] WeChatQRCode 不可用: {e}，将仅使用 pyzbar")
                        self._wechat = "disabled"
        return self._wechat if self._wechat != "disabled" else None

    # ------------------------------
    # 提交识别任务
    # ------------------------------
    def submit(self, image_id: str, file_path: str, expected_sku: Optional[str] = None):
        self._queue.put({
            "image_id": image_id,
            "file_path": file_path,
            "expected_sku": expected_sku,
            "submitted_at": time.time(),
        })

    # ------------------------------
    # Worker 线程主循环
    # ------------------------------
    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=5)
            except queue.Empty:
                continue
            try:
                self._process_one(item)
            except Exception as e:
                print(f"[QR引擎] 处理异常 ({item.get('image_id')}): {e}")
                self._mark_failed(item["image_id"], str(e))
            finally:
                self._queue.task_done()

    def _rescue_worker(self):
        """每 30 秒扫描 status="pending" 且超时的图像，重新入队。"""
        while self._running:
            time.sleep(30)
            try:
                db = SessionLocal()
                try:
                    threshold = datetime.utcnow().timestamp() - 60  # 60s 前的都算卡住
                    pending = (
                        db.query(ImageRecord)
                        .filter(ImageRecord.status == "pending")
                        .filter(
                            (ImageRecord.queued_at.is_(None))
                            | (ImageRecord.queued_at < datetime.fromtimestamp(threshold))
                        )
                        .limit(50)
                        .all()
                    )
                    for img in pending:
                        if os.path.exists(img.file_path):
                            self._queue.put({
                                "image_id": img.id,
                                "file_path": img.file_path,
                                "expected_sku": img.expected_sku,
                                "submitted_at": time.time(),
                            })
                            img.queued_at = datetime.utcnow()
                    db.commit()
                    if pending:
                        print(f"[QR引擎] 兜底扫描: 重新入队 {len(pending)} 张")
                finally:
                    db.close()
            except Exception as e:
                print(f"[QR引擎] 兜底扫描异常: {e}")

    # ------------------------------
    # 核心识别逻辑
    # ------------------------------
    def _process_one(self, item: dict):
        image_id = item["image_id"]
        file_path = item["file_path"]
        expected_sku = item["expected_sku"]

        if not os.path.exists(file_path):
            self._mark_failed(image_id, "文件不存在")
            return

        # 1. 标记 processing
        db = SessionLocal()
        try:
            record = db.query(ImageRecord).filter(ImageRecord.id == image_id).with_for_update().first()
            if not record:
                return
            if record.status in ("processed", "failed"):
                return  # 已处理过
            record.status = "processing"
            record.processing_started_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        # 2. 读取图像
        img = cv2.imread(file_path)
        if img is None:
            self._mark_failed(image_id, "无法读取图像 (可能已损坏)")
            return

        # 3. 质量评分 (Laplacian 方差)
        quality = self._score_quality(img)

        # 4. 多尺度 + 多解码器尝试
        qr_text, confidence, decoder = self._try_decode(img)

        # 5. 若主识别失败，且图像质量较差，尝试预处理后再试
        if not qr_text and quality < 100.0:
            enhanced = self._preprocess(img)
            qr_text2, confidence2, decoder2 = self._try_decode(enhanced)
            if qr_text2:
                qr_text, confidence, decoder = qr_text2, confidence2, decoder2 + "+enhanced"

        # 6. 写入结果并触发入库
        db = SessionLocal()
        try:
            record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
            if not record:
                return

            record.status = "processed"
            record.processed_at = datetime.utcnow()
            record.qr_data = qr_text
            record.confidence = confidence
            record.image_quality_score = quality
            record.decoder_used = decoder or "none"

            # 7. 业务判定与入库
            inventory_status = "missing"
            inventory_message = "未识别到二维码"
            if qr_text:
                inventory_status, inventory_message = self._classify_inventory(
                    qr_text, expected_sku, record.waypoint_id, db
                )
                # 正常/错位/多货 → 写入 inventory_items
                if inventory_status in ("normal", "misplaced", "extra", "duplicate"):
                    self._insert_inventory_item(record, qr_text, inventory_status, inventory_message, confidence, db)

            record.inventory_status = inventory_status
            record.inventory_message = inventory_message
            db.commit()

            # 8. 更新任务计数
            self._update_task_counts(record.task_id, db)

            print(
                f"[QR引擎] {image_id} → SKU={qr_text or 'N/A'} "
                f"decoder={decoder} quality={quality:.1f} "
                f"status={inventory_status}"
            )
        finally:
            db.close()

    # ------------------------------
    # 质量评分
    # ------------------------------
    def _score_quality(self, img: np.ndarray) -> float:
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            return float(laplacian_var)
        except Exception:
            return 0.0

    # ------------------------------
    # 多尺度 + 多解码器
    # ------------------------------
    def _try_decode(self, img: np.ndarray) -> Tuple[Optional[str], float, Optional[str]]:
        # 多尺度: 原始 + 放大1.5x + 缩小0.7x
        scales = [1.0, 1.5, 0.7]
        for scale in scales:
            if scale != 1.0:
                resized = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            else:
                resized = img

            # 1) WeChatQRCode
            wechat = self._get_wechat()
            if wechat is not None:
                try:
                    decoded_texts, _, _, _ = wechat.detectAndDecode(resized)
                    for t in decoded_texts:
                        if isinstance(t, str) and t.strip():
                            return t.strip(), 0.95, "wechat_qrcode"
                        if isinstance(t, bytes):
                            s = t.decode("utf-8", errors="ignore").strip()
                            if s:
                                return s, 0.95, "wechat_qrcode"
                except Exception:
                    pass

            # 2) pyzbar
            if HAS_PYZBAR:
                try:
                    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(resized.shape) == 3 else resized
                    results = pyzbar_decode(gray)
                    if results:
                        data = results[0].data.decode("utf-8", errors="ignore").strip()
                        if data:
                            return data, float(results[0].quality) / 100.0, "pyzbar"
                except Exception:
                    pass

        return None, 0.0, None

    # ------------------------------
    # 图像预处理 (去模糊 + 对比度增强)
    # ------------------------------
    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        # 1) 自适应阈值二值化
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        # 2) 轻度锐化
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharp = cv2.filter2D(thresh, -1, kernel)
        return sharp

    # ------------------------------
    # 库存业务判定
    # ------------------------------
    def _classify_inventory(self, qr_text: str, expected_sku: Optional[str],
                             waypoint_id: str, db) -> Tuple[str, str]:
        """
        简单判定逻辑 (可调优):
          - 若航点有预期 SKU (expected_sku):
              * QR == expected_sku → normal
              * QR 已在该任务其他位置出现过 → duplicate
              * QR 存在但与预期不符 → misplaced
          - 若航点无预期 SKU:
              * QR 已在该任务其他位置出现过 → duplicate
              * 否则 → extra (多货)
        """
        if not expected_sku:
            # 无预期: 检查是否重复
            wp = db.query(Waypoint).filter(Waypoint.id == waypoint_id).first()
            if wp and wp.task_id:
                exists = (
                    db.query(ImageRecord)
                    .filter(ImageRecord.task_id == wp.task_id)
                    .filter(ImageRecord.qr_data == qr_text)
                    .filter(ImageRecord.id != wp.id)
                    .limit(1)
                    .first()
                )
                if exists:
                    return "duplicate", f"SKU {qr_text} 已在其他位置识别过"
            return "extra", f"无预期SKU，识别到 {qr_text}，标记为多货"

        if qr_text == expected_sku:
            return "normal", "SKU与预期一致，位置正确"

        # 不一致 → 错位
        return "misplaced", f"预期 {expected_sku}，实际 {qr_text}"

    # ------------------------------
    # 写入 inventory_items
    # ------------------------------
    def _insert_inventory_item(self, record: ImageRecord, qr_text: str,
                                status: str, message: str, confidence: float, db):
        item = InventoryItem(
            id=f"inv_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{os.urandom(4).hex()}",
            task_id=record.task_id,
            waypoint_id=record.waypoint_id,
            image_id=record.id,
            sku=qr_text,
            expected_sku=record.expected_sku,
            expected_location="",
            position_x=record.position_x,
            position_y=record.position_y,
            position_z=record.position_z,
            status=status,
            message=message,
            confidence=confidence,
            source_qr_data=qr_text,
        )
        db.add(item)

    # ------------------------------
    # 更新任务统计
    # ------------------------------
    def _update_task_counts(self, task_id: str, db):
        task = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
        if not task:
            return
        all_images = db.query(ImageRecord).filter(ImageRecord.task_id == task_id).all()
        task.total_images = len(all_images)
        task.total_recognized = sum(1 for i in all_images if i.qr_data)
        task.total_failed = sum(1 for i in all_images if i.status == "failed")

    # ------------------------------
    # 标记失败
    # ------------------------------
    def _mark_failed(self, image_id: str, error: str):
        db = SessionLocal()
        try:
            r = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
            if r:
                r.status = "failed"
                r.error_message = error
                r.processed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()


def get_recognition_engine() -> QRRecognitionEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = QRRecognitionEngine(max_workers=2)
    return _engine_instance
```

### 6.3 `api/inspection.py`（修改）— 扩展任务与航点

在现有 `api/inspection.py` 中新增/修改以下路由：

```python
# ========== 新增内容 ==========

# 1. 无人机获取可执行任务列表
@router.get("/api/drones/{drone_id}/tasks/available")
async def get_available_tasks(drone_id: str, db: Session = Depends(get_db)):
    """无人机请求可执行任务 (status == 'pending' 且分配给该无人机或未分配)"""
    tasks = (
        db.query(InspectionTask)
        .filter(
            (InspectionTask.status == "pending")
            & (
                (InspectionTask.drone_id == drone_id)
                | (InspectionTask.drone_id.is_(None))
            )
        )
        .order_by(InspectionTask.created_at.desc())
        .limit(5)
        .all()
    )
    return [
        {
            "task_id": t.id,
            "warehouse_id": t.warehouse_id,
            "status": t.status,
            "total_waypoints": t.total_waypoints or 0,
            "scheduled_at": t.scheduled_at.isoformat() if t.scheduled_at else None,
            "description": t.description or "",
        }
        for t in tasks
    ]


# 2. 无人机确认接收任务
@router.post("/api/drones/{drone_id}/tasks/{task_id}/accept")
async def accept_task(drone_id: str, task_id: str, db: Session = Depends(get_db)):
    t = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if t.status not in ("pending", "paused"):
        raise HTTPException(status_code=400, detail=f"任务状态 {t.status} 不可接收")
    t.drone_id = drone_id
    t.status = "in_progress"
    t.started_at = datetime.utcnow()
    db.commit()
    return {"task_id": t.id, "status": t.status, "message": "任务已接收"}


# 3. 获取任务的所有航点
@router.get("/api/inspection/tasks/{task_id}/waypoints")
async def get_task_waypoints(task_id: str, db: Session = Depends(get_db)):
    t = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    waypoints = (
        db.query(Waypoint)
        .filter(Waypoint.task_id == task_id)
        .order_by(Waypoint.sort_order.asc())
        .all()
    )
    return [
        {
            "waypoint_id": wp.id,
            "position": {"x": wp.position_x, "y": wp.position_y, "z": wp.position_z},
            "camera_angle": wp.camera_angle,
            "expected_sku": wp.expected_sku,
            "expected_location": wp.expected_location,
            "status": wp.status,
        }
        for wp in waypoints
    ]


# 4. 无人机上报任务进度
@router.post("/api/inspection/tasks/{task_id}/progress")
async def update_progress(task_id: str, payload: dict, db: Session = Depends(get_db)):
    t = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    t.scanned_waypoints = payload.get("scanned", t.scanned_waypoints)
    t.total_recognized = payload.get("recognized", t.total_recognized)
    db.commit()
    return {"ok": True}


# 5. 无人机标记任务完成
@router.post("/api/inspection/tasks/{task_id}/complete")
async def complete_task(task_id: str, payload: dict, db: Session = Depends(get_db)):
    t = db.query(InspectionTask).filter(InspectionTask.id == task_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    t.status = "completed"
    t.completed_at = datetime.utcnow()
    db.commit()
    # 异步生成报告
    try:
        from ..image.qr_worker import generate_report_for_task
        generate_report_for_task(task_id, db)
    except Exception as e:
        print(f"[警告] 自动生成报告失败: {e}")
    return {"ok": True, "task_id": task_id, "message": "任务已标记完成，正在生成报告"}
```

### 6.4 `models/models.py`（修改）— 扩展模型

```python
# ========== 新增表: Waypoint ==========
class Waypoint(Base):
    __tablename__ = "waypoints"
    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("inspection_tasks.id", ondelete="CASCADE"))
    position_x = Column(Float, default=0)
    position_y = Column(Float, default=0)
    position_z = Column(Float, default=0)
    camera_angle = Column(Float, default=45.0)
    expected_sku = Column(String(128))
    expected_location = Column(String(256))
    status = Column(String(16), default="pending")
    sort_order = Column(Integer, default=0)
    scanned_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id:
            self.id = f"wp_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"


# ========== 新增表: ImageRecord ==========
class ImageRecord(Base):
    __tablename__ = "image_records"
    id = Column(String(128), primary_key=True)
    drone_id = Column(String(64), ForeignKey("drone_devices.id"))
    task_id = Column(String(64), ForeignKey("inspection_tasks.id", ondelete="CASCADE"))
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"))
    file_path = Column(String(512))
    file_name = Column(String(256))
    file_size = Column(Integer)
    file_format = Column(String(8), default="jpeg")
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    camera_angle = Column(Float)
    capture_index = Column(Integer, default=0)
    rfid_tags = Column(String(256))
    status = Column(String(16), default="pending")
    queued_at = Column(DateTime)
    processing_started_at = Column(DateTime)
    processed_at = Column(DateTime)
    error_message = Column(String(512))
    qr_data = Column(String(256))
    confidence = Column(Float)
    image_quality_score = Column(Float)
    decoder_used = Column(String(32))
    inventory_status = Column(String(16))
    expected_sku = Column(String(128))
    inventory_message = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow)


# ========== 新增表: InventoryItem ==========
class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id = Column(String(128), primary_key=True)
    task_id = Column(String(64), ForeignKey("inspection_tasks.id", ondelete="CASCADE"))
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"))
    image_id = Column(String(128), ForeignKey("image_records.id"))
    sku = Column(String(128))
    expected_sku = Column(String(128))
    expected_location = Column(String(256))
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    status = Column(String(16))
    message = Column(String(512))
    confidence = Column(Float)
    source_qr_data = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id:
            self.id = f"inv_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}_{os.urandom(3).hex()}"


# ========== 新增表: InspectionReport ==========
class InspectionReport(Base):
    __tablename__ = "inspection_reports"
    id = Column(String(128), primary_key=True)
    task_id = Column(String(64), ForeignKey("inspection_tasks.id", ondelete="CASCADE"))
    warehouse_id = Column(String(64))
    total_waypoints = Column(Integer)
    total_images = Column(Integer)
    total_recognized = Column(Integer)
    total_failed = Column(Integer)
    normal_count = Column(Integer, default=0)
    misplaced_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    extra_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    accuracy = Column(Float)
    details = Column(Text)
    generated_at = Column(DateTime, default=datetime.utcnow)
    generated_by = Column(String(128))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.id:
            self.id = f"report_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}"


# ========== 扩展 InspectionTask 新增字段 ==========
# 在现有 InspectionTask 类中新增这些列（如果不存在）:
#   total_images = Column(Integer, default=0)
#   total_recognized = Column(Integer, default=0)
#   total_failed = Column(Integer, default=0)
#   pending_count = Column(Integer, default=0)
#   scanned_waypoints = Column(Integer, default=0)
#   started_at = Column(DateTime)
#   completed_at = Column(DateTime)
#   warehouse_id = Column(String(64))
```

### 6.5 `requirements.txt`（修改）— 新增依赖

```
# ========== 已有依赖 ==========
fastapi==0.110.0
uvicorn[standard]==0.29.0
SQLAlchemy==2.0.29
psycopg2-binary==2.9.9
redis==5.0.3
pydantic==2.6.4
python-dotenv==1.0.1
python-multipart==0.0.9
httpx==0.27.0
websockets==12.0
PyYAML==6.0.1
aiofiles==23.2.1

# ========== 新增: 图像处理与二维码识别 ==========
opencv-python-headless==4.9.0.80          # 含 cv2.wechat_qrcode_WeChatQRCode
pyzbar==0.1.9                              # 备用解码器
numpy==1.26.4                              # 图像运算

# ========== 可选: 若使用 GPU 加速识别 ==========
# opencv-contrib-python==4.9.0.80
```

---

## 七、前端页面扩展

在 `frontend/index.html` 中添加：

```html
<!-- ============ 图像列表 + 识别状态 ============ -->
<div class="panel">
  <h3>📷 图像识别状态</h3>
  <div class="section">
    <label>任务ID:</label>
    <select id="img-task-select">
      <option value="">-- 选择任务 --</option>
    </select>
    <button onclick="loadImages()" class="btn btn-primary">刷新</button>
  </div>
  <div class="grid gap-2" id="images-grid">
    <!-- 动态加载: 每张图像卡片显示缩略图 + SKU + 状态 -->
  </div>
</div>

<script>
async function loadImages() {
  const taskId = document.getElementById('img-task-select').value;
  if (!taskId) return;
  try {
    const resp = await fetch(`/api/images/task/${taskId}`);
    const images = await resp.json();
    const grid = document.getElementById('images-grid');
    grid.innerHTML = '';
    for (const img of images) {
      const card = document.createElement('div');
      card.className = 'card';
      const statusColor = {
        'pending': 'gray', 'processing': 'yellow',
        'processed': 'green', 'failed': 'red'
      }[img.status] || 'gray';
      card.innerHTML = `
        <div class="flex items-center gap-3">
          <img src="/api/images/${img.image_id}/file" width="120" height="80"
               style="border-radius:6px; object-fit:cover; background:#f3f4f6;"/>
          <div class="flex-1">
            <div><b>航点:</b> ${img.waypoint_id} (第 ${img.capture_index+1} 张)</div>
            <div><b>状态:</b> <span style="color:${statusColor}">${img.status}</span></div>
            <div><b>SKU:</b> ${img.qr_data || '<span style="color:#999">未识别</span>'}</div>
            <div><b>置信度:</b> ${(img.confidence || 0).toFixed(2)}</div>
            <div><b>库存:</b> ${img.inventory_status || '-'}</div>
          </div>
          <button onclick="retryImage('${img.image_id}')" class="btn btn-small">重新识别</button>
        </div>
      `;
      grid.appendChild(card);
    }
  } catch (e) { alert('加载失败: ' + e); }
}

async function retryImage(imageId) {
  await fetch(`/api/images/${imageId}/retry`, { method: 'POST' });
  setTimeout(loadImages, 2000);
}
</script>
```

---

## 八、部署与测试

### 8.1 基站端部署（192.168.1.200）

```bash
cd warehouse-inspection-system/backend

# 1) 安装依赖（在 Docker 中自动完成，或本地测试）
pip install -r requirements.txt

# 2) 启动数据库 + Redis + 后端
docker-compose up -d

# 3) 确认服务
curl http://192.168.1.200:8000/
# 应返回 {"message": "仓库巡检系统 API", "status": "running"}
```

### 8.2 模拟无人机上传（无真实无人机时）

```bash
# 使用 curl 模拟上传一张含二维码的测试图片
curl -X POST http://192.168.1.200:8000/api/images/upload \
  -F "image=@test_qr.jpg" \
  -F "drone_id=DRONE001" \
  -F "task_id=TASK001" \
  -F "waypoint_id=WP001" \
  -F "position_x=1.5" \
  -F "position_y=2.0" \
  -F "position_z=3.0" \
  -F "camera_angle=45.0" \
  -F "capture_index=0"

# 查看识别结果（几秒后）
curl http://192.168.1.200:8000/api/images/<返回的image_id>/result
```

### 8.3 无人机端部署（192.168.1.201）

遵循 `docs/development_guide.md` 中的 **机载系统** 指南。关键点：

- **网络**：确保能 `ping 192.168.1.200`
- **上传 API**：`POST http://192.168.1.200:8000/api/images/upload`
- **轮询接口**：`GET http://192.168.1.200:8000/api/images/{id}/result`

---

## 九、实现步骤总结

| 步骤 | 说明 | 重点文件 |
|------|------|---------|
| 1 | 扩展数据库 Schema | `models/models.py` |
| 2 | 实现图像上传接口 | `api/images.py` |
| 3 | 实现二维码识别 Worker | `image/qr_worker.py` |
| 4 | 扩展任务/航点 API | `api/inspection.py` |
| 5 | 添加依赖 | `requirements.txt` |
| 6 | 前端新增图像列表 | `frontend/index.html` |
| 7 | 测试: 模拟上传 | curl 测试脚本 |
| 8 | 联调: 无人机真实上传 | 真实 Jetson 部署 |

本方案重点利用**基站强大算力**做二维码识别，无人机仅负责采集。好处：
- 识别算法升级只需修改基站
- 可使用更重的模型 (WeChatQRCode / YOLO)
- 数据库集中管理，所有识别结果立即可查
- 图像证据全部保留，可事后复核
