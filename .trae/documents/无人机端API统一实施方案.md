# 无人机端 API 统一实施方案

## Context

`doc/无人机端API大纲.md` 定义了 9 个无人机↔基站接口，当前代码中这些端点分散在 4 个 router 文件中，参数风格不一致（`drone_code` 字符串 vs `drone_id` 整数），Schema 验证缺失（大量裸 `dict` 入参）。用户要求全部统一到 `/api/drones/` 命名空间，使用 `drone_id`（整数 PK）作为路径参数，前端自行适应。

---

## 一、旧端点 → 新端点完整映射

| # | 旧端点 | 新端点 | 变更要点 |
|---|--------|--------|----------|
| 1 | `POST /api/v1/drones/{drone_code}/heartbeat` (drones.py:129) | `POST /api/drones/heartbeat` | drone_code 从路径移到 body 的 `drone_id` |
| 2 | `GET /api/v1/drones/{drone_id}/position` (drones.py:116) | **删除** | 位置合并到心跳 body |
| 3 | `GET /api/v1/drones/{drone_code}/tasks/available` (inspection.py:150) | `GET /api/drones/{drone_id}/tasks/available` | drone_code→drone_id |
| 4 | `POST /api/v1/drones/{drone_code}/tasks/{task_code}/accept` (inspection.py:202) | `POST /api/drones/{drone_id}/tasks/{task_code}/accept` | drone_code→drone_id |
| 5 | `POST /api/v1/inspection/tasks/{task_code}/progress` (inspection.py:268) | `POST /api/drones/{drone_id}/tasks/{task_code}/progress` | 新增 drone_id 路径+归属校验 |
| 6 | `POST /api/v1/inspection/tasks/{task_code}/complete` (inspection.py:294) | `POST /api/drones/{drone_id}/tasks/{task_code}/complete` | 新增 drone_id 路径+归属校验 |
| 7 | `GET /api/v1/inspection/tasks/{task_code}/waypoints` (inspection.py:231) | `GET /api/tasks/{task_code}/waypoints` | 去掉 /inspection 前缀，独立注册 |
| 8 | `POST /api/v1/gateway/shelves/sync` (gateway.py:1199) | `POST /api/drones/{drone_id}/shelves/sync` | 移入 drone_api，加 drone_id |
| 9 | `WS /ws/video/{drone_code}` (ws_video.py:49) | `WS /ws/video/{drone_id}` | drone_code→drone_id(int) |
| 10 | **新增** | `GET /api/drones/lookup?drone_code=xxx` | drone_code→drone_id 反查 |
| 11 | **新增** | `POST /api/drones/{drone_id}/waypoints/{waypoint_id}/commands/arrive` | 航点到达命令 |

---

## 二、新建文件: `api/drone_api.py`

路径: `station/warehouse-inspection-system/backend/src/api/drone_api.py`

### 2.1 Router 定义

```python
router = APIRouter(tags=["无人机端API"])       # 注册 prefix="/api/drones"
waypoints_router = APIRouter(tags=["无人机端API"])  # 注册 prefix="/api"
```

两个 router 的原因：`GET /api/tasks/{task_code}/waypoints` 不在 `/api/drones/` 前缀下（大纲要求），需独立注册在 `/api` prefix。

### 2.2 全部端点签名

