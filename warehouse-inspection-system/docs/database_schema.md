# 数据库表结构设计

## ER图

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│   Drone     │       │  InspectionRecord│       │   Shelf     │
├─────────────┤       ├──────────────────┤       ├─────────────┤
│ id (PK)     │◄──────│ drone_id (FK)    │       │ id (PK)     │
│ drone_code  │       │ id (PK)          │──────►│ shelf_code  │
│ drone_name  │       │ shelf_id (FK)    │       │ shelf_name  │
│ model       │       │ rfid_tag_id (FK) │       │ zone        │
│ status      │       │ record_code      │       │ position_x  │
│ battery     │       │ status           │       │ position_y  │
│ position    │       │ qr_code_data     │       │ position_z  │
└─────────────┘       │ rfid_data        │       │ qr_code     │
      │               │ image_path       │       └─────────────┘
      │               │ is_matched       │              │
      │               │ inspection_time  │              │
      │               └──────────────────┘              │
      │                        │                        │
      │                        │                        │
      ▼                        ▼                        ▼
┌─────────────┐       ┌──────────────────┐       ┌─────────────┐
│   Task      │       │    RFIDTag        │       │   Shelf     │
├─────────────┤       ├──────────────────┤       │  (关联)     │
│ id (PK)     │       │ id (PK)           │       ├─────────────┤
│ task_code   │       │ tag_id            │◄──────│ shelf_id    │
│ drone_id(FK)│──────►│ shelf_id (FK)     │       │ (FK)        │
│ status      │       │ goods_name        │       └─────────────┘
│ altitude    │       │ goods_quantity    │
└─────────────┘       └──────────────────┘
```

## 表详细说明

### 1. drones（无人机表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| drone_code | VARCHAR(50) | UNIQUE, NOT NULL | 无人机编号 |
| drone_name | VARCHAR(100) | | 无人机名称 |
| model | VARCHAR(100) | | 型号 |
| status | VARCHAR(20) | DEFAULT 'offline' | 状态: online/offline/maintenance |
| battery_level | FLOAT | DEFAULT 100.0 | 电池电量百分比 |
| last_position_x | FLOAT | | 最后位置X |
| last_position_y | FLOAT | | 最后位置Y |
| last_position_z | FLOAT | | 最后位置Z |
| last_seen | TIMESTAMP | | 最后在线时间 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

### 2. shelves（货架表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| shelf_code | VARCHAR(50) | UNIQUE, NOT NULL | 货架编号 |
| shelf_name | VARCHAR(100) | | 货架名称/位置描述 |
| zone | VARCHAR(50) | | 区域 |
| position_x | FLOAT | | 位置X坐标 |
| position_y | FLOAT | | 位置Y坐标 |
| position_z | FLOAT | | 位置Z坐标 |
| rows | INTEGER | DEFAULT 1 | 行数 |
| columns | INTEGER | DEFAULT 1 | 列数 |
| levels | INTEGER | DEFAULT 1 | 层数 |
| qr_code | VARCHAR(200) | | 关联二维码 |
| status | VARCHAR(20) | DEFAULT 'normal' | 状态: normal/damaged/maintenance |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

### 3. rfid_tags（RFID标签表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| tag_id | VARCHAR(100) | UNIQUE, NOT NULL | 标签UID |
| tag_type | VARCHAR(50) | | 标签类型 |
| shelf_id | INTEGER | FOREIGN KEY | 关联货架 |
| goods_name | VARCHAR(200) | | 货物名称 |
| goods_quantity | INTEGER | DEFAULT 0 | 货物数量 |
| last_read_time | TIMESTAMP | | 最后读取时间 |
| last_read_strength | INTEGER | | 最后读取信号强度 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

### 4. inspection_records（巡检记录表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| record_code | VARCHAR(50) | UNIQUE, NOT NULL | 记录编号 |
| drone_id | INTEGER | FOREIGN KEY, NOT NULL | 无人机ID |
| shelf_id | INTEGER | FOREIGN KEY | 货架ID |
| rfid_tag_id | INTEGER | FOREIGN KEY | RFID标签ID |
| status | ENUM | DEFAULT 'pending' | 巡检状态 |
| qr_code_data | VARCHAR(500) | | 二维码数据 |
| rfid_data | VARCHAR(500) | | RFID数据 |
| image_path | VARCHAR(500) | | 拍摄图片路径 |
| detected_qr_codes | TEXT | | 检测到的二维码JSON |
| detected_rfid_tags | TEXT | | 检测到的RFID标签JSON |
| drone_position_x | FLOAT | | 巡检时无人机位置X |
| drone_position_y | FLOAT | | 巡检时无人机位置Y |
| drone_position_z | FLOAT | | 巡检时无人机位置Z |
| is_matched | BOOLEAN | | 数据是否匹配 |
| mismatch_reason | TEXT | | 不匹配原因 |
| inspection_time | TIMESTAMP | | 巡检时间 |
| duration_ms | INTEGER | | 处理耗时(毫秒) |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |

### 5. tasks（巡检任务表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| task_code | VARCHAR(50) | UNIQUE, NOT NULL | 任务编号 |
| task_name | VARCHAR(200) | NOT NULL | 任务名称 |
| task_type | VARCHAR(50) | | 任务类型: routine/emergency/custom |
| status | ENUM | DEFAULT 'created' | 任务状态 |
| target_shelves | TEXT | | 目标货架列表JSON |
| flight_path | TEXT | | 飞行路径JSON |
| altitude | FLOAT | DEFAULT 5.0 | 飞行高度 |
| speed | FLOAT | DEFAULT 2.0 | 飞行速度 |
| drone_id | INTEGER | FOREIGN KEY | 分配的无人机 |
| start_time | TIMESTAMP | | 开始时间 |
| end_time | TIMESTAMP | | 结束时间 |
| total_records | INTEGER | DEFAULT 0 | 总记录数 |
| abnormal_records | INTEGER | DEFAULT 0 | 异常记录数 |
| created_by | VARCHAR(100) | | 创建人 |
| created_at | TIMESTAMP | DEFAULT NOW() | 创建时间 |
| updated_at | TIMESTAMP | DEFAULT NOW() | 更新时间 |

### 6. system_logs（系统日志表）

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | SERIAL | PRIMARY KEY | 主键 |
| level | VARCHAR(20) | NOT NULL | 日志级别 |
| source | VARCHAR(100) | | 日志来源模块 |
| message | TEXT | NOT NULL | 日志消息 |
| details | TEXT | | 详细信息JSON |
| created_at | TIMESTAMP | DEFAULT NOW(), INDEX | 创建时间 |

## 索引设计

```sql
-- 无人机编号唯一索引
CREATE UNIQUE INDEX idx_drones_code ON drones(drone_code);

