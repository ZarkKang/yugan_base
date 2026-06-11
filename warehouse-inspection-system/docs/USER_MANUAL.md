# 仓库巡检系统 - 使用手册

> 版本：1.0  
> 更新日期：2024-01-01  

---

## 一、系统概述

仓库巡检系统由 **无人机端**（Jetson NX，192.168.1.201）和 **基站端**（Edge Server，192.168.1.200:8000）组成。

- **无人机端**：负责摄像采集、飞行控制、实时图传、图像上传
- **基站端**：负责二维码识别、数据入库、异常判定、报告生成

**核心设计：无人机只负责拍摄和上传图像，二维码识别全部在基站完成。**

---

## 二、网络拓扑

```
无人机 (192.168.1.201)  ─── 局域网 ───  基站 (192.168.1.200:8000)
    │                                        │
    ├── 摄像头采集                             ├── FastAPI 后端
    ├── 激光雷达避障                           ├── PostgreSQL 数据库
    ├── SBUS 飞行控制                          ├── 二维码识别引擎
    └── 图传上传                               └── 桌面监控应用
```

**前置条件：**
- 无人机可 ping 通基站：`ping 192.168.1.200`
- 基站防火墙已开放 8000 端口
- Docker 服务正常运行

---

## 三、快速开始

### 3.1 启动基站端

```bash
# 在基站服务器 (192.168.1.200) 上执行
cd warehouse-inspection-system/backend
docker-compose up -d

# 检查服务状态
curl http://192.168.1.200:8000/health
# 返回: {"status":"healthy","database":"connected","redis":"connected"}
```

### 3.2 创建巡检任务（基站操作员）

```bash
# 1. 创建任务
curl -X POST http://192.168.1.200:8000/api/v1/inspection/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_code": "TASK001",
    "task_name": "A区货架巡检",
    "task_type": "routine",
    "altitude": 5.0,
    "speed": 2.0
  }'

# 2. 添加航点
curl -X POST http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001/waypoints \
  -H "Content-Type: application/json" \
  -d '{
    "waypoints": [
      {
        "position_x": 1.0, "position_y": 2.0, "position_z": 3.0,
        "expected_sku": "SKU001",
        "expected_location": "A-01-03",
        "camera_angle": 45.0,
        "sort_order": 1
      },
      {
        "position_x": 2.0, "position_y": 2.0, "position_z": 3.0,
        "expected_sku": "SKU002",
        "expected_location": "A-02-01",
        "camera_angle": 45.0,
        "sort_order": 2
      }
    ]
  }'
```

### 3.3 无人机获取并执行任务

```bash
# 无人机端 (192.168.1.201) 执行:

# 1. 获取可用任务
curl http://192.168.1.200:8000/api/v1/drones/DRONE001/tasks/available

# 2. 接收任务
curl -X POST http://192.168.1.200:8000/api/v1/drones/DRONE001/tasks/TASK001/accept

# 3. 获取航点列表
curl http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001/waypoints

# 4. 上传图像（在航点拍摄后）
curl -X POST http://192.168.1.200:8000/api/v1/images/upload \
  -F "image=@capture.jpg" \
  -F "drone_code=DRONE001" \
  -F "task_code=TASK001" \
  -F "waypoint_id=wp_20240101_120000_abc" \
  -F "position_x=1.0" \
  -F "position_y=2.0" \
  -F "position_z=3.0" \
  -F "capture_index=0"

# 返回: {"success":true, "data":{"image_id":"img_...","status":"pending"}}

# 5. 轮询识别结果
curl http://192.168.1.200:8000/api/v1/images/<返回的image_id>/result

# 6. 上报任务进度
curl -X POST http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001/progress \
  -H "Content-Type: application/json" \
  -d '{"scanned": 1, "total": 2}'

# 7. 标记任务完成
curl -X POST http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001/complete \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 3.4 查看报告

```bash
# 查看该任务的所有报告
curl http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001