```python
# --- 心跳与查询 ---
@router.post("/heartbeat", response_model=APIResponse)
def drone_heartbeat(payload: DroneHeartbeatRequest, db: Session = Depends(get_db)):
    """无人机心跳上报（drone_id 在 body）"""

@router.get("/lookup", response_model=APIResponse)
def lookup_drone_id(drone_code: str = Query(...), db: Session = Depends(get_db)):
    """drone_code 反查 drone_id（无人机启动时调用）"""

# --- 任务管理 ---
@router.get("/{drone_id}/tasks/available", response_model=APIResponse)
def get_available_tasks(drone_id: int, db: Session = Depends(get_db)):
    """获取可执行任务"""

@router.post("/{drone_id}/tasks/{task_code}/accept", response_model=APIResponse)
def accept_task(drone_id: int, task_code: str, db: Session = Depends(get_db)):
    """接收任务"""

@router.post("/{drone_id}/tasks/{task_code}/progress", response_model=APIResponse)
def update_task_progress(drone_id: int, task_code: str, payload: TaskProgressRequest, db: Session = Depends(get_db)):
    """上报任务进度"""

@router.post("/{drone_id}/tasks/{task_code}/complete", response_model=APIResponse)
def complete_task(drone_id: int, task_code: str, payload: TaskCompleteRequest = None, db: Session = Depends(get_db)):
    """任务完成"""

# --- 航点 ---
@router.post("/{drone_id}/waypoints/{waypoint_id}/commands/arrive", response_model=APIResponse)
def waypoint_arrive(drone_id: int, waypoint_id: str, payload: WaypointArriveRequest, db: Session = Depends(get_db)):
    """航点到达命令（NEW）"""

@waypoints_router.get("/tasks/{task_code}/waypoints", response_model=APIResponse)
def get_task_waypoints(task_code: str, db: Session = Depends(get_db)):
    """获取任务航点列表"""

# --- 货架同步 ---
@router.post("/{drone_id}/shelves/sync", response_model=ShelfSyncResult)
def sync_shelves_from_drone(drone_id: int, payload: DroneShelfSyncRequest, db: Session = Depends(get_db)):
    """无人机推送货架数据同步"""
```

### 2.3 关键逻辑说明

**心跳 `drone_heartbeat`**:
1. 通过 `payload.drone_id` 查 Drone，不存在抛 404
2. 更新: `status`, `battery_level`, `last_position_x/y/z`（从 position dict 提取）, `last_seen`
3. 若 `payload.current_task` 和 `payload.task_progress` 存在，同步更新对应 Task 的 `scanned_waypoints`
4. 调用 `upsert_device_from_heartbeat(db, drone)` — 复用 `services/device_verification.py:417`
5. 返回 `{"drone_status": ..., "server_time": ...}`

**lookup `lookup_drone_id`**:
1. 通过 `drone_code` 查 Drone，不存在抛 404
2. 返回 `{"drone_id": drone.id, "drone_code": drone.drone_code, "status": drone.status}`

**航点到达 `waypoint_arrive`** (NEW):
1. 验证 drone_id → Drone 存在
2. 查询 Waypoint.id == waypoint_id，不存在 404
3. 设 `waypoint.status = "scanning"`, `waypoint.scanned_at = None`（到达不代表完成）
4. 若 payload.task_code 存在，校验 `waypoint.task_id == payload.task_code`
5. 尝试调用 `VideoStreamAggregator.get_instance().mark_waypoint_for_drone(drone_id, waypoint_id, expected_sku=waypoint.expected_sku, position)` — 新增辅助方法
6. 返回 `{"waypoint_id", "waypoint_status": "scanning", "expected_sku": ..., "scan_timeout": 30}`

**货架同步 `sync_shelves_from_drone`**:
- 复用 `gateway.py:1199-1296` 的核心同步逻辑
- 扩展: 写入 Shelf 时也填充 `zone`、`rows`、`columns`、`levels`（DroneShelfItem 已扩展）
- 验证 drone_id 存在后继续同步

**complete_task**:
- 需要 `_generate_report_for_task` — 从 inspection.py 直接 import（避免循环依赖，函数不依赖 inspection 模块其他内容）

---

## 三、新建/扩展 Pydantic Schemas

在 `schemas/schemas.py` 末尾追加：

