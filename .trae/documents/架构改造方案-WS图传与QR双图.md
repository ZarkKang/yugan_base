# 架构改造方案 — WS 实时图传 + QR 双图保存 + 删除 Electron

> 计划文件 · 用于用户审批后开始执行
> 实施状态：Stages 1-7 已实施完成（2026-07-05）；Stage 5 已合并至 Stage 4；本文档为原始设计稿，与最终实现差异已通过末尾 `## 十三、实施差异说明` 章节标注

## Context（背景与目的）

### 起因

用户在审查 `doc/全系统改进方案.md` 后，提出 4 项架构调整要求（用 `***` 标注）：

1. **删除无人机端 QR 识别要求**：当前项目实际已对齐（`/api/scan/upload` 接口在代码中根本不存在），文档过时需更新。
2. **图传视频流改 WebSocket 实时推流**：当前是"无人机上传完整视频文件 → 基站处理"，用户希望改为"无人机持续推 JPEG 帧 → 基站聚合为视频文件后处理"。
3. **航点信号通过 WebSocket 内嵌**：无人机到达航点时通过 WS 控制消息通知基站，基站在视频帧上标记航点位置（不切分视频，仅追加 `waypoint_markers` 数组项）。
4. **舍弃 Electron 桌面应用**：完全删除 `app/desktop-app/` 目录及其在脚本/文档中的引用。
5. **QR 双图保存**：识别 QR 后保存"裁剪出的 QR 区域小图 + 带 QR 框选标注的原图"，关联到巡检记录树叶。

### 现状对比

| 用户要求            | 当前状态                                     | 差距                                |
| --------------- | ---------------------------------------- | --------------------------------- |
| 删除无人机端 QR 识别    | ✅ 已对齐                                    | 仅文档需更新                            |
| QR×RFID 异常判定    | ✅ 已实现（`gateway._cross_validate_qr_rfid`） | 无差距                               |
| WebSocket 实时图传流 | ❌ 仅有 `/ws/monitor`（前端监控用）                | 需新增 `/ws/video/{drone_code}`      |
| 视频按航点切分         | ❌ 当前按固定 1s 间隔抽帧                          | 不新增航点，在到达每个航点时，标记那一帧视频帧           |
| QR 双图保存         | ⚠️ 有 `QRCropResult` 但未持久化                | 需在 `qr_worker._process_one` 中保存双图 |
| 删除 Electron     | ⚠️ `app/desktop-app/` 仍存在                | 需删除目录并清理引用                        |

### 预期结果

* 无人机通过 `ws://{base}:8080/ws/video/{drone_code}` 实时推 JPEG 帧

* 基站标记航点视频帧位置（不切分视频），单一 WS 会话产出单一 `VideoData` 行并触发 QR 识别 + 交叉校验

* QR 识别后产出两张证据图（裁剪图 + 标注图），可通过 `GET /api/v1/images/{id}` 查询

* Electron 桌面应用完全移除，所有界面通过 Web 前端访问

* `POST /api/v1/videos/upload` 保留作为网络降级通道

***

## 一、文件清单

### 1.1 新建文件

| 路径                                                                                    | 用途                                                                                         |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `station/warehouse-inspection-system/backend/src/api/ws_video.py`                     | `/ws/video/{drone_code}` 端点：接收 JPEG 帧 + 航点标记                                               |
| `station/warehouse-inspection-system/backend/src/services/video_stream_aggregator.py` | `VideoStreamAggregator` 单例：每无人机一个 `DroneStreamSession`，帧缓冲 + 编码线程 + 航点帧标记               |
| `station/warehouse-inspection-system/backend/src/services/video_postprocess.py`       | 公共 `postprocess_video()` 函数：抽帧 + QR 识别 + InventoryItem + 交叉校验（从 gateway.py / videos.py 抽取） |
| `station/warehouse-inspection-system/backend/src/db/migrations.py`                    | 幂等迁移：`ALTER TABLE ADD COLUMN IF NOT EXISTS`                                                |
| `station/warehouse-inspection-system/backend/src/image/annotator.py`                  | QR 框选标注：`draw_qr_bbox()` + `save_annotated()`                                              |
| `station/warehouse-inspection-system/backend/tests/test_ws_video.py`                  | WS 端点集成测试                                                                                  |
| `station/warehouse-inspection-system/backend/tests/test_video_stream_aggregator.py`   | 聚合器单元测试                                                                                    |
| `station/warehouse-inspection-system/backend/tests/test_qr_dual_image.py`             | QR 双图保存测试                                                                                  |
| `station/warehouse-inspection-system/backend/tests/test_migrations.py`                | 迁移幂等性测试                                                                                    |

### 1.2 修改文件

