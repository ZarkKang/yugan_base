# 项目记忆 — 域感智能

## 核心约定
- 所有后台线程必须随 FastAPI `lifespan` shutdown 事件优雅退出（如 RFID 连续扫描、入库监听）。
- 禁止在路由中直接 `return` 错误 — 异常由全局 `exception_handler` 统一捕获。
- 日志统一使用 `logging.getLogger(__name__)`，禁止 `print()`。
- 新增 API 必须返回 `APIResponse(success=..., message=..., data=...)` 格式。

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
- WSL 环境不支持 pyserial，需用 fd 直接打开 `/dev/ttyS*`，`select.select()` 做非阻塞读。
- 入库服务的 `_on_tag_detected` 回调在后台线程中执行，需自行创建 `SessionLocal()` 管理数据库会话，**不能使用 FastAPI 的 `get_db` 依赖注入**。
- Python 环境未安装或不在 PATH 时，`pytest` 无法直接从命令行运行。

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