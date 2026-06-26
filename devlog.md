# 域感智能 开发日志

## 2026-06-26 修复：基站兼容 uav_ground_bridge 纯上报型架构（RFID + 设备身份验证）
- **类型**：[修复] + [新增功能]
- **影响范围**：warehouse-inspection-system（gateway、drones、drone_integration、device_verification）
- **详细内容**：
  本批次修改针对无人机端 `uav_ground_bridge` 实际架构（**纯上报型 HTTP 客户端**，无服务端监听）做基站侧兼容，**无人机端代码零修改**。

  ### A. RFID 数据接收兼容 (gateway.py)
  1. **根因**：基站预期字符串列表 `["EPC1"]`，无人机端实际发送字典列表 `[{"epc","rssi_dbm","stamp"}]`，导致解析失败。
  2. **修复**：重写 `_handle_rfid_data` → 新增 `_parse_rfid_payload(payload)`，自动识别两种格式并统一为 `[{"epc","rssi_dbm","stamp"}]`。
  3. **EPC 校验**：新增 `EPC_PATTERN = ^[0-9A-F]{24}$`（ISO 18000-6C 标准），跳过非法 EPC（如 "INVALID"）但不拒绝整批。
  4. **RSSI 校验**：范围 `-120 ~ 0` dBm，超出范围记日志并置 None。
  5. **异步处理**：RFID 接收改为异步队列，立即返回 200，解决无人机端 1.5s 超时问题。
  6. **幂等性**：基于 `RFID_{drone_id}_{task_code}_{waypoint_id}_{stamp}` 生成 record_code 唯一约束，重复上传自动跳过。
  7. **新增 `/replay` 接口**：支持无人机端重放 `failed.jsonl` 中的失败记录（心跳 + RFID），幂等处理。

  ### B. 心跳接口增强 (drones.py)
  - 心跳返回附带基站状态信息（`server_time`、`drone_registered`、`base_status: online`），供无人机端被动获取。
  - **心跳到达自动维护 `DroneDevice` 记录**（调用 `upsert_device_from_heartbeat`），替代原 `/device/report` 上报接口，无人机端无需额外调用。

  ### C. 设备身份验证新增 heartbeat 模式 (device_verification.py + drone_integration.py)
  1. **根因**：原 `active` 模式反查无人机 `192.168.1.201:8080`，但无人机端无 HTTP 服务端，永远失败；`passive` 模式需无人机调用 `/device/report`，实际从未调用。
  2. **新增 `verify_device_by_heartbeat(drone_code)`**：通过 `drones.last_seen` 判断在线（阈值 30s），不反查任何端口。
  3. **新增 `upsert_device_from_heartbeat(db, drone)`**：心跳到达时自动创建/更新 `DroneDevice`（status=online, last_connected_at=now）。
  4. **`/device/verify` 路由重构**：默认 `mode` 从 `active` 改为 `heartbeat`，参数从 `ip` 改为 `drone_code`；保留 active/passive 向后兼容。
  5. **离线检测**：心跳超时时自动将 `DroneDevice.status` 标记为 `offline`。

- **相关文件**：
  - `warehouse-inspection-system/backend/src/api/gateway.py`（RFID 解析、校验、异步、幂等、/replay）
  - `warehouse-inspection-system/backend/src/api/drones.py`（心跳增强 + 自动维护 DroneDevice）
  - `warehouse-inspection-system/backend/src/api/drone_integration.py`（/device/verify 默认 heartbeat）
  - `warehouse-inspection-system/backend/src/services/device_verification.py`（新增 heartbeat 模式 + upsert 函数）
  - `scripts/test_heartbeat.json`、`scripts/test_rfid.json`、`scripts/verify_rfid.py`、`scripts/verify_device_table.py`（验证脚本）
- **验证结果**：
  - RFID: 字典格式支持✓ EPC校验(2/3合法)✓ 异步1.5s返回✓ 幂等(第二次跳过)✓
  - 设备验证: heartbeat模式 verified=true✓ DroneDevice自动online✓ active模式向后兼容(返回失败)✓
- **后续动作**：无人机端联调时仅需正常发送心跳即可通过设备身份验证，无需任何代码修改。

---