| 路径                                           | 修改要点                                                                                                                              |
| -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `station/.../backend/src/models/models.py`   | `VideoData` 加 `source`/`waypoint_markers`/`stream_session_id`/`frame_rate_actual`；`ImageRecord` 加 `qr_cropped_path`/`annotated_path` |
| `station/.../backend/src/db/database.py`     | `init_db()` 末尾调用 `run_migrations(engine)`                                                                                         |
| `station/.../backend/src/main.py`            | lifespan 启停 `VideoStreamAggregator`；注册 `ws_video.router`                                                                          |
| `station/.../backend/src/api/ws.py`          | `get_workers_status()` 增加 `video_stream` 字段                                                                                       |
| `station/.../backend/src/image/qr_worker.py` | `_process_one()`（第 188-244 行）保留 `hit_crop/hit_bbox`，写入双图路径                                                                        |
| `station/.../backend/src/api/gateway.py`     | `_process_video_in_background` 改调 `postprocess_video()`，写 `VideoData.source='gateway'`                                            |
| `station/.../backend/src/api/videos.py`      | `_process_video_background` 改调 `postprocess_video()`，写 `source='upload'`                                                          |
| `station/.../backend/src/api/images.py`      | `GET /{image_id}` 响应追加 `qr_cropped_path`/`annotated_path`                                                                         |
| `station/.../backend/src/schemas/schemas.py` | 新增 `WaypointMarker`/`VideoFrameAck`/`StreamControl` WS 消息 schema（仅文档化）                                                            |
| `app/api-gateway/main.py`                    | 新增 `/ws/video/{drone_code}` WS 反向代理，**同时转发 text + binary**（参考 `main.py:212-269` 现有 `/ws/monitor` 代理，但用 `receive()` 按消息类型分发）       |
| `doc/全系统改进方案.md`                             | 删除 Electron 段落；新增 WS 图传协议说明                                                                                                       |
| `doc/无人机端开发规范.md`                            | 新增 `/ws/video/{drone_code}` 协议章节；版本号升级 v3.0                                                                                       |
| `project_memory.md`                          | 新增"WS 视频流协议速查"+"QR 双图存储路径约定"                                                                                                      |
| `logs/devlog.md`                             | 追加本次变更记录                                                                                                                          |
| `Makefile`                                   | 删除 `desktop` target 与 `install` 中的 `cd app/desktop-app && npm install`                                                            |
| `app/deploy-linux.sh`                        | 删除 desktop-app 安装段                                                                                                                |
| `启动.bat`                                     | 删除 `start_desktop`/`init_desktop` 分支与 electron 进程检测                                                                               |

### 1.3 删除文件/目录

| 路径                       | 说明                                                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `app/desktop-app/`（整个目录） | Electron 桌面应用：`main.js`/`preload.js`/`launcher.html`/`package.json`/`package-lock.json`/`README.md`/`icon.png`/`generate-icon.js` |

> **保留**：`app/api-gateway/`、`app/scripts/`、`app/systemd/`、`app/index.html`、`app/login.html`、`app/root-index.html`（前端入口，非 Electron）
>
> **docker-compose.yml 无需改动**：`./app:/app` 挂载仍需 `app/index.html` 等前端入口，仅 `app/desktop-app/` 子目录被删除

***

## 二、数据库表变更

### 2.1 VideoData 表新增字段（[models.py:540-587](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/models/models.py#L540)）

| 字段名                 | 类型                              | 用途                                                               |
| ------------------- | ------------------------------- | ---------------------------------------------------------------- |
| `source`            | `String(16)` default `'upload'` | 数据来源：`upload`(multipart) / `gateway`(Base64) / `ws_stream`(WS图传) |
| `waypoint_markers`  | `Text` nullable                 | 航点标记帧 JSON 数组：`[{waypoint_id, frame_index, timestamp, expected_sku, position}, ...]` — 不切分视频，仅记录航点对应视频帧位置 |
| `stream_session_id` | `String(64)` nullable           | WS 流会话 ID（同一次 WS 连接内所有段共享）                                       |
| `frame_rate_actual` | `Float` nullable                | 实际帧率（WS 聚合时统计）                                                   |

### 2.2 ImageRecord 表新增字段（[models.py:334-384](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/models/models.py#L334)）

| 字段名               | 类型                     | 用途             |
| ----------------- | ---------------------- | -------------- |
| `qr_cropped_path` | `String(512)` nullable | 裁剪出的 QR 区域小图路径 |
| `annotated_path`  | `String(512)` nullable | 带 QR 框选标注的原图路径 |

### 2.3 迁移机制

新建 `db/migrations.py`，在 `init_db()` 末尾调用。PostgreSQL 支持 `ADD COLUMN IF NOT EXISTS`，迁移天然幂等：

```python
MIGRATIONS = [
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'upload'",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS waypoint_markers TEXT",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS stream_session_id VARCHAR(64)",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS frame_rate_actual FLOAT",
    "ALTER TABLE image_records ADD COLUMN IF NOT EXISTS qr_cropped_path VARCHAR(512)",
    "ALTER TABLE image_records ADD COLUMN IF NOT EXISTS annotated_path VARCHAR(512)",
    "CREATE INDEX IF NOT EXISTS ix_video_data_stream_session ON video_data (stream_session_id)",
]
# 注：waypoint_markers 为应用层 JSON 序列化的 TEXT 字段，PostgreSQL 不校验 JSON 结构，
# 应用层（video_stream_aggregator.py）负责 json.dumps / json.loads 序列化与反序列化。

def run_migrations(engine):
    with engine.begin() as conn:
        for sql in MIGRATIONS:
            conn.execute(text(sql))
```

**理由**：项目 Alembic 未集成（P3 优先级），此方案零依赖、幂等、PostgreSQL 9.6+ 原生支持。

***

## 三、WebSocket 视频流协议设计

### 3.1 端点