# 生成报告
curl -X POST http://192.168.1.200:8000/api/v1/inspection/tasks/TASK001/report

# 查看报告详情
curl http://192.168.1.200:8000/api/v1/inspection/reports/<report_id>

# 导出报告 (JSON)
curl http://192.168.1.200:8000/api/v1/inspection/reports/<report_id>/export
```

---

## 四、完整 API 接口列表

### 4.1 无人机管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/drones/` | 注册无人机 |
| GET | `/api/v1/drones/` | 获取无人机列表 |
| GET | `/api/v1/drones/{id}` | 获取无人机详情 |
| PATCH | `/api/v1/drones/{id}` | 更新无人机信息 |
| DELETE | `/api/v1/drones/{id}` | 删除无人机 |
| GET | `/api/v1/drones/{id}/position` | 获取无人机位置 |

### 4.2 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/inspection/tasks` | 创建巡检任务 |
| GET | `/api/v1/inspection/tasks` | 获取任务列表 |
| GET | `/api/v1/inspection/tasks/{code}` | 获取任务详情 |
| PATCH | `/api/v1/inspection/tasks/{code}` | 更新任务 |
| POST | `/api/v1/inspection/tasks/{code}/waypoints` | 添加航点 |
| GET | `/api/v1/inspection/tasks/{code}/waypoints` | 获取航点列表 |

### 4.3 无人机任务执行（无人机调用）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/drones/{code}/tasks/available` | 获取可执行任务 |
| POST | `/api/v1/drones/{code}/tasks/{code}/accept` | 接收任务 |
| POST | `/api/v1/inspection/tasks/{code}/progress` | 上报进度 |
| POST | `/api/v1/inspection/tasks/{code}/complete` | 完成标记 |

### 4.4 图像上传与识别

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/api/images/upload` | 上传图像 (multipart/form-data) |
| GET | `/api/v1/api/images/{id}` | 图像元信息 |
| GET | `/api/v1/api/images/{id}/file` | 下载源文件 |
| GET | `/api/v1/api/images/{id}/result` | 识别结果（轮询） |
| GET | `/api/v1/api/images/task/{code}` | 任务的所有图像 |
| POST | `/api/v1/api/images/{id}/retry` | 重新识别 |

### 4.5 报告

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/inspection/tasks/{code}/report` | 生成报告 |
| GET | `/api/v1/inspection/reports/{id}` | 获取报告详情 |
| GET | `/api/v1/inspection/reports/{id}/export` | 导出报告 (JSON) |

---

## 五、图像上传参数说明

