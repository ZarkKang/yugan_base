# 域感智能 开发日志

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