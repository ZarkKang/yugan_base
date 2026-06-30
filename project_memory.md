# 项目记忆 — 域感智能

## 核心约定
- 启动管理使用 `启动.sh`（统一脚本），`./启动.sh` 一键启动，`./启动.sh menu` 交互菜单。`引导.sh` 为兼容性包装器。
- 所有后台线程必须随 FastAPI `lifespan` shutdown 事件优雅退出（如 RFID 连续扫描、入库监听）。
- 禁止在路由中直接 `return` 错误 — 异常由全局 `exception_handler` 统一捕获。
- 日志统一使用 `logging.getLogger(__name__)`，禁止 `print()`。
- 新增 API 必须返回 `APIResponse(success=..., message=..., data=...)` 格式。

## 目录结构约定（2026-06-30 整理）
- **日志目录**: `logs/` — 统一存放日志文件
  - `logs/devlog.md` — 开发日志（重要变更时序记录）
  - `logs/review/` — 复盘报告目录（现状-期望分析报告）
  - `logs/runtime/` — 运行日志目录（服务运行时 *.log 文件，如 drone.log、warehouse.log）
- **文档目录**: `doc/` — 统一存放技术文档（不再使用 docs/）
  - `doc/drone/` — 无人机端文档（开发规范、payload 代码等）
  - `doc/specs/` — 规范文档
  - `doc/plans/` — 计划文档
  - `doc/progress/` — 开发进度文档
- **项目记忆**: `project_memory.md` — 根目录保留，存放核心约定和关键信息
- **注意**: 不要再创建 docs/ 目录，所有文档统一放入 doc/

## 关键表结构速查

### RFIDTag（EPC → 商品映射）
| 字段 | 说明 |
|------|------|
| `tag_id` | EPC 标签号（hex 大写，**入库查询键**） |
| `goods_name` | 商品名称（即 SKU 标识） |
| `shelf_id` | 关联货架 |

### Inventory（RFID 实时库存快照）
| 字段 | 说明 |
|------|------|
| `rfid_tag_id` | FK → rfid_tags.id, **unique** |
| `quantity` | 当前库存数量 |
| `last_read_at` | 最后 RFID 读取时间 |

### InboundRecord（入库流水）
| 字段 | 说明 |
|------|------|
| `epc` | RFID 读到的 EPC 号 |
| `status` | success / failed |
| `message` | 失败原因 |

## PRE 系列 RFID 模块协议速查

| 功能 | 命令码 | 说明 |
|------|--------|------|
| 单次盘存 | `0x04` | 返回 TYPE_INFO 通知帧 |
| 多次盘存 | `0x08` | loop=0 表示无限 |
| 停止盘存 | `0x09` | |
| 设置功率 | `0x0A` | power_dbm*100, 2B |
| 锁定/解锁 | `0x0E` | |
| 杀死标签 | `0x0F` | |
| 帧头 | `0xBB` | |
| 帧尾 | `0x7E` | |

EPC 解析公式：`pc_byte0 = params[1]`, `epc_len = ((pc_byte0 // 8) + 1) * 2 - 2`

帧格式：`BB + Type(1) + Cmd(1) + PL(2,big-endian) + Params(N) + CS(1,sum%256) + 7E`

## 已知陷阱
- Windows 编辑的 `.sh` 脚本在 WSL 运行前必须转 LF，否则 bash 解析 shebang 失败（报 `$'\r': command not found` 或 `required file not found`）。项目已统一转换，但新增/编辑 shell 脚本时需确保编辑器使用 LF 换行符。
- WSL 环境不支持 pyserial，需用 fd 直接打开 `/dev/ttyS*`，`select.select()` 做非阻塞读。
- 入库服务的 `_on_tag_detected` 回调在后台线程中执行，需自行创建 `SessionLocal()` 管理数据库会话，**不能使用 FastAPI 的 `get_db` 依赖注入**。
- Python 环境未安装或不在 PATH 时，`pytest` 无法直接从命令行运行。
- drone-db-prototype 所有路由强制 JWT 认证（`OAuth2PasswordBearer`），前端必须通过 `POST /api/auth/login` 获取 token 后存入 localStorage，否则所有请求返回 401。
- warehouse-inspection-system 路由不强制认证，但前端同样配了自动登录机制以保持一致。
- 默认管理员账号: `admin / admin123`（需确认 seed 数据已创建）。

## RFID 连接故障排查速查
1. `GET /api/v1/rfid/diagnose` — 诊断端点，检查 pyserial、串口列表、连接状态
2. CP2102 驱动下载: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers
3. PRE 模块默认波特率 115200，auto_detect 会依次尝试 [115200,9600,38400,19200,57600]
4. WSL 下串口路径 `/dev/ttyS<N>`，Windows 下为 `COM<N>`
5. 常见失败: 模块未通电 / CP2102 驱动未装 / COM 口被 Demo 软件占用
6. 部署脚本已自动处理：`deploy-linux.sh` 和 `引导.sh` 快速部署会自动 `sudo chmod 666` 并加入 `dialout` 组

## 入库流程
```
RFID 读标签 → EPC hex
  → `SELECT * FROM rfid_tags WHERE tag_id = epc`
  → 找到: UPSERT inventory (quantity += 1) + INSERT inbound_records (status=success)
  → 未找到: INSERT inbound_records (status=failed, message="未注册")
```

## 未来计划
- Alembic 数据库迁移（当前未集成，P3 优先级）
- Gateway 端到端测试
- 模拟器全流程测试