## 2026-06-21 新增：无人机端开发技术文档（供 Codex 开发使用）
- **类型**：[文档]
- **影响范围**：无人机端
- **详细内容**：
  - 创建 `doc/无人机端开发技术文档.md` (v1.0)，面向无人机端开发团队的完整实施指南，包含 10 大章节：
    1. 系统架构概述（飞控层+载荷层拓扑图、数据流全景）
    2. 软件开发环境配置指南（硬件平台、OS、ROS 工作空间、Python 依赖、网络配置、开发工具链）
    3. 硬件兼容性要求（UHF RFID PRE 协议 V2.2、摄像头、网络接口）
    4. API 接口规范（6 个端点完整定义 + 通用调用模板）
    5. 数据通信协议（HTTP+UDP 双链路、ROS 话题、RFID 标签格式、航点 YAML、失败日志 JSONL、视频推流协议）
    6. 核心功能模块实现说明（5 个模块的架构图 + 伪代码骨架：心跳、RFID 桥接、航点监控、视频推流、设备上报 + launch 文件结构）
    7. 安全认证机制（当前状态 + 3 阶段增强计划 + 无人机端安全编码规范）
    8. 错误处理流程（错误分类 + 网络/数据/系统错误处理流程 + 失败持久化 + 崩溃恢复）
    9. 性能优化建议（资源目标 + 连接复用、缓存优化、视频调优、日志轮转、线程安全 + 监控指标）
    10. 测试验收标准（10 项单元测试 + 5 项集成测试 + 7 项性能测试 + 完整验收清单）
  - 附录：完整启动命令、常用调试命令、文件索引、错误码速查
- **相关文件**：
  - `doc/无人机端开发技术文档.md`（新建，v1.0）
  - `devlog.md`（本次记录）
- **后续动作**：无人机端团队可直接以本文档为开发规格，使用 Codex 进行功能开发

---

## 2026-06-21 修复：设备验证方向 — 基站主动连接无人机 → 无人机主动上报
- **类型**：[修复] + [新增功能]
- **影响范围**：warehouse-inspection-system + 无人机端
- **详细内容**：
  1. **根因**：基站 `device_verification.py` 设计为主动向无人机 IP (192.168.1.201:8080) 发起 HTTP 请求验证设备身份，但无人机端仅运行 `uav_ground_bridge`（HTTP 客户端），无 HTTP 服务端监听，导致验证向导提示"设备可能不支持HTTP API"。
  2. **方案A（主）— 被动验证模式**：
     - 新增 `POST /drone-integration/device/report` 端点：无人机启动时主动上报设备型号、固件版本、ROS 版本、系统信息等。
     - `device_verification.py` 新增 `save_device_report()` 和 `_verify_device_passive()` 函数，支持存储和查询无人机上报的设备信息。
     - `verify_device_identity` API 新增 `mode` 参数（`active`/`passive`），默认仍为 active。
  3. **方案B（辅）— 无人机端 HTTP 服务端**：
     - `doc/drone_scripts/drone_http_server.py`：轻量 HTTP 服务端，监听 8080，响应 `/health`、`/api/device/info`、`/status` 等端点，为验证向导提供后向兼容。
     - `doc/drone_scripts/report_device_info.py`：设备信息自动采集 + 上报脚本，支持重试，可集成到 launch 文件。
  4. **文档更新**：`doc/无人机端开发规范.md` v1.1，新增 API-06 接口规范、验证模式对比表、脚本引用。
- **相关文件**：
  - `warehouse-inspection-system/backend/src/api/drone_integration.py`（新增 /device/report 端点 + mode 参数）
  - `warehouse-inspection-system/backend/src/services/device_verification.py`（新增 save_device_report + _verify_device_passive）
  - `doc/drone_scripts/report_device_info.py`（新建，无人机端设备上报脚本）
  - `doc/drone_scripts/drone_http_server.py`（新建，无人机端 HTTP 服务端）
  - `doc/无人机端开发规范.md`（v1.0 → v1.1）
- **后续动作**：无人机端集成 `report_device_info.py` 到 launch 启动流程；可选部署 `drone_http_server.py` 作为后台服务；前端验证向导需支持 passive 模式选项。

---

