# 域感智能 开发日志

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