```python
# ===== 无人机端 API Schemas =====

class DroneHeartbeatRequest(BaseModel):
    drone_id: int = Field(..., description="无人机ID(整数PK)")
    battery: Optional[float] = Field(None, ge=0, le=100)
    status: Optional[str] = None  # idle/flying/online/offline/maintenance
    position: Optional[Dict[str, float]] = None  # {x, y, z}
    current_task: Optional[str] = None
    current_waypoint: Optional[str] = None
    task_progress: Optional[Dict[str, int]] = None  # {scanned, total}
    last_heartbeat: Optional[datetime] = None

class TaskProgressRequest(BaseModel):
    scanned: Optional[int] = Field(None, ge=0)
    total: Optional[int] = Field(None, ge=0)
    normal_count: Optional[int] = Field(None, ge=0)
    abnormal_count: Optional[int] = Field(None, ge=0)
    current_waypoint: Optional[str] = None

class TaskCompleteRequest(BaseModel):
    total_scanned: Optional[int] = None
    total_normal: Optional[int] = None
    total_abnormal: Optional[int] = None

class WaypointArriveRequest(BaseModel):
    task_code: Optional[str] = None
    position: Optional[Dict[str, float]] = None  # {x, y, z}
    arrived_at: Optional[datetime] = None
```

**扩展 `DroneShelfItem`** — 增加 `zone`, `rows`, `columns`, `levels`：

```python
class DroneShelfItem(BaseModel):
    shelf_id: str
    shelf_name: Optional[str] = None
    zone: Optional[str] = None          # 新增
    position: Optional[dict] = None
    yaw_rad: Optional[float] = None
    arrival_radius_m: Optional[float] = None
    dwell_time_s: Optional[float] = None
    rows: Optional[int] = 1             # 新增
    columns: Optional[int] = 1          # 新增
    levels: Optional[int] = 1           # 新增
```

---

## 四、需修改的现有文件

### 4.1 `api/drones.py` — 删除无人机面向端点

**删除** 2 个端点：
- `POST /{drone_code}/heartbeat` (行 129-160)
- `GET /{drone_id}/position` (行 116-126)

**保留**（前端 CRUD，需认证）：
- `POST /`, `GET /`, `GET /{drone_id}`, `PATCH /{drone_id}`, `DELETE /{drone_id}`

保留原因：前端 `index.html` 调用 `${API}/drones/` 系列 CRUD，路径为 `/api/v1/drones/...`，与新的 `/api/drones/...` 不冲突。

### 4.2 `api/inspection.py` — 删除 5 个无人机面向端点

**删除**（行 150-317 中的 5 个函数）：
- `GET /drones/{drone_code}/tasks/available` (行 150-199)
- `POST /drones/{drone_code}/tasks/{task_code}/accept` (行 202-228)
- `GET /inspection/tasks/{task_code}/waypoints` (行 231-265)
- `POST /inspection/tasks/{task_code}/progress` (行 268-291)
- `POST /inspection/tasks/{task_code}/complete` (行 294-317)

**保留**：巡检记录 CRUD、任务管理(前端)、航点添加、报告生成/查询/导出、会话管理

### 4.3 `api/gateway.py` — 删除 shelves/sync

**删除** `POST /shelves/sync` (行 1199-1296)
**保留**：所有其它 gateway 端点（数据接收、QR识别、RFID读取、巡检对比、重放等）

### 4.4 `api/ws_video.py` — drone_code 改为 drone_id

**修改**：
- 行 49: `@router.websocket("/ws/video/{drone_code}")` → `"/ws/video/{drone_id}"`
- 行 50: `drone_code: str` → `drone_id: int`
- 行 61-68: 查询 `Drone.id == drone_id` 替代 `Drone.drone_code == drone_code`
- `start_session` 调整：`drone_code` 从 `drone.drone_code` 获取
- 日志/响应中保留 drone_code 用于可读性

### 4.5 `services/video_stream_aggregator.py` — 新增辅助方法

```python
def mark_waypoint_for_drone(self, drone_id: int, waypoint_id: str,
                             expected_sku: str = None, position: dict = None):
    """按 drone_id 查找活跃 WS 会话并标记航点帧（供 HTTP API 调用）"""
    for session in self._sessions.values():
        if session.drone_id == drone_id:
            session.mark_waypoint(waypoint_id, expected_sku, position)
            return True
    return False  # 无活跃会话，不影响（后续视频后处理时会补）
```

### 4.6 `main.py` — 注册新路由

