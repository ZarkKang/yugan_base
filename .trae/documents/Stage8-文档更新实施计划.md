# Stage 8 — 文档更新实施计划

> 文档目的：在 Stages 1-7 已实施完成的基础上，执行原计划 [`架构改造比对与剩余实施计划.md`](file:///e:/A0.software/The%20computer%20files/%E6%A1%8C%E9%9D%A2/%E5%9F%9F%E6%84%9F%E6%99%BA%E8%83%BD/yugan_base/.trae/documents/架构改造比对与剩余实施计划.md) 中 Stage 8 的 5 项文档收尾工作。
> 编写日期：2026-07-05
> 当前代码库状态：Stages 1-7 已验证完成。

---

## 一、Phase 1 探索结果（已验证）

### 1.1 Stages 1-7 实施状态确认

| Stage | 实施内容 | 验证方式 | 状态 |
|-------|---------|---------|------|
| 1 | VideoData/ImageRecord 加字段 + `db/migrations.py` 幂等迁移 | Glob 确认 `migrations.py` 存在；前期已落地 | ✅ |
| 2 | QR 双图保存（`annotator.py` + `qr_worker._save_qr_evidence_images`） | 前期已落地（ImageRecord 新字段已在 `images.py` 响应返回） | ✅ |
| 3 | `video_postprocess.py` 抽取 + `videos.py` / `gateway.py` 薄包装 + `source` 字段 | Grep 命中 `videos.py:40,47,133` / `gateway.py:749,758,767` 调用 `postprocess_video(source="upload"/"gateway")` | ✅ |
| 4 | `video_stream_aggregator.py` + `ws_video.py` + `main.py` 注册 + lifespan shutdown + `ws.py` 状态查询 | Glob 确认两个新文件存在；`main.py:21` 导入 ws_video_api；`main.py:114-119` shutdown；`ws.py:200,231-236` 状态字段 | ✅ |
| 5 | 航点帧标记逻辑（已合并进 Stage 4 的 `waypoint_markers` 数组） | `video_stream_aggregator.DroneStreamSession.mark_waypoint()` 已实现 | ✅ |
| 6 | api-gateway `/ws/video/{drone_code}` 反向代理（双模转发） | Grep 命中 `app/api-gateway/main.py:277-288` | ✅ |
| 7 | 删除 `app/desktop-app/` + 改 Makefile/deploy-linux.sh/启动.bat/全系统改进方案.md | Glob `app/desktop-app/**` 返回空；3 个脚本已无 desktop 引用 | ✅ |

### 1.2 Stage 8 文档当前状态（全部待办）

| 子任务 | 目标文件 | 当前状态 |
|--------|---------|---------|
| 8.1 | `.trae/documents/架构改造方案-WS图传与QR双图.md` | 文件存在，但大量描述"按航点切分视频"旧设计，与代码实际实现（"不切分，仅标记帧位置"）矛盾 |
| 8.2 | `doc/无人机端开发规范.md` | ❌ 不存在，需创建 |
| 8.3 | `project_memory.md` | 未含 WS 协议速查 / QR 双图路径 / VideoData.source 语义 |
| 8.4 | `logs/devlog.md` | ❌ 不存在，需创建（含 Stage 1-7 变更记录） |
| 8.5 | `doc/全系统改进方案.md` 3.2.4 节 | 仍残留 `scan_router.py` 代码块（lines 309-359），用户已标"舍弃" |

---

## 二、Stage 8 详细实施清单

### 8.1 更新 `.trae/documents/架构改造方案-WS图传与QR双图.md`（综合对齐）

**决策（无需再问用户）**：原计划仅列"line 99 字段表 + 第 5 章标题"两处改动。但 Phase 1 阅读发现，该文档**多处描述"按航点切分"的旧设计**，与代码实际实现（"不切分，仅标记帧位置"）严重矛盾。仅做两处改动会让文档自相矛盾、对读者误导。原计划"同步代码实际实现"的本意即要求**全面对齐**，故本计划采取综合更新策略。

**修改清单**：

1. **文档顶部**：在 `> 计划文件 · 用于用户审批后开始执行` 之后追加实施状态备注：
   ```
   > 实施状态：Stages 1-7 已实施完成（2026-07-05）；Stage 5 已合并至 Stage 4；本文档为原始设计稿，与最终实现差异已通过 `## 实施差异说明` 章节标注（见末尾）
   ```

2. **第 1.2 节"修改文件"表（line 62）**：`VideoData 加 source/segment_index/stream_session_id/frame_rate_actual` → `VideoData 加 source/waypoint_markers/stream_session_id/frame_rate_actual`

3. **第 2.1 节字段表（line 99）**：将 `segment_index` 行替换为：
   ```
   | `waypoint_markers` | `Text` nullable | 航点标记帧 JSON 数组: `[{waypoint_id, frame_index, timestamp, expected_sku, position}, ...]` — 不切分视频，仅记录航点对应视频帧位置 |
   ```

4. **第 2.3 节迁移 SQL**：将 `ALTER TABLE video_data ADD COLUMN IF NOT EXISTS segment_index INTEGER DEFAULT 0` 改为：
   ```sql
   ALTER TABLE video_data ADD COLUMN IF NOT EXISTS waypoint_markers TEXT
   ```
   并在 `CREATE INDEX` 后追加注释说明 `waypoint_markers` 为应用层 JSON 序列化的 TEXT。

5. **第 3.5 节"帧聚合策略"**：删除"按 waypoint_enter 触发分段落盘"逻辑，改为：
   - 单一视频文件覆盖整个 WS 会话
   - `waypoint_enter` 仅触发 `session.mark_waypoint()` 追加 `waypoint_markers` 数组项（不切分、不落盘）
   - 落盘触发条件仅保留：缓冲满 / 缓冲超时 / 空闲超时 / stream_end / 连接断开

6. **第 3.6 节文件命名**：将 `vid_{drone_code}_wp{waypoint_id_or_none}_{seg_index}_{yyyyMMdd_HHmmss}.mp4` 改为 `vid_{drone_code}_{session_id}_{yyyyMMdd_HHmmss}.mp4`（移除 waypoint_id 和 seg_index）

7. **第 四 章"视频按航点切分逻辑"**：整章重写为"视频航点帧标记（不切分）"：
   - 标题：`## 四、视频航点帧标记（不切分）`
   - 4.1 收到 `waypoint_enter` 的处理流程：移除"触发 flush_segment"步骤，改为"调用 `aggregator.mark_waypoint()` 追加 `waypoint_markers` 数组项"
   - 4.2 段落盘 → VideoData 写入：删除 `segment_index` 字段，改为单一 VideoData 行含 `waypoint_markers=JSON` 字段
   - 4.3 边界场景表：移除"WS 断开重连 → segment_index 从 0 重新计数"行，改为"WS 断开重连 → 新 stream_session_id，waypoint_markers 数组重新从空开始"

8. **第 9.2 节集成测试代码**：将断言"3 段 VideoData"改为"1 段 VideoData + waypoint_markers 数组长度为 2"：
   ```python
   # 断言 DB 中应有 1 段 VideoData（不切分），含 2 个航点标记
   video = db.query(VideoData).filter(
       VideoData.stream_session_id.isnot(None)
   ).one()
   markers = json.loads(video.waypoint_markers or "[]")
   assert len(markers) == 2
   assert markers[0]["waypoint_id"] == "wp_001"
   assert markers[1]["waypoint_id"] == "wp_002"
   ```

9. **第 10 节"关键设计决策摘要"item 2**：将"每段视频绑定一个 waypoint_id，写入独立 VideoData 行"改为"**单条 VideoData 记录对应一次完整 WS 流会话**，到达航点时仅在 `waypoint_markers` JSON 数组中追加 `{waypoint_id, frame_index, timestamp, expected_sku, position}` 标记，不创建新的 VideoData 行"

10. **第 12 节工作量估算表**：阶段 5 行的"可并行"列改为"—（已合并至阶段 4）"

11. **新增末尾章节 `## 十三、实施差异说明`**：明确列出与原始设计的偏差：
    - `segment_index` 字段废弃，改用 `waypoint_markers` JSON 数组（用户在 2026-07-05 澄清："不新增航点，在到达每个航点时，标记那一帧视频帧"）
    - 视频不再按航点切分为多段，而是单文件 + 帧标记

### 8.2 创建 `doc/无人机端开发规范.md` v3.0

**新文件路径**：`e:\A0.software\The computer files\桌面\域感智能\yugan_base\doc\无人机端开发规范.md`

**说明**：`project_memory.md` 中"目录结构约定"提到 `doc/drone/` 子目录用于无人机端文档，但当前 `doc/` 下无 `drone/` 子目录且原计划明确指定 `doc/无人机端开发规范.md`，遵循原计划路径（避免引入新的目录约定变更）。

**版本号**：v3.0（主版本变更：新增 WS 视频流协议 + 删除无人机端 QR 识别职责）

**章节大纲**（按原计划）：
1. 系统架构与通信拓扑（无人机↔基站网络拓扑图）
2. 接口规范
   - HTTP REST：任务获取、心跳上报、状态更新、固件查询
   - **WebSocket 图传流协议（新增，重点章节）**
     - 端点：`ws://192.168.1.200:8080/ws/video/{drone_code}`
     - 消息分类：binary（JPEG 帧）/ text（JSON 控制）
     - 控制消息类型：`stream_start` / `waypoint_enter` / `waypoint_leave` / `stream_stop` / `heartbeat`
     - 数据格式示例（每种消息完整 JSON 示例）
     - 关键字段说明：`waypoint_id` / `expected_sku` / `position` / `frame_index`
   - 网络降级策略：WS 不稳定时回退 `POST /api/v1/videos/upload`
3. 数据格式规范
   - 心跳数据结构（电池、位置、状态）
   - 任务进度上报结构
   - 航点数据结构（含 expected_sku）
4. 功能需求矩阵
   - 必选：任务获取、心跳、WS 推流、航点标记、状态更新
   - 可选：RFID 复核、避障、固件升级
   - **不再要求**：QR 识别（已转移至基站端）
5. 技术参数与约束
   - 默认 FPS：15（建议 10-30）
   - JPEG 质量：≥ 70（建议 85）
   - 单帧字节数：≥ 5KB（小于 30 字节视为无效帧）
   - 断线重连策略：指数退避（1s/2s/4s/8s，最大 30s）
   - 心跳间隔：5s（超时 30s 视为离线）
6. 开发进度追踪
7. 测试标准（含 WS 推流测试用例）
8. 代码示例（Python `websockets` 客户端最小实现 + 基站端处理逻辑引用）

### 8.3 更新 `project_memory.md`

在文件末尾"未来计划"小节之前插入三个新小节：

```markdown
## WS 图传协议速查

| 项 | 值 |
|----|----|
| 端点 | `ws://192.168.1.200:8080/ws/video/{drone_code}`（经 api-gateway） |
| 直连端点 | `ws://192.168.1.200:8001/ws/video/{drone_code}`（warehouse 直连，仅内网测试用） |
| 帧消息 | binary（JPEG 字节流，无包装） |
| 控制消息 | text（JSON，必含 `type` 字段） |
| 控制消息类型 | `stream_start` / `waypoint_enter` / `waypoint_leave` / `stream_stop` / `heartbeat` |
| 默认 FPS | 15 |
| 单文件策略 | 一次 WS 会话 = 一个 mp4 文件 + 一个 VideoData 行 |
| 航点不切分 | 到达航点仅追加 `waypoint_markers` JSON 数组项，不切分视频 |
| 网络降级 | WS 不稳定时无人机回退 `POST /api/v1/videos/upload` |
| 实现文件 | `services/video_stream_aggregator.py` + `api/ws_video.py` + `app/api-gateway/main.py:277` |

## QR 双图保存路径约定

- 裁剪 QR 区域小图：`storage/qr_crops/{task_id_or_no_task}/{waypoint_id_or_no_wp}/crop_{image_id}_{yyyyMMdd_HHmmss}.jpg`
- 带 QR 框选标注的原图：`storage/qr_crops/{task_id_or_no_task}/{waypoint_id_or_no_wp}/annotated_{image_id}_{yyyyMMdd_HHmmss}.jpg`
- 仅在 QR 命中时保存（`qr_text is not None`），未命中两字段保持 NULL
- 实现入口：`image/qr_worker.py:_save_qr_evidence_images()`，复用 `image/annotator.draw_qr_bbox()` + `image/crop.save_image()`
- 数据库字段：`ImageRecord.qr_cropped_path` / `ImageRecord.annotated_path`

## VideoData.source 字段语义

| 取值 | 含义 | 上传通道 | 触发后处理 |
|------|------|---------|-----------|
| `upload` | 无人机 multipart 文件上传 | `POST /api/v1/videos/upload` | `videos.py:_process_video_background` → `postprocess_video(source="upload")` |
| `gateway` | 无人机经 gateway Base64 上传 | `POST /api/warehouse/videos/...` | `gateway.py:_process_video_in_background` → `postprocess_video(source="gateway")` |
| `ws_stream` | 无人机 WS 实时图传 | `WS /ws/video/{drone_code}` | `video_stream_aggregator.close_session()` → `postprocess_video(source="ws_stream")` |

三条通道最终汇入 `services/video_postprocess.postprocess_video()` 公共管线，保证 QR 识别 + InventoryItem 写入 + 交叉校验逻辑一致。
```

### 8.4 创建 `logs/devlog.md`

**新文件路径**：`e:\A0.software\The computer files\桌面\域感智能\yugan_base\logs\devlog.md`

**说明**：`project_memory.md` 已约定 `logs/devlog.md` 为开发日志标准位置；当前文件不存在，本次需创建并追加 Stage 1-7 变更记录。

**内容大纲**：

```markdown
# 开发日志 — 域感智能

> 本文件记录重要变更时序。按时间倒序追加。

---

## 2026-07-05 — 架构改造：WS 实时图传 + QR 双图 + 删除 Electron

### 背景
用户审查 `doc/全系统改进方案.md` 后提出 6 项架构调整要求（详见 `.trae/documents/架构改造比对与剩余实施计划.md`），其中 2 项已对齐（删除无人机端 QR 识别、QR×RFID 异常判定），4 项需实施。

### 变更清单（Stages 1-7）

#### Stage 1：数据库与模型基础
- 新增文件：`station/warehouse-inspection-system/backend/src/db/migrations.py`
- 修改 `models/models.py`：
  - `VideoData` 加 `source` / `waypoint_markers` / `stream_session_id` / `frame_rate_actual` 4 字段
  - `ImageRecord` 加 `qr_cropped_path` / `annotated_path` 2 字段
- 修改 `db/database.py:init_db()` 末尾调用 `run_migrations(engine)`
- 迁移 SQL 用 PostgreSQL `ADD COLUMN IF NOT EXISTS`，幂等可重跑

#### Stage 2：QR 双图保存
- 新增文件：`image/annotator.py`（`draw_qr_bbox()` + `save_annotated()`）
- 修改 `image/qr_worker.py` 新增 `_save_qr_evidence_images()`，在 QR 命中时写双图路径
- 修改 `api/images.py:GET /{image_id}` 响应追加 `qr_cropped_path` / `annotated_path`

#### Stage 3：视频后处理抽取
- 新增文件：`services/video_postprocess.py` — 公共 `postprocess_video()` 函数（抽帧 + QR 识别 + InventoryItem + 交叉校验）
- 修改 `api/videos.py:_process_video_background` → 薄包装调用 `postprocess_video(source="upload")`
- 修改 `api/gateway.py:_process_video_in_background` → 薄包装调用 `postprocess_video(source="gateway")`
- 消除 videos.py 与 gateway.py 的重复 QR 处理代码

#### Stage 4：WS 视频流端点 + 聚合器（含原 Stage 5 航点标记）
- 新增文件：`services/video_stream_aggregator.py`
  - `DroneStreamSession` 类：帧缓冲 + 编码守护线程 + `waypoint_markers` 数组
  - `VideoStreamAggregator` 单例：`start_session` / `push_frame` / `mark_waypoint` / `close_session` / `shutdown_all` / `get_status`
  - 输出路径：`storage/videos/{task_code|no_task}/{drone_code}/ws_{session_id}.mp4`
  - 关闭会话时创建 VideoData（`source="ws_stream"`, `stream_session_id`, `waypoint_markers=JSON`）并异步触发 `postprocess_video`
- 新增文件：`api/ws_video.py`
  - 端点 `WS /ws/video/{drone_code}`
  - 双模消息：`await websocket.receive()` → bytes 推帧 / text 控制消息
  - 控制消息：`stream_start` / `waypoint_enter` / `waypoint_leave` / `stream_stop` / `heartbeat`
  - finally 块用 `await asyncio.to_thread(aggregator.close_session, session)` 避免阻塞事件循环
- 修改 `main.py`：注册 `ws_video.router`，lifespan shutdown 调用 `shutdown_all()`
- 修改 `api/ws.py:get_workers_status()` 新增 `video_stream` 状态字段

#### Stage 6：api-gateway WS 反向代理
- 修改 `app/api-gateway/main.py`：新增 `/ws/video/{drone_code}` WS 代理
- 与现有 `/ws/monitor` 代理的关键差异：用 `receive()` 而非 `receive_text()`，支持 binary + text 双模转发
- 上游 URL：`ws://warehouse:8001/ws/video/{drone_code}?task_code=...`

#### Stage 7：删除 Electron
- 删除目录：`app/desktop-app/`（整个目录）
- 修改 `Makefile`：移除 `.PHONY` 中 `desktop`、`install` 中 npm install 行、`desktop:` target
- 修改 `app/deploy-linux.sh`：移除 Node.js 依赖安装段、`make desktop` 快速启动命令
- 修改 `启动.bat`：移除菜单项 [5]/[b] / `:start_desktop` / `:init_desktop` / Electron 进程检测停止 / 重新编号菜单
- 修改 `doc/全系统改进方案.md`：12 处"桌面应用/Electron"引用替换为"浏览器/Web 管理界面"

### 关键设计决策
1. **视频不按航点切分**：单条 VideoData 对应一次完整 WS 流会话；到达航点时仅在 `waypoint_markers` JSON 数组中追加 `{waypoint_id, frame_index, timestamp, expected_sku, position}` 标记（用户 2026-07-05 澄清）
2. **WS 双模消息**：binary 承载 JPEG 帧（避免 Base64 膨胀 33%），text 承载 JSON 控制消息（便于调试）
3. **api-gateway WS 代理必须用 `receive()` 而非 `receive_text()`**：现有 `/ws/monitor` 不支持 binary 上行，新代理独立实现
4. **postprocess_video 公共管线**：3 条视频通道（upload/gateway/ws_stream）最终汇入同一后处理函数
5. **Electron 完全删除**：不留向后兼容
```

### 8.5 删除 `doc/全系统改进方案.md` 3.2.4 节

**目标范围**：lines 309-359（共 51 行）
- 标题 `#### 3.2.4 扫码数据接收`（line 309）
- 完整代码块（lines 311-359，含 `scan_router.py` 注释 + 3 个 endpoint 定义）

**保留**：line 308（前一节末尾空行）和 line 360（3.2.5 节前的空行）合并为单个空行

**操作**：使用 Edit 工具，将 lines 309-359 + 后续空行替换为单个空行，使 3.2.5 节紧跟 3.2.3 节。

**替代文档说明**：用户原注释"此处实现功能应当是，无人机视频流实时传回，但是到达航点时需要返回一个信号..."已在 Stage 8.2 创建的 `doc/无人机端开发规范.md` WS 协议章节中完整描述（`waypoint_enter` 控制消息）。删除 3.2.4 节不会丢失语义。

---

## 三、Assumptions & Decisions

1. **Stage 8.1 采取综合更新策略**：原计划仅列 2 处改动，实际需 11 处改动以保持文档内部一致性。决策依据：原计划写明"同步代码实际实现"，且最小改动会让文档自相矛盾。**不再询问用户**，按综合对齐方向执行。
2. **`doc/无人机端开发规范.md` 路径**：遵循原计划 `doc/无人机端开发规范.md`，不引入新的 `doc/drone/` 子目录约定（避免目录结构变更超出 Stage 8 范围）。
3. **`logs/devlog.md` 创建**：文件不存在但 `project_memory.md` 已声明该路径为标准位置，本次创建符合约定。
4. **Stage 8.4 一次性记录 Stage 1-7**：因 `devlog.md` 此前不存在，本次需一次性补记所有 7 个 Stage 的变更；后续变更再追加倒序。
5. **Stage 8.5 不补回替代说明**：3.2.4 节描述的"航点信号"语义已在 8.2 创建的 `无人机端开发规范.md` 中完整覆盖，3.2.4 节直接删除无需补"已迁移至 X 文档"占位说明。
6. **不动 `docker-compose.yml`**：原计划已明确无需改动（`./app:/app` 挂载仍需 `app/index.html` 等前端入口，仅 `app/desktop-app/` 子目录在 Stage 7 已删除）。

---

## 四、Verification Steps

### 4.1 Stage 8.1 验证
- Read `.trae/documents/架构改造方案-WS图传与QR双图.md`
- Grep `segment_index` 应无命中
- Grep `切分` 仅在"不切分"语境下出现
- Grep `waypoint_markers` 在字段表、迁移 SQL、第 四 章、第 9.2 节测试代码、第 10 节决策摘要、末尾差异说明章节均有命中

### 4.2 Stage 8.2 验证
- Read `doc/无人机端开发规范.md`
- 版本号 v3.0
- 含 WS 图传协议章节，覆盖 5 种控制消息类型
- 含"不再要求 QR 识别"声明

### 4.3 Stage 8.3 验证
- Read `project_memory.md`
- 含"WS 图传协议速查"小节
- 含"QR 双图保存路径约定"小节
- 含"VideoData.source 字段语义"小节

### 4.4 Stage 8.4 验证
- Read `logs/devlog.md`
- 顶部为"开发日志 — 域感智能"标题
- 含 2026-07-05 条目，覆盖 Stages 1-7 全部变更
- 含关键设计决策 5 条

### 4.5 Stage 8.5 验证
- Read `doc/全系统改进方案.md` lines 305-365
- 不应出现 `#### 3.2.4 扫码数据接收` 标题
- 不应出现 `scan_router.py` 或 `/api/scan/upload` 代码
- 3.2.5 节应紧跟 3.2.3 节
- Grep `scan_router` 在该文件应无命中

### 4.6 整体验证
- `app/desktop-app/` 目录仍不存在
- 3 个启动脚本（Makefile / deploy-linux.sh / 启动.bat）中 `desktop` / `electron` 关键字均无命中
- Stage 1-7 实施文件全部存在且未被本次 Stage 8 改动影响

---

## 五、实施顺序

按以下顺序执行，无依赖关系时可并行：

1. **8.5 删除 3.2.4 节**（最简单，独立）
2. **8.3 更新 project_memory.md**（独立）
3. **8.4 创建 logs/devlog.md**（独立）
4. **8.2 创建 doc/无人机端开发规范.md**（独立，但内容较大）
5. **8.1 综合更新架构改造方案文档**（最大改动，最后做以便参考前 4 项已确认的最终状态）

每完成一项立即用 TaskUpdate 标记完成。
