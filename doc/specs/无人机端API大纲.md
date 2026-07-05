# 无人机端 API 大纲 — 基站侧接口定义

> **用途**: 铆钉无人机端↔基站端开发方向，明确接口契约
> **基站地址**: `192.168.1.200:8080` (API Gateway)
> **统一响应格式**: `{"success": bool, "message": str, "data": ...}`

---

## 一、核心端点（用户指定 5 项）

### 1. 货柜表上传

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/shelves/sync` |
| **调用时机** | 无人机启动后 / 货柜配置变更时 |
| **请求体** | 货架列表 JSON（含 shelf_code、坐标、尺寸等） |

**请求示例**:
```json
{
  "drone_id": "DRONE001",
  "shelves": [
    {
      "shelf_code": "SHELF-001",
      "shelf_name": "A区1排",
      "zone": "A",
      "position_x": 1.0,
      "position_y": 2.0,
      "position_z": 1.5,
      "yaw_rad": 0.0,
      "arrival_radius_m": 0.5,
      "dwell_time_s": 3.0,
      "rows": 4,
      "columns": 3,
      "levels": 2
    }
  ]
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "货架表同步成功，共 12 条",
  "data": {
    "synced_count": 12,
    "archived_count": 0,
    "last_synced_at": "2026-07-05T10:30:00Z"
  }
}
```

**对应模型**: `Shelf` 表 — shelf_code 非唯一索引（允许归档后重用）

---

### 2. 任务获取

| 项目 | 内容 |
|------|------|
| **方法** | `GET` |
| **路径** | `/api/drones/{drone_id}/tasks/available` |
| **调用时机** | 无人机启动后轮询（无任务时每 30 秒） |
| **响应** | 待执行巡检任务列表 |

**响应示例**:
```json
{
  "success": true,
  "message": "获取到 1 个可用任务",
  "data": {
    "tasks": [
      {
        "task_code": "task_20260705_001",
        "task_name": "A区例行巡检",
        "task_type": "routine",
        "total_waypoints": 15,
        "altitude": 5.0,
        "speed": 2.0,
        "target_shelves": ["SHELF-001", "SHELF-002", "SHELF-003"],
        "created_at": "2026-07-05T08:00:00Z"
      }
    ]
  }
}
```

**对应模型**: `Task` 表 — status=created 的任务

---

### 3. 航点到达

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive` |
| **调用时机** | 无人机到达航点时 |
| **用途** | 通知基站航点到达，触发视频帧标记 + 扫码准备 |

**请求示例**:
```json
{
  "drone_id": "DRONE001",
  "waypoint_id": "wp_xxx",
  "task_code": "task_20260705_001",
  "position": {
    "x": 1.5,
    "y": 2.0,
    "z": 3.0
  },
  "arrived_at": "2026-07-05T10:30:15Z"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "航点到达已确认",
  "data": {
    "waypoint_id": "wp_xxx",
    "waypoint_status": "scanning",
    "expected_sku": "SKU001",
    "scan_timeout": 30
  }
}
```

**对应模型**: `Waypoint` 表 → status 更新为 `scanning`；同时调用 `VideoStreamAggregator.mark_waypoint()` 在视频流中标记当前帧

---

### 4. 心跳上报

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/heartbeat` |
| **调用时机** | 每 5 秒 |
| **请求体** | 电池/位置/任务进度/状态 |

**请求示例**:
```json
{
  "drone_id": "DRONE001",
  "battery": 85,
  "status": "flying",
  "position": {
    "x": 1.5,
    "y": 2.0,
    "z": 3.0
  },
  "current_task": "task_20260705_001",
  "current_waypoint": "wp_xxx",
  "task_progress": {
    "scanned": 8,
    "total": 15
  },
  "last_heartbeat": "2026-07-05T10:30:20Z"
}
```

**响应示例**:
```json
{
  "success": true,
  "message": "心跳已接收",
  "data": {
    "drone_status": "flying",
    "server_time": "2026-07-05T10:30:20Z"
  }
}
```

**对应模型**: `Drone` 表 — 更新 battery_level、status、last_position_*、last_seen

**变更说明**: 现有 `drones.py` 用 `drone_code` 路径参数，新规范改为 body 中传 `drone_id`，路径为 `/api/drones/heartbeat`（无路径参数）

---

### 5. 实时图传

| 项目 | 内容 |
|------|------|
| **协议** | `WebSocket` |
| **路径** | `ws://192.168.1.200:8080/ws/video/{drone_id}` |
| **调用时机** | 飞行全程持续推流 |
| **数据格式** | binary (JPEG帧) + text (控制消息) |