```python
from .api import drone_api

# 无人机端API路由（无JWT认证）
app.include_router(drone_api.router, prefix="/api/drones")
app.include_router(drone_api.waypoints_router, prefix="/api")
```

**PathAliasMiddleware 兼容性**：中间件只处理 `/api/warehouse/` 和 `/api/drone/`（单数），新路径 `/api/drones/` 不会被匹配，安全。

### 4.7 `app/api-gateway/main.py` — 新增代理路由

**新增** `/api/drones/{path}` 代理：
```python
@app.api_route("/api/drones/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_warehouse_drones(path: str, request: Request):
    url = f"{service['base_url']}/api/drones/{path}"
    # ... 与现有 proxy_to_warehouse 逻辑相同
```

**新增** `/api/tasks/{path}` 代理（仅 GET，用于航点列表）：
```python
@app.api_route("/api/tasks/{path:path}", methods=["GET"])
async def proxy_tasks_to_warehouse(path: str, request: Request):
    url = f"{service['base_url']}/api/tasks/{path}"
    # ... 同上
```

**修改** WS 视频代理：
- `@app.websocket("/ws/video/{drone_code}")` → `"/ws/video/{drone_id}"`
- `drone_code: str` → `drone_id: int`
- 上游 URL: `ws://.../ws/video/{drone_id}`

---

## 五、前端影响分析

**结论：前端 `index.html` 本次无需修改。**

- 前端调用的都是 `/api/v1/drones/` CRUD 和 `/api/v1/inspection/tasks/` 任务管理，这些端点保留在原位
- 被删除的旧端点都是纯无人机端调用（heartbeat、available、accept、progress、complete、waypoints、shelves/sync），前端未使用
- `drone_integration/device/verify` 使用 `drone_code` 作为 Query 参数，不受影响

---

## 六、实施步骤

### Phase 1: Schema 层（无破坏性）
1. 在 `schemas/schemas.py` 末尾追加 4 个新 Schema
2. 扩展 `DroneShelfItem` 增加 4 个字段

### Phase 2: 新建 drone_api.py（增量）
3. 创建 `api/drone_api.py`，实现全部 9 个端点
4. 在 `video_stream_aggregator.py` 新增 `mark_waypoint_for_drone()` 方法
5. 在 `main.py` 注册新路由

### Phase 3: 旧端点清理（有破坏性）
6. `api/drones.py` 删除 heartbeat + position（2 个端点）
7. `api/inspection.py` 删除 5 个无人机端点
8. `api/gateway.py` 删除 shelves/sync（1 个端点）
9. `api/ws_video.py` drone_code → drone_id

### Phase 4: 网关更新
10. `app/api-gateway/main.py` 新增 `/api/drones/` + `/api/tasks/` 代理
11. WS 视频代理 drone_code → drone_id

### Phase 5: 验证
12. 启动 warehouse 后端，验证新端点可达
13. 启动 api-gateway，验证代理正常
14. 验证旧端点已不可达
15. 验证前端功能不受影响

---

## 七、风险与注意事项

1. **drone_id 发现机制**：无人机启动时只知 `drone_code`，需先调 `GET /api/drones/lookup?drone_code=DRONE001` 获取整数 ID。若返回 404 则说明未注册，需操作员通过前端注册。
2. **心跳无路径参数**：`POST /api/drones/heartbeat` 的 drone_id 在 body 中，无法通过 URL 区分不同无人机。日志需从 body 提取。
3. **_generate_report_for_task 引用**：从 inspection.py 直接 import（`from .inspection import _generate_report_for_task`），无循环依赖风险（函数不依赖 inspection 模块其他内容）。
4. **认证策略**：drone_api.py 全部端点不加 JWT 认证（无人机无法提供 token）。drones.py 的 CRUD 仍需认证，保留原位。
5. **WS 路径类型安全**：`drone_id: int` 类型参数，非整数值自动返回 422。
6. **PathAliasMiddleware**：只匹配 `/api/warehouse/` 和 `/api/drone/`（单数），新路径 `/api/drones/` 不会被错误重写。
