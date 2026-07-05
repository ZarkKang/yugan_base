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

## 三、接口汇总表

| # | 功能 | 方法 | 路径 | 状态 |
|---|------|------|------|------|
| 1 | 货柜表上传 | POST | `/api/drones/{drone_id}/shelves/sync` | ✅ 已实现 |
| 2 | 任务获取 | GET | `/api/drones/{drone_id}/tasks/available` | ✅ 已实现 |
| 3 | 航点到达 | POST | `/api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive` | ✅ 已实现 |
| 4 | 心跳上报 | POST | `/api/drones/heartbeat` | ✅ 已实现（drone_id 在 body） |
| 5 | 实时图传 | WS | `ws://192.168.1.200:8080/ws/video/{drone_id}` | ✅ 已实现 |
| 6 | 任务确认 | POST | `/api/drones/{drone_id}/tasks/{task_code}/accept` | ✅ 已实现 |
| 7 | 进度上报 | POST | `/api/drones/{drone_id}/tasks/{task_code}/progress` | ✅ 已实现 |
| 8 | 任务完成 | POST | `/api/drones/{drone_id}/tasks/{task_code}/complete` | ✅ 已实现 |
| 9 | 航点列表 | GET | `/api/tasks/{task_code}/waypoints` | ✅ 已实现 |
| 10 | ID反查 | GET | `/api/drones/lookup?drone_code=xxx` | ✅ 已实现（新增） |

---

## 四、开发优先级

### P0 — 无人机无法运行 without these
1. **心跳上报** (#4) — 重构为 body 传 drone_id
2. **任务获取** (#2) — 无人机启动后获取任务
3. **航点列表** (#9) — 获取航点序列
4. **航点到达** (#3) — 航点到达通知

### P1 — 业务闭环
5. **任务确认** (#6) — 接收任务
6. **进度上报** (#7) — 实时进度
7. **任务完成** (#8) — 完成上报 + 报告生成

### P2 — 增强功能
8. **货柜表上传** (#1) — 货架配置同步
9. **实时图传** (#5) — 已实现，需联调

---

## 五、与现有代码的差异

| 现有实现 | 新规范 | 变更 | 实施状态 |
|----------|--------|------|---------|
| `POST /api/v1/drones/{drone_code}/heartbeat` | `POST /api/drones/heartbeat` | drone_code 从路径参数移到 body 的 drone_id | ✅ 已实施 |
| `GET /api/v1/drones/{drone_id}/position` | 合并到心跳 body | 位置通过心跳上报 | ✅ 已删除 |
| 无 | `POST /api/drones/{drone_id}/shelves/sync` | 新增（从 gateway.py 迁移） | ✅ 已实施 |
| 无 | `POST /api/drones/{drone_id}/waypoints/{wp_id}/commands/arrive` | 新增 | ✅ 已实施 |
| `WS /ws/video/{drone_code}` | `WS /ws/video/{drone_id}` | 参数从 drone_code(str) 改为 drone_id(int) | ✅ 已实施 |
| 无 | `GET /api/drones/lookup?drone_code=xxx` | 新增（drone_code→drone_id 反查） | ✅ 已实施 |
| `GET /api/v1/drones/{drone_code}/tasks/available` | `GET /api/drones/{drone_id}/tasks/available` | 统一到 /api/drones/ | ✅ 已实施 |
| `POST /api/v1/drones/{drone_code}/tasks/{code}/accept` | `POST /api/drones/{drone_id}/tasks/{code}/accept` | 统一 + 归属校验 | ✅ 已实施 |
| `POST /api/v1/inspection/tasks/{code}/progress` | `POST /api/drones/{drone_id}/tasks/{code}/progress` | 统一 + 归属校验 | ✅ 已实施 |
| `POST /api/v1/inspection/tasks/{code}/complete` | `POST /api/drones/{drone_id}/tasks/{code}/complete` | 统一 + 归属校验 | ✅ 已实施 |
| `GET /api/v1/inspection/tasks/{code}/waypoints` | `GET /api/tasks/{code}/waypoints` | 统一到 /api/tasks/ | ✅ 已实施 |
| `POST /api/v1/gateway/shelves/sync` | `POST /api/drones/{drone_id}/shelves/sync` | 迁移到 drone_api.py | ✅ 已实施 |

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

---

*文档版本: v1.0*
*创建日期: 2026-07-05*