**双模消息**:

| 消息类型 | 格式 | 内容 |
|----------|------|------|
| 视频帧 | `binary` | JPEG 压缩帧（质量 70%） |
| 流开始 | `text` | `{"type": "stream_start", "task_code": "task_xxx"}` |
| 航点进入 | `text` | `{"type": "waypoint_enter", "waypoint_id": "wp_xxx", "expected_sku": "SKU001"}` |
| 航点离开 | `text` | `{"type": "waypoint_leave", "waypoint_id": "wp_xxx"}` |
| 流结束 | `text` | `{"type": "stream_stop"}` |
| 心跳 | `text` | `{"type": "heartbeat", "battery": 85}` |

**基站处理流程**:
1. `VideoStreamAggregator.start_session()` → 初始化帧缓冲
2. 每个 binary 帧 → `push_frame()` 写入缓冲
3. `waypoint_enter` → `mark_waypoint()` 在视频帧位置打标记
4. `stream_stop` / 连接断开 → `close_session()` 编码 MP4 + 创建 VideoData + 触发 `postprocess_video`

**对应模型**: `VideoData` 表 — source="ws_stream", stream_session_id, waypoint_markers

**已实现**: `api/ws_video.py` + `services/video_stream_aggregator.py`（Stage 4）

---

## 二、辅助端点（配套必需）

### 6. 任务确认

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/tasks/{task_code}/accept` |
| **用途** | 无人机确认接收任务，基站将任务状态改为 assigned |

---

### 7. 任务进度上报

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/tasks/{task_code}/progress` |
| **用途** | 每完成一个航点后上报进度 |

**请求示例**:
```json
{
  "scanned": 8,
  "total": 15,
  "normal_count": 7,
  "abnormal_count": 1,
  "current_waypoint": "wp_xxx"
}
```

---

### 8. 任务完成

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/tasks/{task_code}/complete` |
| **用途** | 任务完成上报，基站标记 finished + 生成报告 |

---

### 9. 航点列表获取

| 项目 | 内容 |
|------|------|
| **方法** | `GET` |
| **路径** | `/api/tasks/{task_code}/waypoints` |
| **用途** | 任务开始前获取航点序列 |

**响应示例**:
```json
{
  "success": true,
  "data": {
    "waypoints": [
      {
        "id": "wp_001",
        "shelf_code": "SHELF-001",
        "position": {"x": 1.0, "y": 2.0, "z": 3.0},
        "camera_angle": 45.0,
        "expected_sku": "SKU001",
        "sort_order": 1
      }
    ]
  }
}
```

---

### 10. RFID 扫描文件上传

| 项目 | 内容 |
|------|------|
| **方法** | `POST` |
| **路径** | `/api/drones/{drone_id}/rfid/upload` |
| **Content-Type** | `multipart/form-data` |
| **调用时机** | 无人机在航点完成 RFID 扫描后，将扫描结果保存为文件并上传 |
| **用途** | 接收无人机端扫描到的 RFID 信号文件，解析后入库 |

**与现有 `/gateway/receive` (data_type=rfid) 的区别**:
- `/gateway/receive`：JSON body 内嵌 payload（适合小数据量、Base64 编码）
- `/api/drones/{drone_id}/rfid/upload`：**文件上传**（multipart/form-data，适合无人机端生成的完整扫描文件）

**请求参数** (multipart/form-data):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | RFID 扫描结果文件（.json 格式） |
| `task_code` | string | 否 | 关联任务编号 |
| `waypoint_id` | string | 否 | 关联航点 ID |
| `position_x` | float | 否 | 扫描时无人机 X 坐标 |
| `position_y` | float | 否 | 扫描时无人机 Y 坐标 |
| `position_z` | float | 否 | 扫描时无人机 Z 坐标 |

**文件格式** (JSON):
```json
{
  "drone_id": "DRONE001",
  "scanned_at": "2026-07-05T10:30:15Z",
  "tags": [
    {
      "epc": "E20000123456789012345678",
      "rssi_dbm": -62,
      "stamp": 1751704215
    },
    {
      "epc": "E20000876543210987654321",
      "rssi_dbm": -71,
      "stamp": 1751704216
    }
  ]
}
```

**兼容格式**（纯数组，无外层结构）:
```json
[
  {"epc": "E20000123456789012345678", "rssi_dbm": -62},
  {"epc": "E20000876543210987654321", "rssi_dbm": -71}
]
```

**响应示例**:
```json
{
  "success": true,
  "message": "RFID文件已接收，共解析到 2 个标签",
  "data": {
    "file_name": "rfid_20260705_103015.json",
    "file_size": 512,
    "total_tags": 2,
    "valid_tags": 2,
    "resolved_tags": 1,
    "record_id": 123,
    "saved_path": "storage/gateway/DRONE001/rfid_20260705_103015.json"
  }
}
```

**基站处理流程**:
1. 保存上传文件到 `storage/gateway/{drone_code}/rfid_{timestamp}.json`
2. 解析文件内容 → 提取 EPC 列表（支持两种 JSON 格式）
3. EPC 格式校验（24 字符大写 hex，ISO 18000-6C 标准）
4. 复用 `_process_rfid_payload()` 核心逻辑：
   - 查 RFIDTag 表关联 SKU
   - 写 InspectionRecord + RFIDData 树叶记录
   - 更新 Inventory 库存快照
   - 触发 QR×RFID 交叉校验
5. 广播 WebSocket 事件 `rfid_processed`

**对应模型**: `InspectionRecord` + `RFIDData` + `Inventory` + `RFIDTag`

---

## 三、接口汇总表

| # | 功能 | 方法 | 路径 | 状态 |
|---|------|------|------|------|
| 1 | 货柜表上传 | POST | `/api/drones/{drone_id}/shelves/sync` | 待开发 |
| 2 | 任务获取 | GET | `/api/drones/{drone_id}/tasks/available` | 待开发 |
| 3 | 航点到达 | POST | `/api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive` | 待开发 |
| 4 | 心跳上报 | POST | `/api/drones/heartbeat` | 待重构（现有用 drone_code） |
| 5 | 实时图传 | WS | `ws://192.168.1.200:8080/ws/video/{drone_id}` | 已实现（Stage 4） |
| 6 | 任务确认 | POST | `/api/drones/{drone_id}/tasks/{task_code}/accept` | 待开发 |
| 7 | 进度上报 | POST | `/api/drones/{drone_id}/tasks/{task_code}/progress` | 待开发 |
| 8 | 任务完成 | POST | `/api/drones/{drone_id}/tasks/{task_code}/complete` | 待开发 |
| 9 | 航点列表 | GET | `/api/tasks/{task_code}/waypoints` | 待开发 |
| 10 | RFID扫描文件上传 | POST | `/api/drones/{drone_id}/rfid/upload` | 待开发 |