## 2026-06-21 优化：建立基站-无人机同步开发流程与接口规范文档
- **类型**：[优化] + [文档]
- **影响范围**：全局（Skill + 无人机端 + warehouse-inspection-system）
- **详细内容**：
  1. **创建 `doc/无人机端开发规范.md`**（v1.0）：结构化无人机端开发文档，涵盖系统架构、通信拓扑、5 个 API 接口规范（心跳/RFID/图像/二维码/视频推流）、全部数据格式定义（RFID/位置/电池/航点/失败日志）、功能需求矩阵（8 已完成 + 5 待开发 + 3 基站配合）、技术参数表、里程碑进度、测试标准（单元/集成/性能）、完整 Python ROS 代码示例。
  2. **修复 `schemas.py`**：`DataReceiveRequest` 新增 `metadata: Optional[dict]` 字段，支持无人机端上传 `task_code`、`waypoint_id`、`event`、`video_stream`、`battery` 等附加元数据。
  3. **更新 `SKILL.md`**：新增"基站-无人机同步开发流程"章节，包含接口契约原则、5 阶段同步开发要求表、文档版本控制机制（语义化版本 + 同步提交规则 + 冲突处理 + 定期审查）。
  4. **接口路径对齐**：明确无人机端 HTTP 路径统一使用 `/api/warehouse` 前缀（经 API 网关路由），修正了无人机端现有路径 `/api/v1/` 与基站实际路径不匹配的问题。
- **相关文件**：
  - `doc/无人机端开发规范.md`（新建，v1.0）
  - `warehouse-inspection-system/backend/src/schemas/schemas.py`（DataReceiveRequest 新增 metadata 字段）
  - `.trae/skills/yugan-intelligence/SKILL.md`（新增同步开发流程章节）
  - `devlog.md`（本次记录）
- **后续动作**：无人机端需按 `doc/无人机端开发规范.md` 修正 HTTP 路径前缀；基站 gateway 需实现 metadata 字段存储逻辑。

---

## 2026-06-21 新增：无人机系统整合 — 发现→验证→注册→传输→自动化→监控全流程
- **类型**：[新增功能]
- **影响范围**：warehouse-inspection-system
- **详细内容**：
  1. **网络工具模块** (`src/core/network.py`)：ping、端口扫描、子网扫描、连通性诊断，支持 Windows/Linux 双平台
  2. **设备发现服务** (`src/services/drone_discovery.py`)：扫描 192.168.1.x 网段，识别无人机图传设备(192.168.1.201)和基站(192.168.1.200)，结果存入 `network_scan_results` 表
  3. **设备身份验证** (`src/services/device_verification.py`)：HTTP 请求设备 API 获取型号/固件/协议信息，匹配已知兼容设备列表 (DJI/Walksnail/HDZero/SIYI 等)，检查协议兼容性
  4. **系统整合服务** (`src/services/drone_integration.py`)：设备注册、通信参数配置(协议/端口/认证/加密)、连接测试、数据传仕测试(视频+RFID JSON)
  5. **自动化任务调度** (`src/services/automated_task.py`)：定时任务调度器(interval/cron/once)，支持视频采集+RFID读取+JSON文件自动回传至基站(192.168.1.200)
  6. **API路由** (`src/api/drone_integration.py`)：完整的 REST API 覆盖7个步骤，共 15 个端点
  7. **数据库新增 4 张表**：`drone_devices`(设备配置)、`communication_logs`(通信日志)、`automated_tasks`(自动化任务)、`network_scan_results`(扫描结果)
  8. **生命周期集成**：调度器随 FastAPI lifespan 自动启停
- **相关文件**：
  - `src/core/network.py`（新建，网络工具）
  - `src/services/drone_discovery.py`（新建，设备发现）
  - `src/services/device_verification.py`（新建，身份验证）
  - `src/services/drone_integration.py`（新建，整合服务）
  - `src/services/automated_task.py`（新建，任务调度）
  - `src/api/drone_integration.py`（新建，API路由）
  - `src/models/models.py`（新增 4 张表）
  - `src/schemas/schemas.py`（新增 4 个 Schema）
  - `src/main.py`（注册路由 + 调度器启停）
  - `requirements.txt`（添加 apscheduler）
- **后续动作**：在 WSL 中重启服务验证 API 可用性；真机测试需无人机图传设备接入 192.168.1.x 网段

---

## 2026-06-21 修复：无人机系统 admin 登录失败（passlib + bcrypt 5.x 不兼容）
- **类型**：[修复]
- **影响范围**：drone-db-prototype（无人机数据系统）
- **详细内容**：
  1. **根因**：`passlib[bcrypt]==1.7.4` 与 bcrypt 5.0.0 不兼容 — passlib 内部的 `detect_wrap_bug` 函数使用 255 字节测试密钥，bcrypt 5.x 拒绝处理超过 72 字节的密码，抛出 `ValueError: password cannot be longer than 72 bytes`，导致 `CryptContext` 初始化失败，登录接口无法验证密码。
  2. **修复**：移除 `passlib` 依赖，改用 `bcrypt` 直接调用（`bcrypt.checkpw` / `bcrypt.hashpw`）。`security.py` 中删除 `CryptContext`，`requirements.txt` 中 `passlib[bcrypt]==1.7.4` → `bcrypt>=4.0,<5.0`。
  3. **验证**：admin/admin123 登录返回 200 + JWT token，错误密码返回 401。