**`WS /ws/video/{drone_code}`**（warehouse 8001，或经 api-gateway 8080）

* 路径参数：`drone_code`（必须先在 `drones` 表注册）

* Query：`token`（预留，当前允许匿名，与 `/api/v1/videos/upload` 一致）

* 鉴权：查 DB 确认 `drone_code` 存在，不存在则 `close(code=4404)`

### 3.2 消息分类（基于 WebSocket opcode）

| 类型       | opcode            | 用途                 |
| -------- | ----------------- | ------------------ |
| **视频帧**  | binary (opcode 2) | 纯 JPEG 字节流，无包装     |
| **控制消息** | text (opcode 1)   | JSON，含 `type` 字段区分 |

**设计理由**：JPEG 二进制直传效率最高（避免 Base64 膨胀 33%）；控制消息用 JSON 文本便于调试。

### 3.3 无人机 → 基站 消息格式

#### 视频帧（binary）

```
[raw JPEG bytes]
```

基站端按收到顺序分配 `frame_id`（递增计数器），记录接收时间戳。

#### 控制消息（text JSON）

```json
{"type": "stream_start", "task_code": "TASK001", "session_token": "uuid-...",
 "camera": {"width": 1920, "height": 1080, "fps": 15}, "timestamp": "ISO8601"}
```

```json
{"type": "waypoint_enter", "waypoint_id": "wp_xxx", "task_code": "TASK001",
 "shelf_code": "SHELF-001", "expected_sku": "SKU001",
 "position": {"x": 1.5, "y": 2.0, "z": 3.0}, "sort_order": 3, "timestamp": "ISO8601"}
```

```json
{"type": "waypoint_leave", "waypoint_id": "wp_xxx",
 "result_summary": {"qr_count": 1, "rfid_count": 4}, "timestamp": "ISO8601"}
```

```json
{"type": "heartbeat", "battery": 85, "status": "flying",
 "position": {"x":1.5,"y":2.0,"z":3.0}}
```

```json
{"type": "stream_end", "reason": "task_completed"}
```

### 3.4 基站 → 无人机 消息格式（text JSON）

```json
{"type": "ack", "frame_id": 1234, "status": "ok"}
```

```json
{"type": "ack", "frame_id": 1235, "status": "dropped", "reason": "buffer_full"}
```

```json
{"type": "control", "action": "pause", "reason": "processing_backlog", "resume_in_sec": 5}
```

```json
{"type": "control", "action": "switch_to_upload", "reason": "ws_unstable",
 "fallback_url": "/api/v1/videos/upload"}
```

> `switch_to_upload` 是降级指令：当 WS 连续丢帧/超时，基站主动让无人机回退到 multipart 上传。

### 3.5 帧聚合策略

```python
MAX_BUFFER_FRAMES = 150        # 缓冲区达此帧数强制落盘
MAX_BUFFER_SECONDS = 30        # 缓冲达此秒数强制落盘
IDLE_FLUSH_SECONDS = 15        # 无新帧达此秒数触发落盘
TARGET_FPS = 10                # 编码用帧率
JPEG_QUALITY_THRESHOLD = 30    # 小于此字节数视为无效帧丢弃
CODEC = "mp4v"                  # OpenCV VideoWriter codec
```

**落盘触发条件**（满足任一 — **不切分视频**，单次 WS 会话产出单一 mp4 文件）：

1. `len(frame_buffer) >= MAX_BUFFER_FRAMES`
2. `now - first_frame_time >= MAX_BUFFER_SECONDS`
3. `now - last_frame_time >= IDLE_FLUSH_SECONDS`（空闲超时）
4. 收到 `stream_end` 或连接断开

> **注**：收到 `waypoint_enter` 不触发落盘，仅追加 `waypoint_markers` 数组项（见第 四 章）。

**编码流程**（守护线程）：

1. `cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)` 解码首帧获取尺寸
2. `cv2.VideoWriter(path, fourcc, TARGET_FPS, (w, h))`
3. 逐帧 `imdecode → writer.write()`
4. 写 `VideoData` 记录（`source='ws_stream'`、`waypoint_markers=JSON`、`stream_session_id`、`frame_rate_actual`）
5. 复用 `services/video_postprocess.py:postprocess_video()` 抽帧 QR + 写 `InventoryItem` + 交叉校验
6. 广播 `video_processed` 事件

### 3.6 文件命名与存储路径

```
storage/videos/{task_code|no_task}/{drone_code}/
  ws_{session_id}.mp4
```

> **注**：文件名不再包含 `waypoint_id` 与 `segment_index`，单次 WS 会话产出单一 mp4 文件，所有航点位置标记存入 `VideoData.waypoint_markers` JSON 数组。

***

## 四、视频航点帧标记（不切分）

> **设计变更说明**：原设计为"按航点切分视频，每段一个 VideoData 行"，用户在 2026-07-05 澄清后改为"不切分视频，单文件 + waypoint_markers 数组标记"。

### 4.1 收到 `waypoint_enter` 的处理流程

