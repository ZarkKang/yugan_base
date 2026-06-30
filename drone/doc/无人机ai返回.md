# 无人机端 Trae 系统兼容性核查报告

> 核查对象：`uav_ground_bridge` 包
> 核查依据：基站下发的《无人机端 Trae 系统兼容性提示词》
> 核查原则：仅基于现有代码分析，不修改任何代码
> 生成时间：2026-06-26

涉及文件：
- `scripts/uav_ground_bridge_node.py`
- `scripts/video_stream_node.py`
- `launch/bridge.launch`
- `config/waypoints.yaml`
- `~/4.sh`（启动脚本）
- `logs/uav_ground_bridge_failed.jsonl`（实际发报样本）

---

## 连接参数 ✅ 全部一致

| 规范 | 代码实现 | 位置 |
|------|---------|------|
| `BASE_STATION_IP=192.168.1.100` | `video_target_host` 默认 `192.168.1.100` | `bridge.launch:17` |
| `DRONE_CODE=DRONE001` | `drone_code` 默认 `DRONE001` | `bridge.launch:3` |
| `BASE_PORT=8001` | `ground_url` 默认 `http://192.168.1.100:8001` | `bridge.launch:2` |
| `GROUND_URL` | `self.ground_url` + `.rstrip("/")` | `uav_ground_bridge_node.py:22` |

---

## 1. 心跳包 ✅ 完全合规

代码 `uav_ground_bridge_node.py:151-164`：

```python
body = {
    "drone_code": self.drone_code,
    "status": self.status,
    "battery": self.battery_percent,
    "position": dict(self.position),
    "timestamp": time.time(),
}
```

| 规范字段 | 代码 | 验证 | 位置 |
|---------|------|------|------|
| 路径 `POST /api/v1/drones/{DRONE_CODE}/heartbeat` | `"%s/api/v1/drones/%s/heartbeat"` | ✅ | `:161` |
| `Content-Type: application/json` | `requests.post(url, json=body)` | ✅ | `:251` |
| `drone_code` | ✅ | ✅ | `:154` |
| `status` | ✅ | ✅ | `:155` |
| `battery` (0-100, -1未知) | 默认 `-1`；`battery_cb` 限幅 0-100 | ✅ | `:38`, `:147` |
| `position` {x,y,z} 米 | `dict(self.position)` 浮点 | ✅ | `:157` |
| `timestamp` Unix秒浮点 | `time.time()` | ✅ | `:158` |
| 每5秒一次 | `heartbeat_interval=5.0` + `rospy.Timer` | ✅ | `:29`, `:59` |

失败日志样本（`logs/uav_ground_bridge_failed.jsonl`）证实实际发出的 body 字段与规范完全一致：

```json
{"drone_code":"DRONE001","status":"idle","battery":-1,"position":{"x":0.0,"y":0.0,"z":0.0},"timestamp":1781872297.797}
```

---

## 2. RFID扫描结果上传 ✅ 字段全合规

代码 `uav_ground_bridge_node.py:211-242`：

| 规范字段 | 代码 | 验证 | 位置 |
|---------|------|------|------|
| 路径 `POST /api/v1/gateway/receive` | `"%s/api/v1/gateway/receive"` | ✅ | `:239` |
| `drone_code` | ✅ | ✅ | `:221` |
| `data_type: "rfid"` | ✅ | ✅ | `:222` |
| `payload` 为 JSON **字符串** | `json.dumps(compact_tags, ensure_ascii=False)` | ✅ | `:223` |
| `position_x/y_z` | ✅ | ✅ | `:224-226` |
| `metadata.task_code` | `self.task_code`（来自 waypoints.yaml） | ✅ | `:228` |
| `metadata.waypoint_id` | `wp.get("id")` | ✅ | `:229` |
| `metadata.event: "waypoint_completed"` | 字面量 | ✅ | `:230` |
| `metadata.video_stream` | 默认 `udp://@:5600` | ✅ | `:231`, `:34` |
| `metadata.battery` | ✅ | ✅ | `:232` |
| `metadata.timestamp` | ✅ | ✅ | `:233` |

`compact_tags` 元素仅含 `epc / rssi_dbm / stamp` 三字段（`:214-218`），与规范示例完全一致。

---

## 3. 字段约束 ⚠️ 部分由上游负责，桥接节点未校验