-- 货架编号唯一索引
CREATE UNIQUE INDEX idx_shelves_code ON shelves(shelf_code);

-- RFID标签UID唯一索引
CREATE UNIQUE INDEX idx_rfid_tags_uid ON rfid_tags(tag_id);

-- 巡检记录编号唯一索引
CREATE UNIQUE INDEX idx_inspection_records_code ON inspection_records(record_code);

-- 巡检记录状态索引（用于状态筛选）
CREATE INDEX idx_inspection_records_status ON inspection_records(status);

-- 巡检记录创建时间索引（用于时间范围查询）
CREATE INDEX idx_inspection_records_created ON inspection_records(created_at);

-- 任务编号唯一索引
CREATE UNIQUE INDEX idx_tasks_code ON tasks(task_code);

-- 任务状态索引
CREATE INDEX idx_tasks_status ON tasks(status);

-- 系统日志时间索引
CREATE INDEX idx_system_logs_created ON system_logs(created_at);
```

## 初始化数据

```sql
-- 插入示例无人机
INSERT INTO drones (drone_code, drone_name, model, status) VALUES
('DRONE-001', '巡检无人机A', 'DJI-M300', 'online'),
('DRONE-002', '巡检无人机B', 'DJI-M300', 'offline');

-- 插入示例货架
INSERT INTO shelves (shelf_code, shelf_name, zone, position_x, position_y, qr_code) VALUES
('SHELF-A01', 'A区01号货架', 'A区', 10.5, 20.3, 'QR-A01-2024'),
('SHELF-A02', 'A区02号货架', 'A区', 15.5, 20.3, 'QR-A02-2024'),
('SHELF-B01', 'B区01号货架', 'B区', 10.5, 30.3, 'QR-B01-2024');

-- 插入示例RFID标签
INSERT INTO rfid_tags (tag_id, shelf_id, goods_name, goods_quantity) VALUES
('RFID-001', 1, '商品A-001', 100),
('RFID-002', 1, '商品A-002', 50),
('RFID-003', 2, '商品B-001', 200);
```