- **相关文件**：
  - `drone-db-prototype/backend/app/core/security.py`（passlib → bcrypt 直接调用）
  - `drone-db-prototype/backend/requirements.txt`（passlib[bcrypt] → bcrypt）
- **后续动作**：生产环境更换 `SECRET_KEY`，启用 HTTPS。

---

## 2026-06-21 修复：前端导航栏 HTML 结构错误导致显示异常
- **类型**：[修复]
- **影响范围**：warehouse-inspection-system 前端
- **详细内容**：
  1. **根因**：提交 `a341454`（feat: 前端新增入库管理页面）在合并时产生 HTML 结构错误 — `index.html` 第 309 行多了一个 `</div>`，导致 `<nav class="sidebar-nav">` 在入库管理 nav-item 之后被提前关闭。
  2. **影响**：货架管理、SKU 管理、图像管理、视频管理、数据网关、系统状态、RFID 设置等 7 个导航项被渲染在 `<nav>` 容器之外，CSS 选择器 `.sidebar-nav .nav-item` 样式失效，造成导航栏显示错乱。
  3. **修复**：删除多余的 `</div>`，恢复 nav 标签的正确嵌套结构。
  4. **验证**：HTML 标签验证通过（nav 1:1，div 343:343 平衡），所有 nav-item 均在 `<nav>` 内，后端服务正常。
- **相关文件**：`warehouse-inspection-system/frontend/index.html`（第 309 行）
- **后续动作**：前端可正常打开使用 `file:///.../index.html`，所有导航项点击和页面切换正常。

---

## 2026-06-21 修复：启动.sh abs_path 函数 bug 导致 venv 路径错误
- **类型**：[修复]
- **影响范围**：启动.sh
- **详细内容**：
  1. `abs_path()` 中 `local rel="$1" full="$SCRIPT_DIR/$rel"` 的单行声明存在 bug，`$rel` 在 `full` 赋值时未展开，导致所有路径都返回 `$SCRIPT_DIR/` 而非 `$SCRIPT_DIR/子目录`。
  2. 修复为两行独立声明：`local rel="$1"` + `local full="$SCRIPT_DIR/$rel"`。
  3. 清理了 bug 产生的根目录 `venv` 残留。
- **相关文件**：`启动.sh`
- **验证**：三个服务（8000/8001/8080）均启动成功，状态全部正常。

---

## 2026-06-21 重构：引导脚本与启动脚本合并为统一启动管理脚本
- **类型**：[重构] + [架构变更]
- **影响范围**：全局（部署脚本、引导菜单、启动脚本）
- **详细内容**：
  1. **合并**：将 `引导.sh`（1024 行，交互菜单）和 `启动.sh`（569 行，服务管理）合并为单一 `启动.sh`（1584 行），消除全部重复代码（颜色输出、SCRIPT_DIR、MODE 管理、RFID 检测等）。
  2. **端口统一管理**：新增 `release_port()` / `get_port_pid()` / `release_all_ports()` 函数，启动前自动检测并释放占用端口，彻底解决两脚本独立运行时的端口抢占冲突。
  3. **阶段化启动流程**：`start_all()` 分为 5 个明确阶段（前置检查 → 基础设施 → RFID 检测 → 后端服务 → 状态汇总），每阶段独立日志输出。
  4. **双入口设计**：`./启动.sh`（无参数）→ 一键启动；`./启动.sh menu` → 交互式引导菜单；`./启动.sh start|stop|status|restart|logs|daemon|help` → CLI 命令。
  5. **兼容性**：`引导.sh` 改为 7 行兼容性包装器（`exec bash 启动.sh menu`），保留原有调用方式。
  6. **附带修复**：`deploy-linux.sh` 修复 HTML 实体编码错误（`&amp;&gt;` → `&>`，`&amp;&amp;` → `&&`）。
- **相关文件**：
  - `启动.sh`（完全重写，合并两个脚本的全部功能）
  - `引导.sh`（简化为兼容性包装器）
  - `deploy-linux.sh`（修复 HTML 实体编码）
- **后续动作**：验证 `./启动.sh` 一键启动和 `./启动.sh menu` 菜单功能正常。