| 规范 | 代码行为 | 评估 | 位置 |
|------|---------|------|------|
| `epc` 24字符大写hex | 透传 `rfid_cb` 收到的 `epc`，不做格式校验 | ⚠️ 依赖 `rfid_reader` 上游发布正确格式 | `:95-97` |
| `rssi_dbm` 有符号整数(-90~-30) | 透传 `data.get("rssi_dbm")`，不校验范围 | ⚠️ 同上 | `:102` |
| `timestamp` Unix秒浮点 | `time.time()` 浮点 | ✅ | — |
| `task_code` 与 waypoints.yaml 一致 | 从 `waypoints.yaml` 读取 `task_code: TASK001` | ✅ | `:89`, `waypoints.yaml:1` |
| `position` 米浮点 | `float(...)` 转换 | ✅ | — |
| `payload` JSON字符串非对象 | `json.dumps(...)` | ✅ | `:223` |

说明：epc / rssi_dbm 的格式合法性不在桥接节点职责内，由 `/rfid/tags` 话题发布方（`rfid_reader` 节点）保证。桥接节点只做转发。

---

## 4. 通信规则 ❌ 有一处超时不一致

| 规范 | 代码 | 验证 | 位置 |
|------|------|------|------|
| 心跳 HTTP 超时 1.5s | `timeout=1.5` | ✅ | `:251` |
| **扫描 HTTP 超时 10s** | **同样使用 `timeout=1.5`（硬编码，未区分 kind）** | ❌ **不符合** | `:251` |
| 异步发送不阻塞主循环 | `post_json_async` 起守护线程 | ✅ | `:244-247` |
| 不重试 | 单次 `requests.post`，无循环 | ✅ | `:250-258` |
| 失败写 `logs/uav_ground_bridge_failed.jsonl` | `self.failed_log` 路径正确 | ✅ | `:54` |
| 视频推流 `udp://192.168.1.100:5600` H.264/MPEG-TS | ffmpeg `-c:v libx264 -f mpegts udp://...:5600?pkt_size=1316` | ✅ | `video_stream_node.py:47,55,56` |

**唯一不合规项**：`post_json` 对 `heartbeat` 和 `waypoint_result`（即 RFID 扫描上传）使用同一个 `timeout=1.5`，未按规范对扫描用 10s。在大批量 RFID 标签或网络抖动时，`waypoint_result` 可能因 1.5s 超时而失败并写入 jsonl。

---

## 5. 状态机 ✅ 完全合规

代码 `uav_ground_bridge_node.py:166-203`：

| 规范 | 代码 | 验证 | 位置 |
|------|------|------|------|
| `idle→approaching→scanning→uploading→running→completed` | 状态转移完全一致 | ✅ | `:180-203` |
| 航点到达判定 `distance<=0.3m` 持续2秒 | `arrival_radius=0.3`, `arrival_hold_time=2.0` | ✅ | `:30-31`, `:182-189` |
| 扫描时长 `dwell_time` 默认5秒 | `wp.get("dwell_time", self.rfid_window)`，`rfid_window=5.0` | ✅ | `:194` |
| waypoints.yaml 中 `dwell_time: 5.0` | ✅ | ✅ | `waypoints.yaml:7,12,17` |

注：规范状态枚举还包含 `flying / returning / error`，代码未使用这三个值——这是合法子集，不算违规。

---

## 6. 兼容性自检 V1-V5 ❌ 大部分未实现

代码中**没有任何启动期自检逻辑**，`__init__` 末尾直接进入 `rospy.spin`（`:276-277`）。

| 规范 | 代码现状 | 评估 |
|------|---------|------|
| V1 POST心跳→HTTP200且`body.success==true` | 仅检查 `status_code<300`，**不解析 `body.success`** | ❌ `:252` |
| V2 GET /health→HTTP200且 database/redis==connected | **无任何 `/health` 探测代码** | ❌ 未实现 |
| V3 drone_code未注册返回404（检查注册） | 无预注册检查；收到 404 仅作为失败写日志 | ❌ 未实现 |
| V4 payload必须是字符串不是对象 | `json.dumps` 保证字符串 | ✅ `:223` |
| V5 task_code必须与基站任务一致 | 从本地 waypoints.yaml 读取，**不与基站校验** | ⚠️ 仅本地一致，需操作员保证与基站一致 |

---

## 7. 错误处理 ⚠️ 有一处语义偏差