**请求：** `POST /api/v1/api/images/upload` (Content-Type: multipart/form-data)

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image` | File | ✅ | 图像文件 (JPEG/PNG, 建议 1920x1080) |
| `drone_code` | string | ✅ | 无人机编号 (如 DRONE001) |
| `task_code` | string | ✅ | 任务编号 (如 TASK001) |
| `waypoint_id` | string | ✅ | 航点ID (如 wp_xxx) |
| `position_x` | float | - | 位置X坐标 |
| `position_y` | float | - | 位置Y坐标 |
| `position_z` | float | - | 位置Z坐标 |
| `camera_angle` | float | - | 摄像头俯仰角 (默认45.0) |
| `capture_index` | int | - | 同一航点第几张 (0, 1, 2...) |
| `rfid_tags` | string | - | RFID标签JSON `["TAG001","TAG002"]` |

**响应示例：**
```json
{
  "success": true,
  "message": "图像已接收，正在后台识别二维码",
  "data": {
    "image_id": "img_20240101_120000_a1b2c3d4",
    "status": "pending",
    "file_name": "img_20240101_120000_a1b2c3d4_capture.jpg",
    "file_size": 524288
  }
}
```

---

## 六、识别结果查询

**请求：** `GET /api/v1/api/images/{image_id}/result`

### 6.1 处理中

```json
{
  "success": true,
  "data": {
    "image_id": "img_20240101_120000_a1b2c3d4",
    "status": "processing",
    "qr_data": null,
    "confidence": 0,
    "message": "处理中，请继续轮询"
  }
}
```

### 6.2 识别成功

```json
{
  "success": true,
  "data": {
    "image_id": "img_20240101_120000_a1b2c3d4",
    "status": "processed",
    "qr_data": "SKU123456",
    "confidence": 0.95,
    "image_quality": 85.0,
    "decoder_used": "pyzbar",
    "inventory_status": "normal",
    "expected_sku": "SKU123456",
    "message": "SKU与预期一致，位置正确"
  }
}
```

### 6.3 识别失败

```json
{
  "success": true,
  "data": {
    "image_id": "img_...",
    "status": "failed",
    "qr_data": null,
    "confidence": 0,
    "image_quality": 35.0,
    "decoder_used": null,
    "inventory_status": null,
    "expected_sku": "SKU123456",
    "message": "未识别到二维码"
  }
}
```

---

## 七、库存状态说明

| 状态 | 说明 | 触发条件 |
|------|------|---------|
| `normal` | 正常 | 识别SKU与预期一致 |
| `misplaced` | 错位 | 识别到SKU但与预期不符 |
| `missing` | 缺货 | 航点图像中未检测到二维码 |
| `extra` | 多货 | 无预期SKU但识别到了 |
| `duplicate` | 重复码 | 同一SKU在其他航点已出现过 |

---

## 八、二维码识别引擎说明

识别引擎 `QRRecognitionEngine` 使用以下策略：

1. **多尺度解码**：原始 (1.0x) → 放大 (1.5x) → 缩小 (0.7x)
2. **多解码器**：WeChatQRCode（主）→ pyzbar（备用）
3. **图像预处理**（低质量时触发）：
   - 去噪 (fastNlMeansDenoising)
   - 自适应阈值二值化
   - 轻度锐化
4. **质量评分**：拉普拉斯方差 (Laplacian variance)，值越高越清晰
5. **兜底机制**：每30秒扫描卡住的 pending 图像

### 至2026年6月，此引擎的工作原理

```
图像上传
  │
  ├── 1. 保存文件 → storage/images/{task_code}/{drone_code}/
  │   └── 写入 image_records 表 (status: pending)
  │
  ├── 2. 入队识别 → QRRecognitionEngine
  │   ├── 读取图像 (cv2.imread)
  │   ├── 质量评分 (Laplacian方差)
  │   ├── 多尺度 + 多解码器尝试
  │   │   ├── WeChatQRCode.detectAndDecode()   [如可用]
  │   │   └── pyzbar.decode()                   [备用]
  │   ├── 若失败 → 预处理 → 重试
  │   └── 写入结果到 image_records
  │
  ├── 3. 库存判定
  │   ├── 从 waypoints 查询预期SKU
  │   ├── 比对识别结果
  │   └── 写入 inventory_items 表
  │
  └── 4. 自动更新任务统计
```

---

## 九、数据存储

图像文件存储在 `storage/images/` 目录下：

```
storage/
└── images/
    └── {task_code}/
        └── {drone_code}/
            ├── img_20240101_120000_abc.jpg
            ├── img_20240101_120005_def.jpg
            └── ...
```

可通过 `GET /api/v1/api/images/{image_id}/file` 下载原图用于人工复核。

---

## 十、故障排查

### 10.1 无人机无法连接基站

```bash
# 在无人机上检查
ping 192.168.1.200                    # 网络连通性
curl http://192.168.1.200:8000/health # API可达性