---

## 2026-06-21 修复：仓库巡检系统 inbound.py 数据库导入路径错误
- **类型**：[修复]
- **影响范围**：warehouse-inspection-system
- **详细内容**：
  1. 一键启动时仓库巡检系统（端口 8001）启动失败，日志报 `ModuleNotFoundError: No module named 'src.core.database'`。
  2. 根因：`src/api/inbound.py` 中错误地从 `..core.database` 导入 `get_db`，而项目实际数据库模块位于 `src/db/database.py`（其他路由均使用 `..db.database`）。
  3. 修复：将 `from ..core.database import get_db` 改为 `from ..db.database import get_db`。
  4. 验证：修复后仓库巡检系统 `/health` 返回正常，数据库与 Redis 连接正常；同时手动启动了无人机数据系统（8000）和 API 网关（8080），三者均运行正常。
- **相关文件**：`warehouse-inspection-system/backend/src/api/inbound.py`
- **后续动作**：启动脚本 `./启动.sh start` 已可正常启动全部服务；建议后续提交本次修复。

---

## 2026-06-21 修复：WSL 下所有 shell 脚本换行符转换为 LF
- **类型**：[修复] + [配置]
- **影响范围**：全局（部署脚本、引导菜单、启动脚本）
- **详细内容**：
  1. 项目所有 `.sh` 脚本（`引导.sh`、`启动.sh`、`deploy-linux.sh` 等）在 Windows 编辑保存后使用了 CRLF 换行符，导致 WSL bash 无法正确解析 shebang，报 `required file not found` 或 `$'\r': command not found`。
  2. 使用 `find` + `sed -i 's/\r$//'` 将所有 `.sh` 文件统一转换为 LF 换行符。
  3. 修复后 `./引导.sh` 服务管理菜单可正常调用 `启动.sh`。
- **相关文件**：项目根目录及子目录下所有 `*.sh` 脚本
- **后续动作**：后续编辑 shell 脚本时确保使用 LF 换行符；建议配置编辑器/IDE 默认对 `.sh` 文件使用 LF。

---

## 2026-06-15 P0: Gateway 端到端测试 + 模拟器全流程测试 + EPC 种子数据
- **类型**：[测试] + [数据填充]
- **影响范围**：warehouse-inspection-system
- **详细内容**：
  1. **Gateway 端到端测试**（`tests/test_gateway.py`）：14 个测试用例，覆盖全部 3 个端点（`POST /gateway/receive`、`POST /gateway/qrcode/process`、`POST /gateway/rfid/read`）。测试范围含 RFID/QR/SBUS/视频/图像五种数据类型接收、无人机不存在 404、无效数据类型 400、单标签处理、InspectionRecord 字段正确性验证、后台处理器启动、二维码识别无输入/文件不存在场景、RFID 读卡器未连接/无标签/有标签场景。使用 SQLite 内存数据库 + FastAPI TestClient + mock RFID 驱动。
  2. **模拟器全流程测试**（`tests/test_simulator.py`）：9 个测试用例，模拟无人机端 8 步完整巡检流程（健康检查→心跳→获取任务→接收任务→获取航点→上传图像→完成任务→查看详情→全流程端到端）。使用 SQLite 内存数据库，自动创建测试无人机、任务、航点。
  3. **EPC→商品映射种子数据**（`tools/seed_rfid_tags.py`）：30 条预置 EPC→商品映射，覆盖 5 个大类（电子产品/日用品/食品饮料/办公用品/服装），自动创建关联货架。支持 `--seed`（默认填充）、`--export`（导出 JSON）、`--import-file`（从 JSON 导入）三种模式。
- **相关文件**：
  - `warehouse-inspection-system/backend/tests/test_gateway.py`（新增，14 个用例）
  - `warehouse-inspection-system/backend/tests/test_simulator.py`（新增，9 个用例）
  - `warehouse-inspection-system/backend/tools/seed_rfid_tags.py`（新增，30 条映射）
- **后续动作**：部署到 VM 运行 pytest 验证；RFID 串口硬件验证仍需真机；RuntimeWarning 等已知日志正常。

---