| 规范 | 代码 | 验证 | 位置 |
|------|------|------|------|
| 永不崩溃：外部调用 try/except | `rfid_cb`/`battery_cb`/`post_json`/`write_failed` 全部 try/except 包裹 | ✅ | `:93-115`, `:144-149`, `:250-271` |
| 永不丢失：失败写本地 JSONL | `write_failed` 追加写 jsonl | ✅ | `:259-271` |
| **200成功清缓存，4xx/5xx写日志继续运行** | **缓存（`scan_tags`）在 `state_cb` 中调用 `upload_waypoint_result` 后立即清空（`:202`），此时 HTTP 尚在异步线程中未返回；若上传失败，缓存已丢失，仅 jsonl 保留** | ⚠️ **语义偏差**：不是"200成功才清缓存"，而是"无论成功失败都立即清缓存" | `:202` |

说明：失败数据仍可通过 `uav_ground_bridge_failed.jsonl` 手动重放（`README:74`），所以"永不丢失"在 jsonl 层面成立，但"200成功清缓存"的精确语义未实现。

---

## 8. 路径兼容 ✅ 合规

| 规范 | 代码 | 验证 | 位置 |
|------|------|------|------|
| 统一用 `/api/v1/` 前缀 | 心跳与 gateway 均用 `/api/v1/` | ✅ | `:161`, `:239` |
| 基站自动兼容 `/api/warehouse/` | 无人机端不发送该路径，由基站侧兼容 | ✅ 不涉及 | — |

---

## 汇总

| 章节 | 合规度 | 说明 |
|------|--------|------|
| 连接参数 | ✅ 4/4 | — |
| 1. 心跳包 | ✅ 全部 | 字段、路径、间隔均一致 |
| 2. RFID上传 | ✅ 全部 | payload 为 JSON 字符串 |
| 3. 字段约束 | ⚠️ 4/6 | epc/rssi_dbm 不校验，依赖上游 rfid_reader |
| 4. 通信规则 | ❌ 5/6 | **扫描超时应为 10s，实为 1.5s** |
| 5. 状态机 | ✅ 全部 | — |
| 6. 自检 V1-V5 | ❌ 1/5 | 仅 V4 天然满足；V1/V2/V3 未实现，V5 仅本地一致 |
| 7. 错误处理 | ⚠️ 2/3 | "200成功才清缓存"未精确实现（先清后发） |
| 8. 路径兼容 | ✅ 全部 | — |

---

## 关键不合规点（按严重度排序）

### 1. 【功能影响】第4节 扫描超时
`post_json` 对 `waypoint_result` 也用 `timeout=1.5`，规范要求 10s。在标签多或网络抖动时，RFID 上传会误判失败。位置 `uav_ground_bridge_node.py:251`。

### 2. 【可靠性影响】第7节 缓存清理时机
`scan_tags` 在调用异步上传后立即清空（`:202`），不等 HTTP 200 返回。若上传失败，本次航点的标签数据只在 `uav_ground_bridge_failed.jsonl` 中留底，需手动重放。

### 3. 【运维影响】第6节 自检缺失
无 `/health` 探测、无 drone_code 注册预检、不解析 `body.success`。启动时无法主动发现基站侧故障或注册缺失，只能靠心跳失败被动写日志。

### 4. 【数据质量】第3节 epc/rssi 校验
桥接节点不校验 epc 是否 24 字符大写 hex、rssi 是否在 -90~-30。需由 `/rfid/tags` 发布方保证。

---

## 已验证合规的关键点

- 心跳 body 字段与规范逐字段一致（且有失败日志佐证实际发报内容）
- RFID 上传 `payload` 确为 JSON 字符串（`json.dumps`）
- 状态机转移、航点判定 0.3m/2s、dwell_time 5s 全部一致
- 视频推流 `libx264 + mpegts + udp://192.168.1.100:5600` 与规范 H.264/MPEG-TS 一致
- 所有外部调用均有 try/except，失败写 jsonl，节点不会崩溃

---

## 附：实际发报样本（来自 logs/uav_ground_bridge_failed.jsonl）

心跳实际 body（证实字段与规范一致）：

```json
{
  "drone_code": "DRONE001",
  "status": "idle",
  "battery": -1,
  "position": {"x": 0.0, "y": 0.0, "z": 0.0},
  "timestamp": 1781872297.7970207
}
```

URL：`http://192.168.1.100:8001/api/v1/drones/DRONE001/heartbeat`

失败原因（历史样本）：基站当时不可达，`connect timeout=1.5`（与代码 `:251` 一致）。

> 注：当前基站 `192.168.1.100:8001` 已恢复可达（HTTP 200），心跳与 RFID 上传链路具备工作条件。