```
WS 收到 waypoint_enter 消息
  │
  ▼
ws_video.py 协程
  ├─ 1. 解析 waypoint_id / task_code / expected_sku / position
  ├─ 2. aggregator.mark_waypoint(session, waypoint_id, expected_sku, position)
  │      │
  │      ▼
  │   DroneStreamSession
  │      ├─ 取当前 frame_count 作为 frame_index
  │      ├─ 取当前时间戳
  │      └─ 追加到 waypoint_markers 数组：
  │           {waypoint_id, frame_index, timestamp, expected_sku, position}
  │      ⚠️ 不触发落盘，不切分视频，不创建 VideoData 行
  ├─ 3. upsert Waypoint 记录（若不存在则创建，含 task_id/shelf_code/expected_sku）
  ├─ 4. 回复 ack（含 frame_index）
  └─ 5. 广播 waypoint_changed 事件给 /ws/monitor
```

### 4.2 会话关闭 → VideoData 写入（单一记录）

```python
video_rec = VideoData(
    file_name=filename,
    file_path=file_path,
    file_size=file_size,
    drone_id=drone.id,
    task_code=task_code,
    waypoint_id=None,                # ← 不绑定单一 waypoint，所有标记在 waypoint_markers
    captured_at=datetime.utcnow(),
    processing_status="extracting",
    source="ws_stream",              # ← 区分来源
    stream_session_id=session_id,
    frame_rate_actual=actual_fps,
    waypoint_markers=json.dumps(markers),  # ← JSON 数组：所有航点位置
)
db.add(video_rec)
db.commit()
# → 调用 postprocess_video() 抽帧 QR + 写 InventoryItem
# → _cross_validate_qr_rfid(task_code, waypoint_id=None, qr_codes, None, db)
#   （waypoint_id 由 postprocess_video 内部从 waypoint_markers 解析或按时间戳最近原则匹配）
```

### 4.3 边界场景

| 场景                                          | 处理                                                             |
| ------------------------------------------- | -------------------------------------------------------------- |
| 无人机未发 `waypoint_enter` 就推帧                  | `waypoint_markers=[]`，仍写单一 VideoData 行                          |
| 连续多个 `waypoint_enter` 之间无帧                  | 仍追加 marker（不同 frame_index），不创建空段                                |
| WS 断开重连                                     | 新 `stream_session_id`，`waypoint_markers` 数组重新从空开始              |
| `waypoint_leave` 未收到直接 `waypoint_enter` 下一个 | 仅追加新 marker，不影响已有 marker                                       |

***

## 五、QR 双图保存实现

### 5.1 插入位置