## 2026-06-15 P3 - 数据库统一：两个系统共用 PostgreSQL
- **类型**：[架构变更] + [配置]
- **影响范围**：全局（drone-db-prototype + warehouse-inspection-system）
- **详细内容**：
  1. **drone-db-prototype 从 SQLite 迁移到 PostgreSQL**：配置文件 `config.py` 改为自动生成 PostgreSQL 连接串，`database.py` 添加连接池配置；移除 SQLite 专属的 `check_same_thread` 参数。
  2. **Drone 表字段合并**：仓库巡检系统的 `drones` 表新增 `manufacturer`、`latitude/longitude/altitude`（GPS坐标）、`max_speed/max_altitude/flight_duration`（飞行参数）、`sku_id`（FK→skus）、`owner_id`（FK→users）、`description`、`is_active` 等字段，保留 `battery_level`、`last_position_x/y/z`、`last_seen` 等仓库巡检字段。两个系统共用同一张 `drones` 表。
  3. **新增共享表**：仓库巡检系统新增 `skus`、`video_data`、`image_data`、`rfid_data` 四张表（从无人机数据系统迁入），实现 SKU 管理、视频/图片/RFID 读取数据统一存储。
  4. **User 表对齐**：统一 `users` 表字段（`username`、`email`（可选）、`hashed_password`、`full_name`、`role`（String）、`is_active`），添加 `drones` 反向关系。
  5. **Enum→String 迁移**：无人机数据系统移除 `DroneStatus` 和 `UserRole` 枚举类，状态和角色改用纯字符串存储，与仓库巡检系统保持一致。同步更新 `permissions.py`、`schemas/`、`routers/` 中所有引用。
  6. **启动顺序调整**：`启动.sh` 改为先启动仓库巡检系统（8001，Schema 持有者），再启动无人机数据系统（8000）。守护进程也同步调整。
  7. **引导脚本更新**：`引导.sh` 的 `db_list_tables()` 移除 SQLite 引用，`init_database()` 和 `reset_database()` 使用 `postgres` 用户，标注两个系统共用 `warehouse_inspection` 数据库。
- **相关文件**：
  - `warehouse-inspection-system/backend/src/models/models.py`（Drone 合并 + 新增 SKU/VideoData/ImageData/RFIDData）
  - `drone-db-prototype/backend/app/core/config.py`（SQLite→PostgreSQL）
  - `drone-db-prototype/backend/app/core/database.py`（连接池配置）
  - `drone-db-prototype/backend/app/models/drone.py`（对齐字段 + Enum→String）
  - `drone-db-prototype/backend/app/models/user.py`（对齐字段 + Enum→String）
  - `drone-db-prototype/backend/app/models/__init__.py`（移除枚举导出）
  - `drone-db-prototype/backend/app/core/permissions.py`（UserRole→字符串常量）
  - `drone-db-prototype/backend/app/schemas/drone.py`（DroneStatus→str）
  - `drone-db-prototype/backend/app/schemas/user.py`（UserRole→str）
  - `drone-db-prototype/backend/app/routers/drones.py`（移除枚举引用）
  - `drone-db-prototype/backend/app/main.py`（create_all 安全化）
  - `drone-db-prototype/backend/.env.example`（PostgreSQL 连接串）
  - `drone-db-prototype/backend/.env.example.linux`（PostgreSQL 连接串）
  - `启动.sh`（启动顺序调整）
  - `引导.sh`（移除 SQLite 引用 + 数据库初始化对齐）
- **后续动作**：部署到 VM 验证数据库表创建和两个系统数据一致性；清理旧 SQLite 文件 `yugan.db`。

---

## 2026-06-14 部署脚本增强：RFID 串口权限自动配置 + 全系统启动验证
- **类型**：[新增功能] + [修复] + [配置]
- **影响范围**：全局（部署脚本 + 引导菜单 + 启动脚本）
- **详细内容**：
  1. **全系统启动验证**：成功启动所有4个子系统（drone:8000 / warehouse:8001 / gateway:8080 / desktop-app），验证健康检查、数据库连接、API 连通性均正常。
  2. **RFID 连接诊断**：`GET /api/v1/rfid/diagnose` 确认 pyserial 可用、`/dev/ttyUSB0` 存在但权限不足（用户不在 dialout 组），连接失败根因定位为串口权限问题。
  3. **启动.sh 增强**：`check_rfid_permissions` 新增 `auto_fix` 参数，静默模式下自动尝试 `sudo chmod 666` 和 `sudo usermod -aG dialout/docker`，无需交互即可修复权限。
  4. **deploy-linux.sh 增强**：部署流程新增 RFID 串口权限配置步骤，自动检测 `/dev/ttyUSB*` / `/dev/ttyACM*`，修复设备权限 + 加入 dialout 组 + 加入 docker 组。
  5. **引导.sh 增强**：新增 `setup_rfid_permissions()` 函数；集成到快速部署流程；环境部署子菜单新增独立选项「配置RFID串口权限」。
  6. **Git 提交**：本地提交 `4e8465f` feat(global): 部署脚本新增 RFID 串口权限自动配置，推送因 GitHub 连接受阻。