# 常见原因:
# - 基站 Docker 未启动: docker-compose ps
# - 防火墙阻止: sudo ufw allow 8000/tcp
# - 端口未正确映射: 检查 docker-compose.yml 中 ports 配置
```

### 10.2 二维码识别失败率高

可能原因和处理方法：
- **图像模糊**：降低飞行速度/增加停留时间/检查对焦
- **光照不足**：开启补光灯
- **二维码过小**：降低飞行高度 (减小 altitude 参数)
- **图像质量差**：提高 JPEG 质量参数 (jpeg_quality=95)

可通过 `GET /api/v1/api/images/{image_id}/result` 查看 `image_quality` 评分：
- quality > 200：清晰，正常可识别
- quality 50-200：轻度模糊，预处理后可识别
- quality < 50：严重模糊，难识别

### 10.3 图像上传超时

```bash
# 检查图像文件大小
ls -lh capture.jpg

# 大于 5MB 建议降低分辨率或提高压缩率
# 推荐: 1920x1080 JPEG quality=85 (约 500KB-1MB)
```

### 10.4 任务状态不更新

```bash
# 检查数据库
docker-compose exec postgres psql -U postgres -d warehouse_inspection \
  -c "SELECT task_code, status, scanned_waypoints, total_images FROM tasks;"
```

---

## 十一、部署清单

- [ ] 基站 Docker 服务已启动（PostgreSQL + FastAPI + Redis）
- [ ] 基站防火墙已开放 8000/tcp
- [ ] 无人机可 ping 通 192.168.1.200
- [ ] 已创建至少一个巡检任务（含航点）
- [ ] 已注册无人机（POST /api/v1/drones/）
- [ ] 摄像头工作正常，拍摄分辨率 1920x1080
- [ ] 图像存储目录有足够空间（至少 10GB）

---

## 十二、模拟无人机测试工具

项目提供 `tools/simulate_drone.py` 用于模拟无人机端完整通信流程，无需真实无人机即可测试。

### 12.1 安装依赖

```bash
pip install requests Pillow qrcode[pil]
```

### 12.2 基本用法

```bash
cd tools/

# 1. 生成测试二维码图像（一次性）
python simulate_drone.py --gen-qr 5

# 2. 全自动测试：创建任务 → 生成航点 → 执行巡检 → 显示报告
python simulate_drone.py --auto --waypoints 3

# 3. 连接指定基站
python simulate_drone.py --host 192.168.1.200 --auto

# 4. 逐步模式（每步等回车，方便观察）
python simulate_drone.py --auto --step-by-step
```

### 12.3 选项列表

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `--host` | 127.0.0.1 | 基站地址 |
| `--port` | 8000 | 基站端口 |
| `--drone` | DRONE001 | 无人机编号 |
| `--task` | 自动选择 | 指定任务编号 |
| `--auto` | False | 全自动模式（创建任务+航点+执行） |
| `--waypoints` | 3 | 自动创建航点数量 |
| `--gen-qr N` | 0 | 仅生成测试图像 |
| `--step-by-step` | False | 逐步模式 |

### 12.4 完整测试流程（一键）

```bash
# 终端 1: 启动基站
cd warehouse-inspection-system/backend
docker-compose up -d

# 确认基站就绪
curl http://127.0.0.1:8000/health

# 终端 2: 运行模拟测试
cd warehouse-inspection-system/tools
python simulate_drone.py --auto --waypoints 3
```

输出示例：
```
╔══════════════════════════════════════════════╗
║        无人机模拟通信程序 v1.0                 ║
╚══════════════════════════════════════════════╝
───────────────────────────────────────────────────────
  1. 检查基站连通性
  ✓ 基站运行正常
───────────────────────────────────────────────────────
  2. 启动心跳上报
  ✓ 心跳线程已启动（间隔 5 秒）
...
───────────────────────────────────────────────────────
  8. 查看盘点报告
  ...
╔══════════════════════════════════════════════╗
║        测试完成!                               ║
╚══════════════════════════════════════════════╝
```

---

*手册版本：1.0*  
*对应系统版本：仓库巡检系统 v1.0*