在 [qr\_worker.py:QRRecognitionEngine.\_process\_one()](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/image/qr_worker.py#L149) 中：

* **第 188-197 行解码循环**：保留命中 `crop_img` 与 `bbox`

* **第 209-244 行写入结果**：保存双图

### 5.2 改动要点

#### 修改解码循环（保留命中 crop 与 bbox）

```python
# 在 _process_one 的解码循环中
hit_crop = None
hit_bbox = None
for crop_img, bbox, crop_conf in all_regions:
    text, conf, dec = self._try_decode(crop_img)
    if text:
        if confidence == 0.0 or conf > confidence:
            qr_text, confidence, decoder = text, conf, dec
            hit_crop = crop_img
            hit_bbox = bbox
        if conf > 0.8:
            break
```

#### 写入结果处保存双图

```python
# 仅在 qr_text 命中时保存
if qr_text and hit_crop is not None and hit_bbox is not None:
    crop_dir = os.path.join(STORAGE_ROOT, "qr_crops",
                            record.task_id or "no_task",
                            record.waypoint_id or "no_wp")
    os.makedirs(crop_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    crop_path = os.path.join(crop_dir, f"crop_{record.id}_{ts}.jpg")
    annot_path = os.path.join(crop_dir, f"annotated_{record.id}_{ts}.jpg")

    # 1. 裁剪图（复用 image.crop.save_image）
    from ..image.crop import save_image
    save_image(hit_crop, crop_path, format="jpg")

    # 2. 标注图（新模块 image.annotator）
    from ..image.annotator import draw_qr_bbox, save_annotated
    annotated = draw_qr_bbox(img, hit_bbox, label=qr_text)
    save_annotated(annotated, annot_path, format="jpg")

    record.qr_cropped_path = crop_path
    record.annotated_path = annot_path
```

### 5.3 `image/annotator.py` 设计

```python
def draw_qr_bbox(img: np.ndarray, bbox: tuple, label: str = "",
                 color=(0, 255, 0), thickness=2) -> np.ndarray:
    """在原图上绘制 QR 框选矩形 + 标签"""
    x, y, w, h = bbox
    out = img.copy()
    cv2.rectangle(out, (x, y), (x + w, y + h), color, thickness)
    if label:
        cv2.putText(out, label, (x, max(0, y - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return out

def save_annotated(image, path, format="jpg") -> bool:
    # 委托 crop.save_image
    from .crop import save_image
    return save_image(image, path, format)
```

### 5.4 命名规则与存储路径

| 图类型 | 路径模板                                                                                    |
| --- | --------------------------------------------------------------------------------------- |
| 裁剪图 | `storage/qr_crops/{task_code}/{waypoint_id}/crop_{image_id}_{yyyyMMdd_HHmmss}.jpg`      |
| 标注图 | `storage/qr_crops/{task_code}/{waypoint_id}/annotated_{image_id}_{yyyyMMdd_HHmmss}.jpg` |

### 5.5 兜底情况

* QR 未识别（`qr_text is None`）：不保存双图，两字段保持 NULL

* `hit_bbox` 来自全图回退（`img.shape` 整图边框）：仍保存标注图，但框选为整图边框（视觉上提示"未定位到具体区域"）

***

## 六、Electron 删除清单

### 6.1 删除目录

| 路径                       | 说明                                                                                                                  |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `app/desktop-app/`（整个目录） | `main.js`/`preload.js`/`launcher.html`/`package.json`/`package-lock.json`/`README.md`/`icon.png`/`generate-icon.js` |

### 6.2 docker-compose.yml 修改点

**无需改动**。`frontend` 服务挂载 `./app:/app` 仍需 `app/index.html`/`app/login.html`/`app/root-index.html`，仅 `app/desktop-app/` 子目录被删除。

### 6.3 文档与脚本更新点

| 文件                    | 修改                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------- |
| `doc/全系统改进方案.md`      | 删除拓扑图中"桌面应用 (Electron)"节点；删除 1.2 节"桌面应用"段落；删除 3.1 节"桌面应用 (Electron)"分支；删除六、启动顺序中"第2步：桌面应用启动"      |
| `doc/无人机端开发规范.md`     | 升级文档版本号 v3.0；新增 WS 图传协议章节                                                                         |
| `Makefile`            | 删除 `.PHONY` 中的 `desktop`；删除 `install` 中的 `cd app/desktop-app && npm install`；删除 `desktop:` target |
| `app/deploy-linux.sh` | 删除 desktop-app npm install 段                                                                      |
| `启动.bat`              | 删除 `start_desktop`/`init_desktop` 分支与 electron 进程检测                                               |
| `project_memory.md`   | 新增"WS 视频流协议速查"+"QR 双图存储路径约定"                                                                      |

***

## 七、实施顺序（按依赖关系）

### 阶段 1：数据库与模型基础（半天）

**产出**：新字段就绪，迁移可重复执行

1. 修改 `models/models.py`：给 `VideoData`、`ImageRecord` 加字段
2. 新建 `db/migrations.py`：实现 `run_migrations(engine)`
3. 修改 `db/database.py:init_db()`：末尾调用 `run_migrations(engine)`
4. 新建 `tests/test_migrations.py`：验证幂等（连续跑 2 次不报错）

**验证**：启动服务，`\d video_data` 和 `\d image_records` 看到新字段；旧接口功能不回归。

### 阶段 2：QR 双图保存（独立可上线，1 天）

**产出**：QR 识别后产出双图

1. 新建 `image/annotator.py`：`draw_qr_bbox` + `save_annotated`
2. 修改 `qr_worker.py:_process_one()`：保留 `hit_crop/hit_bbox`，写入双图路径
3. 修改 `images.py:get_image_info`：响应追加 `qr_cropped_path`/`annotated_path`
4. 新建 `tests/test_qr_dual_image.py`：mock 图像 → 提交识别 → 断言两文件存在 + DB 字段非空

**验证**：`POST /api/v1/images/upload` 一张含 QR 的图，识别完成后在 `storage/qr_crops/` 看到两张图，`GET /api/v1/images/{id}` 返回路径。

### 阶段 3：视频后处理抽取（重构，1 天）

**产出**：`gateway.py` 与 `videos.py` 共用 `postprocess_video()`

1. 新建 `services/video_postprocess.py`：把 `videos.py:_process_video_background` 中的抽帧+QR+InventoryItem+交叉校验逻辑抽出为 `postprocess_video(file_path, video_rec, task_code, waypoint_id, expected_sku, drone_id, source)`
2. `videos.py` 与 `gateway.py:_process_video_in_background` 改为调用该函数
3. 两者写入 `VideoData` 时设置 `source` 字段
4. 回归测试：`POST /api/v1/videos/upload` 与 `gateway/receive` 视频通道行为不变

**验证**：上传视频后 QR 识别、InventoryItem 写入、交叉校验事件正常广播。

### 阶段 4：WS 视频流端点（2 天）

**产出**：`/ws/video/{drone_code}` 可接收帧并落盘

1. 新建 `services/video_stream_aggregator.py`：`VideoStreamAggregator` 单例 + `DroneStreamSession` + 编码守护线程
2. 新建 `api/ws_video.py`：实现端点，处理 `stream_start`/`waypoint_enter`/`waypoint_leave`/`stream_end`/`heartbeat`/binary 帧
3. 修改 `main.py`：lifespan 启动/停止 aggregator；注册 `ws_video.router`
4. 修改 `ws.py:get_workers_status()`：增加 `video_stream` 状态
5. 新建 `tests/test_ws_video.py` + `tests/test_video_stream_aggregator.py`：注入伪帧验证航点帧标记

**验证**：用 Python `websockets` 客户端脚本模拟无人机推 50 帧 + 2 个 `waypoint_enter`，断言产出 1 个 `VideoData` 行（不切分），`waypoint_markers` 数组长度为 2，QR 识别正常。

### 阶段 5：航点切分与 Waypoint 关联（1 天） — **已合并至阶段 4**

**产出**：~~段按航点切分~~ → 改为：航点帧位置标记到 `waypoint_markers` 数组，Waypoint 状态联动

1. 在 `aggregator.on_waypoint_enter` 中实现"先 flush 上一段再切换"
2. `waypoint_enter` 时 upsert Waypoint（若不存在则创建）
3. `waypoint_leave` 时更新 `Waypoint.status='completed'`、`scanned_at`
4. `flush_segment` 调用 `postprocess_video(expected_sku=waypoint.expected_sku)`

**验证**：推帧 → 发 `waypoint_enter(WP1)` → 推帧 → 发 `waypoint_enter(WP2)` → 发 `stream_end`，DB 中应有 3 段（WP1前/ WP1段/ WP2段），每段 `waypoint_id` 正确。

### 阶段 6：api-gateway WS 反向代理（半天）

**产出**：无人机经 8080 端口接入

1. 修改 `app/api-gateway/main.py`：新增 `/ws/video/{drone_code}` WS 代理，**同时转发 text + binary**（参照现有 `/ws/monitor` 代理 [main.py:212-269](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/app/api-gateway/main.py#L212)，但 `forward_*` 函数用 `receive()` 而非 `receive_text()`，按消息类型分发）
2. 验证：直连 8001 与经 8080 代理两种路径都能推流

**验证**：`wscat -c ws://localhost:8080/ws/video/DRONE001` 连接成功，发 binary 帧能落地。

### 阶段 7：Electron 删除（半天，独立可并行）

**产出**：删除 desktop-app，清理引用

1. 删除 `app/desktop-app/` 整个目录
2. 修改 `Makefile`、`app/deploy-linux.sh`、`启动.bat`
3. 更新 `doc/全系统改进方案.md`、`doc/无人机端开发规范.md`
4. 更新 `project_memory.md`、`logs/devlog.md`

**验证**：`make help` 不再出现 desktop；`./启动.bat` 菜单不再有桌面应用选项；`docker-compose up` 不报错。

### 阶段 8：联调与文档（1 天）

**产出**：端到端打通

1. 更新 `doc/无人机端开发规范.md`：完整 WS 协议章节
2. 模拟器全流程测试：心跳 → WS 推流 → 航点帧标记 → QR 识别 → 交叉校验 → 报告
3. 网络降级测试：断开 WS → 无人机回退 `POST /api/v1/videos/upload`

***

## 八、风险点和兼容性

### 8.1 可能影响现有功能

| 改动                            | 影响                                  | 缓解                                                          |
| ----------------------------- | ----------------------------------- | ----------------------------------------------------------- |
| `ImageRecord` 加字段             | `images.py` 序列化响应变化                 | 仅新增字段，旧客户端忽略即可                                              |
| `qr_worker._process_one()` 改动 | QR 识别主流程                            | 仅在 `qr_text` 命中时新增保存逻辑，未命中路径不变                              |
| 抽取 `postprocess_video()`      | `videos.py`/`gateway.py` 视频处理       | 行为完全等价，仅去重；通过阶段 3 回归测试验证                                    |
| 新增 WS 端点                      | `main.py` lifespan 增加 aggregator 启停 | aggregator 守护线程，启动失败不阻塞 FastAPI；shutdown 优雅等待编码完成（超时 5s 强退） |
| 删除 desktop-app                | 启动脚本/Makefile                       | 阶段 7 独立执行，先改脚本再删目录                                          |
| api-gateway WS 代理             | 网关增加 binary 转发                      | 现有 `/ws/monitor` 代理仅转 text，新代理独立函数，互不影响                     |

### 8.2 数据迁移风险

| 风险                            | 缓解                                                            |
| ----------------------------- | ------------------------------------------------------------- |
| `ADD COLUMN IF NOT EXISTS` 幂等 | PostgreSQL 9.6+ 支持，项目用 PG 16-alpine                           |
| 旧数据新字段为 NULL                  | `source` 默认 `'upload'`；`qr_cropped_path` 等为 NULL，查询时判空        |
| 迁移中途失败                        | `run_migrations` 在事务中执行，失败整体回滚；每条 SQL 独立 `IF NOT EXISTS`，重跑安全 |

### 8.3 WS 流特有风险

| 风险                    | 缓解                                                                          |
| --------------------- | --------------------------------------------------------------------------- |
| 帧丢失（网络抖动）             | 基站端 `frame_id` 递增，发现 gap 仅记日志不重传（视频非关键应用）                                   |
| 缓冲区溢出                 | `queue.Queue(maxsize=500)`，满时丢弃并广播 `queue_full` 事件；同时向无人机发 `control: pause` |
| 编码线程阻塞                | 编码在独立守护线程，与 WS 接收解耦；编码慢时缓冲堆积触发 `control: reduce_fps`                        |
| 内存泄漏（长连接）             | `MAX_BUFFER_FRAMES=150` 强制落盘 + `IDLE_FLUSH_SECONDS=15` 空闲落盘                 |
| WS 断开后未发 `stream_end` | `IDLE_FLUSH_SECONDS` 触发落盘；连接关闭时 `finally` 强制 flush                          |
| 无人机未注册 `drone_code`   | WS 端点首步查 DB，不存在则 `close(4404)`                                              |
| cv2.VideoWriter 编码失败  | 捕获异常，写 `VideoData.processing_status='failed'`，不阻塞后续段                        |

### 8.4 回滚方案

| 阶段                   | 回滚方式                                                         |
| -------------------- | ------------------------------------------------------------ |
| 阶段 1（迁移）             | 新字段为 nullable + 有默认值，回滚无需删列；保留即可不影响                          |
| 阶段 2（QR 双图）          | 在 `qr_worker` 加配置开关 `ENABLE_DUAL_IMAGE_SAVE=True`，回滚时设 False |
| 阶段 3（postprocess 抽取） | git revert 该次提交，恢复 `videos.py`/`gateway.py` 原内联实现            |
| 阶段 4-5（WS 端点）        | 不注册 `ws_video.router` 即可禁用；WS 端点存在但不被调用无副作用                  |
| 阶段 6（网关代理）           | 删除 api-gateway 中新增的 `/ws/video` 路由                           |
| 阶段 7（Electron 删除）    | git revert；desktop-app 目录可从历史 commit 恢复                      |

> 全程通过 feature flag（环境变量 `ENABLE_WS_VIDEO_STREAM=True`）控制 WS 端点是否注册，可在 `main.py` 中条件加载，出问题时关闭 flag 即回退到纯 multipart 模式。

***

## 九、验证测试方案

### 9.1 单元测试

| 测试文件                                    | 验证内容                               |
| --------------------------------------- | ---------------------------------- |
| `tests/test_migrations.py`              | 迁移幂等性（连续跑 2 次不报错）                  |
| `tests/test_qr_dual_image.py`           | mock 图像 → 提交识别 → 断言两文件存在 + DB 字段非空 |
| `tests/test_video_stream_aggregator.py` | 伪帧注入 + 航点帧标记验证                      |

### 9.2 集成测试

```python
# tests/test_ws_video.py 核心场景
async def test_ws_video_stream_with_waypoint_markers():
    async with websockets.connect("ws://localhost:8001/ws/video/DRONE001") as ws:
        await ws.send(json.dumps({"type": "stream_start", "task_code": "T001"}))
        # 推 30 帧
        for i in range(30):
            await ws.send_binary(generate_fake_jpeg_frame())
        # 航点 1 进入（不触发落盘，仅追加 marker）
        await ws.send(json.dumps({
            "type": "waypoint_enter",
            "waypoint_id": "wp_001",
            "task_code": "T001",
            "expected_sku": "SKU001"
        }))
        # 推 30 帧
        for i in range(30):
            await ws.send_binary(generate_fake_jpeg_frame())
        # 航点 2 进入（不触发落盘，仅追加 marker）
        await ws.send(json.dumps({
            "type": "waypoint_enter",
            "waypoint_id": "wp_002",
            "task_code": "T001",
            "expected_sku": "SKU002"
        }))
        await ws.send(json.dumps({"type": "stream_end"}))

    # 断言 DB 中应有 1 段 VideoData（不切分），含 2 个航点标记
    video = db.query(VideoData).filter(
        VideoData.stream_session_id.isnot(None)
    ).one()
    markers = json.loads(video.waypoint_markers or "[]")
    assert len(markers) == 2
    assert markers[0]["waypoint_id"] == "wp_001"
    assert markers[1]["waypoint_id"] == "wp_002"
    assert markers[0]["frame_index"] < markers[1]["frame_index"]
```

### 9.3 端到端验证脚本

```bash
# 1. 启动服务
cd "e:\A0.software\The computer files\桌面\域感智能\yugan_base"
./启动.bat

# 2. 模拟无人机推流（Python 客户端）
python tests/e2e_simulate_drone_ws.py --drone DRONE001 --task T001 --waypoints wp_001,wp_002

# 3. 检查 DB
psql -U postgres -d warehouse -c "SELECT id, source, processing_status, stream_session_id, jsonb_array_length(waypoint_markers::jsonb) AS marker_count FROM video_data WHERE stream_session_id IS NOT NULL;"

# 4. 检查 QR 双图
ls storage/qr_crops/*/*/*.jpg

# 5. 验证 Electron 已删除
test ! -d app/desktop-app && echo "Electron 已删除"
```

***

## 十、关键设计决策摘要

1. **WS 帧用 binary JPEG，控制用 text JSON**：兼顾效率与可调试性，符合 FastAPI WebSocket 双模式特性。
2. **单条 VideoData 记录对应一次完整 WS 流会话**，到达航点时仅在 `waypoint_markers` JSON 数组中追加 `{waypoint_id, frame_index, timestamp, expected_sku, position}` 标记，不创建新的 VideoData 行（用户 2026-07-05 澄清："不新增航点，在到达每个航点时，标记那一帧视频帧"）。
3. **复用** **`postprocess_video()`** **公共函数**：WS 流、multipart 上传、gateway Base64 三条通道最终汇入同一后处理管线，保证 QR 识别与库存判定逻辑一致。
4. **迁移用** **`ADD COLUMN IF NOT EXISTS`** **而非 Alembic**：项目 Alembic 未集成（P3 优先级），此方案零依赖、幂等、PostgreSQL 原生支持。
5. **QR 双图保存位置在** **`_process_one`** **解码循环后**：能拿到命中的 `crop_img` 与 `bbox`，无需重复检测；仅在 `qr_text` 命中时保存。
6. **api-gateway 新增 WS 代理必须支持 binary 转发**：现有 `/ws/monitor` 代理仅转 text，新代理用 `receive()` 按消息类型分发。
7. **Feature flag 控制全局开关**：`ENABLE_WS_VIDEO_STREAM=True` 控制是否注册 WS 端点，出问题时关闭即可回退到纯 multipart 模式。

***

## 十一、Critical Files for Implementation

* [models/models.py](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/models/models.py) — VideoData/ImageRecord 加字段

* [qr\_worker.py](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/image/qr_worker.py) — `_process_one` 第 149-244 行插入双图保存

* [ws.py](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/api/ws.py) — EventBroadcaster 模式 + 新增 WS 视频端点的参考模板

* [gateway.py](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/station/warehouse-inspection-system/backend/src/api/gateway.py) — `_process_video_in_background` 第 702 行，抽取 `postprocess_video` 的源头

* [api-gateway/main.py](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/app/api-gateway/main.py) — 新增 `/ws/video/{drone_code}` WS 反向代理，须支持 binary 转发

***

## 十二、工作量估算

| 阶段                       | 工作量       | 可并行               |
| ------------------------ | --------- | ----------------- |
| 阶段 1：数据库与模型基础            | 0.5 天     | 否（其他阶段依赖）         |
| 阶段 2：QR 双图保存             | 1 天       | 是（与阶段 3 并行）       |
| 阶段 3：视频后处理抽取             | 1 天       | 是（与阶段 2 并行）       |
| 阶段 4：WS 视频流端点            | 2 天       | 否                 |
| 阶段 5：航点切分与 Waypoint 关联   | —（已合并至阶段 4） | —（已合并至阶段 4） |
| 阶段 6：api-gateway WS 反向代理 | 0.5 天     | 是（与阶段 4 并行）       |
| 阶段 7：Electron 删除         | 0.5 天     | 是（独立可并行）          |
| 阶段 8：联调与文档               | 1 天       | 否                 |
| **合计**                   | **7.5 天** | 实际工期约 5-6 天（并行优化） |

***

## 十三、实施差异说明

> 本章节记录原始设计（本文档前 12 章）与最终实现（Stages 1-7）之间的偏差，便于读者理解代码与文档差异的来源。

### 13.1 主要偏差：视频不再按航点切分

**原始设计**（本文档第 3.5 / 3.6 / 四 / 9.2 / 10 节描述）：
- 收到 `waypoint_enter` 时触发"上一段落盘 → 切换 waypoint → 段序号 +1"
- 一次 WS 会话产出多段 mp4 文件，每段对应一个 `VideoData` 行
- 数据库字段：`segment_index INTEGER` 表示段序号
- 文件命名：`vid_{drone_code}_wp{waypoint_id}_{seg_index}_{ts}.mp4`

**最终实现**（用户 2026-07-05 澄清后）：
- 收到 `waypoint_enter` 时仅追加 `waypoint_markers` JSON 数组项
- 一次 WS 会话产出**单一 mp4 文件**，对应**单一 `VideoData` 行**
- 数据库字段：`waypoint_markers TEXT`（JSON 序列化的数组），原 `segment_index` 字段废弃
- 文件命名：`ws_{session_id}.mp4`
- 边界场景：`waypoint_markers=[]` 表示无航点标记的纯推流

**偏差原因**：用户审查设计稿后澄清："不新增航点，在到达每个航点时，标记那一帧视频帧"。原设计的"切分"语义改为"标记帧位置"，避免单次会话产出多段 VideoData 行带来的检索复杂度。

### 13.2 阶段 5 已合并至阶段 4

**原始设计**：阶段 5 为独立的"航点切分与 Waypoint 关联"（1 天），负责 flush_segment / upsert Waypoint / postprocess 联动。

**最终实现**：航点标记逻辑直接由 `DroneStreamSession.mark_waypoint()` 在阶段 4 中实现，无需独立阶段。

### 13.3 实施状态摘要

| 阶段 | 状态 | 备注 |
|------|------|------|
| 阶段 1：数据库与模型基础 | ✅ 已实施 | `db/migrations.py` + `models.py` 加 6 字段 |
| 阶段 2：QR 双图保存 | ✅ 已实施 | `image/annotator.py` + `qr_worker._save_qr_evidence_images` |
| 阶段 3：视频后处理抽取 | ✅ 已实施 | `services/video_postprocess.py` 公共函数 |
| 阶段 4：WS 视频流端点 | ✅ 已实施 | `services/video_stream_aggregator.py` + `api/ws_video.py` |
| 阶段 5：航点标记 | ✅ 已合并至阶段 4 | `waypoint_markers` 数组 |
| 阶段 6：api-gateway WS 代理 | ✅ 已实施 | `app/api-gateway/main.py:277` |
| 阶段 7：Electron 删除 | ✅ 已实施 | `app/desktop-app/` 已删除 + 3 脚本已清理 |
| 阶段 8：联调与文档 | ✅ 文档已就绪 | `doc/无人机端开发规范.md` v3.0 + `project_memory.md` + `logs/devlog.md` |

### 13.4 后续待办（不阻塞本设计稿完成）

- 端到端联调：模拟器全流程测试（心跳 → WS 推流 → 航点标记 → QR 识别 → 交叉校验 → 报告）
- 网络降级测试：断开 WS → 无人机回退 `POST /api/v1/videos/upload`
- 单元测试补齐：`tests/test_ws_video.py` / `tests/test_video_stream_aggregator.py` / `tests/test_qr_dual_image.py` / `tests/test_migrations.py`