- **相关文件**：
  - `启动.sh`（check_rfid_permissions 改造）
  - `deploy-linux.sh`（新增 RFID 权限配置段落）
  - `引导.sh`（新增 setup_rfid_permissions 函数 + 菜单项）
  - `warehouse-inspection-system/.env`（新建，数据库连接配置）
- **后续动作**：真机 RFID 串口通信验证；`RFIDTag` 表填充 EPC→商品映射数据；GitHub 推送待网络恢复后执行。

---

## 2026-06-13 修复：完善注册系统 + ensure-admin 兜底机制
- **类型**：[修复] + [新增功能]
- **影响范围**：全局（drone-db-prototype + warehouse-inspection-system）
- **详细内容**：
  1. drone-db-prototype `init_data.py` 重构：`ensure_admin()` 函数每次启动都验证 admin 密码兼容性，bcrypt版本变更导致的hash不兼容自动修复。
  2. warehouse-inspection-system `seed.py` 重构：admin 密码验证 try/except 容错，验证异常时自动重置。
  3. 两个后端均新增 `POST /api/auth/ensure-admin` 端点：创建/修复 admin 用户并重置为 `admin123`，前端登录最后兜底。
  4. 两套前端登录流程增强为 5 步：localStorage恢复 → auto-login → auto-register → ensure-admin → 显示登录页。
- **相关文件**：
  - `drone-db-prototype/backend/app/init_data.py`（重写 ensure_admin）
  - `drone-db-prototype/backend/app/routers/auth.py`（新增 /ensure-admin）
  - `drone-db-prototype/frontend/src/index.html`（5步登录流程）
  - `warehouse-inspection-system/backend/src/db/seed.py`（增强容错）
  - `warehouse-inspection-system/backend/src/api/auth.py`（新增 /ensure-admin）
  - `warehouse-inspection-system/frontend/index.html`（5步登录流程）
  - `devlog.md`
- **后续动作**：重启服务验证登录流程。

## 2026-06-13 修复：数据库登录系统自动登录 + 注册兜底
- **类型**：[修复]
- **影响范围**：全局（drone-db-prototype + warehouse-inspection-system）
- **详细内容**：
  1. drone-db-prototype 添加 `startup` 事件确保 `init_default_data()` 在应用启动时执行，防止模块级执行时静默失败。
  2. 两套前端 auto-login 增强：登录失败 → 自动注册 admin/admin123 → 重试登录 → 最终失败则显示登录页。
  3. warehouse-inspection-system `POST /auth/register` 端点添加 `Form()` 注解，支持 `application/x-www-form-urlencoded` 格式。
- **相关文件**：
  - `drone-db-prototype/backend/app/main.py`（添加 startup 事件）
  - `drone-db-prototype/frontend/src/index.html`（增强 auto-login）
  - `warehouse-inspection-system/frontend/index.html`（增强 auto-login）
  - `warehouse-inspection-system/backend/src/api/auth.py`（register 添加 Form 注解）
- **后续动作**：重启服务后验证自动登录是否成功。

## 2026-06-13 修复：前端认证 + RFID诊断工具
- **类型**：[修复] + [新增功能]
- **影响范围**：全局（drone-db-prototype + warehouse-inspection-system + RFID）
- **详细内容**：
  1. 修复 drone-db-prototype 前端 `TOKEN='dev-bypass'` 导致所有 API 请求无 Authorization 头的问题（401 → "请求未授权"）。改为 init 时自动用默认账号 admin/admin123 登录获取 JWT token，存入 localStorage，后续请求自动附加 Bearer token。
  2. 修复 warehouse-inspection-system 前端同样问题，同步改为自动登录机制。
  3. 新增 `GET /api/v1/rfid/diagnose` 诊断端点：检测 pyserial 安装状态、串口列表、RFID 连接状态、平台特定提示（CP2102 驱动链接、Linux 权限提示）。
- **相关文件**：
  - `drone-db-prototype/frontend/src/index.html`（修改）
  - `warehouse-inspection-system/frontend/index.html`（修改）
  - `warehouse-inspection-system/backend/src/api/rfid.py`（新增 diagnose 端点）