---

## 四、开发优先级

### P0 — 无人机无法运行 without these
1. **心跳上报** (#4) — 重构为 body 传 drone_id
2. **任务获取** (#2) — 无人机启动后获取任务
3. **航点列表** (#9) — 获取航点序列
4. **航点到达** (#3) — 航点到达通知
5. **RFID扫描文件上传** (#10) — RFID 数据回传

### P1 — 业务闭环
6. **任务确认** (#6) — 接收任务
7. **进度上报** (#7) — 实时进度
8. **任务完成** (#8) — 完成上报 + 报告生成

### P2 — 增强功能
9. **货柜表上传** (#1) — 货架配置同步
10. **实时图传** (#5) — 已实现，需联调

---

## 五、与现有代码的差异

| 现有实现 | 新规范 | 变更 |
|----------|--------|------|
| `POST /api/drones/{drone_code}/heartbeat` | `POST /api/drones/heartbeat` | drone_code 从路径参数移到 body |
| `GET /api/drones/{drone_code}/position` | 合并到心跳 body | 位置通过心跳上报 |
| 无 | `POST /api/drones/{drone_id}/shelves/sync` | 新增 |
| 无 | `POST /api/drones/{drone_id}/waypoints/{wp_id}/commands/arrive` | 新增 |
| `WS /ws/video/{drone_code}` (Stage 4) | `WS /ws/video/{drone_id}` | 参数名统一为 drone_id |

---

## 六、数据模型对照

| 接口 | 写入表 | 读取表 |
|------|--------|--------|
| 货柜表上传 | shelves (upsert) | - |
| 任务获取 | - | tasks (status=created) |
| 航点到达 | waypoints.status=scanning, video waypoint_markers | waypoints |
| 心跳上报 | drones (battery/status/position/last_seen) | drones |
| 实时图传 | video_data (source=ws_stream) | - |
| 任务确认 | tasks.status=assigned | tasks |
| 进度上报 | tasks.scanned_waypoints | tasks |
| 任务完成 | tasks.status=finished, inspection_reports | scan_records, tasks |
| 航点列表 | - | waypoints (sort_order) |
| RFID扫描文件上传 | inspection_records, rfid_data, inventory | rfid_tags, skus |

---

*文档版本: v1.0*
*创建日期: 2026-07-05*