- **后续动作**：需验证默认账号 admin/admin123 是否已在 seed 数据中创建；运行 RFID 诊断端点确认硬件状态。

## 2026-06-13 RFID驱动重构 + 自动入库功能
- **类型**：[新增功能] + [重构]
- **影响范围**：仓库巡检系统
- **详细内容**：
  1. **重写 `rfid_reader.py`**：命令码全部对齐 PRE 系列 UHF 模块 C# SDK V2.2（`RFID_Reader_Cmds.xml`），修复了旧版命令码全错（`0x22→0x04` 等）的问题；EPC 解析从固定 12 字节改为按 PC 字段动态计算 `((PC/8)+1)*2` 字节；补充了 `lock_tag`、`kill_tag`、`set_query_params`、`set_select_params`、`set_fhss`、`set_cw`、`modem_params`、`nv_config`、`io_control` 等 20+ 个命令方法。
  2. **新增 `Inventory` 表**：RFID 实时库存快照，按 `rfid_tag_id` 唯一索引，纪录 `quantity` + `last_read_at`。
  3. **新增 `InboundRecord` 表**：入库流水，包含 `epc`、`goods_name`、`rssi`、`status`、`message`。
  4. **新建 `services/inbound_service.py`**：`InboundService` 单例，start/stop/status 接口；后台通过 `rfid_reader.on_tag_detected` 回调驱动，EPC→`RFIDTag.tag_id` 查询 → 事务更新 `Inventory` + 写入 `InboundRecord`。
  5. **新建 `api/inbound.py`**：`POST /inbound/start`、`POST /inbound/stop`、`GET /inbound/status`；统一使用 `APIResponse`。
  6. **更新 `api/rfid.py`**：新增 `/rfid/lock`、`/rfid/kill`、`/rfid/power`(GET+POST)、`/rfid/query`、`/rfid/region` 端点。
  7. **更新 `main.py`**：注册 `inbound` 路由；在 `lifespan` shutdown 阶段调用 `InboundService.stop()` 优雅退出。
  8. **新增 `tests/test_inbound_service.py`**：10 个 pytest 用例，覆盖 start/stop 生命周期、EPC 注册/未注册、异常回滚、停止时忽略标签。
  9. **添加 `pytest` + `pytest-asyncio` 到 `requirements.txt`**。
- **相关文件**：
  - `hardware/rfid_reader.py`（完全重写）
  - `models/models.py`（新增 2 表）
  - `services/inbound_service.py`（新建）
  - `api/inbound.py`（新建）
  - `api/rfid.py`（新增 6 个端点）
  - `main.py`（注册路由 + shutdown hook）
  - `tests/test_inbound_service.py`（新建）
  - `requirements.txt`（添加 pytest）
- **后续动作**：
  - 需真机测试 PRE RFID 模块串口通信
  - `RFIDTag` 表需预填充 EPC→商品映射数据
  - 前端需接收入库状态和流水数据
  - 建议执行 `pip install -r requirements.txt` 更新依赖

---

## 2026-06-12 基础设施完善
- **类型**：[新增功能] + [配置]
- **影响范围**：仓库巡检系统
- **详细内容**：
  1. 完成数据接收网关 `gateway.py`（双 Worker 异步队列处理 QR + RFID 数据）
  2. 完善 `rfid_reader.py`：E720 协议帧解析，串口自动探测（含 WSL fd 回退），全局单例，连续扫描线程
  3. 新增 `seeds.py`：默认数据填充（无人机、货架、RFID 标签、用户）
- **相关文件**：`api/gateway.py`、`hardware/rfid_reader.py`（旧版）、`db/seed.py`
- **后续动作**：RFID 串口真机验证

---

## 2026-06-11 引导菜单 + 项目选择页
- **类型**：[新增功能]
- **影响范围**：全局（前端 + API 网关）
- **详细内容**：新增系统选择页 `index.html`，仓库巡检系统路由统一添加 `/select` 端点
- **相关文件**：`index.html`（根目录）、`main.py`（`/select` 端点）
- **后续动作**：对接桌面应用 `desktop-app` 的 `contextBridge` API

---

## 2026-06-10 项目初始化
- **类型**：[配置]
- **影响范围**：全局
- **详细内容**：创建项目骨架，三套 Docker Compose，Makefile，Linux 部署脚本
- **相关文件**：`docker-compose.yml`、`Makefile`、`deploy-linux.sh`、`.mode.conf`
- **后续动作**：补充各子系统业务代码