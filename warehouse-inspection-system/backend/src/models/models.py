"""
数据模型 - 数据库表结构定义
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base
import enum
import os
from datetime import datetime


class InspectionStatus(str, enum.Enum):
    """巡检状态枚举"""
    PENDING = "pending"           # 待巡检
    IN_PROGRESS = "in_progress"   # 巡检中
    COMPLETED = "completed"       # 已完成
    ABNORMAL = "abnormal"         # 异常


class TaskStatus(str, enum.Enum):
    """任务状态枚举"""
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class ImageStatus(str, enum.Enum):
    """图像识别状态枚举"""
    PENDING = "pending"          # 待识别
    PROCESSING = "processing"    # 识别中
    PROCESSED = "processed"      # 已识别
    FAILED = "failed"            # 识别失败


class InventoryStatus(str, enum.Enum):
    """库存状态枚举"""
    NORMAL = "normal"            # 正常
    MISPLACED = "misplaced"      # 错位
    MISSING = "missing"          # 缺货
    EXTRA = "extra"              # 多货
    DUPLICATE = "duplicate"      # 重复码


def _gen_id(prefix: str) -> str:
    """生成唯一ID"""
    return f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}_{os.urandom(3).hex()}"


class Drone(Base):
    """无人机表"""
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    drone_code = Column(String(50), unique=True, index=True, nullable=False, comment="无人机编号")
    drone_name = Column(String(100), comment="无人机名称")
    model = Column(String(100), comment="型号")
    status = Column(String(20), default="offline", comment="状态: online/offline/maintenance")
    battery_level = Column(Float, default=100.0, comment="电池电量百分比")
    last_position_x = Column(Float, nullable=True, comment="最后位置X")
    last_position_y = Column(Float, nullable=True, comment="最后位置Y")
    last_position_z = Column(Float, nullable=True, comment="最后位置Z")
    last_seen = Column(DateTime, nullable=True, comment="最后在线时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    inspection_records = relationship("InspectionRecord", back_populates="drone")
    tasks = relationship("Task", back_populates="drone")


class Shelf(Base):
    """货架表"""
    __tablename__ = "shelves"

    id = Column(Integer, primary_key=True, index=True)
    shelf_code = Column(String(50), unique=True, index=True, nullable=False, comment="货架编号")
    shelf_name = Column(String(100), comment="货架名称/位置描述")
    zone = Column(String(50), comment="区域")
    position_x = Column(Float, comment="位置X坐标")
    position_y = Column(Float, comment="位置Y坐标")
    position_z = Column(Float, comment="位置Z坐标")
    rows = Column(Integer, default=1, comment="行数")
    columns = Column(Integer, default=1, comment="列数")
    levels = Column(Integer, default=1, comment="层数")
    qr_code = Column(String(200), nullable=True, comment="关联二维码")
    status = Column(String(20), default="normal", comment="状态: normal/damaged/maintenance")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    inspection_records = relationship("InspectionRecord", back_populates="shelf")
    rfid_tags = relationship("RFIDTag", back_populates="shelf")


class RFIDTag(Base):
    """RFID标签表"""
    __tablename__ = "rfid_tags"

    id = Column(Integer, primary_key=True, index=True)
    tag_id = Column(String(100), unique=True, index=True, nullable=False, comment="标签UID")
    tag_type = Column(String(50), comment="标签类型")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="关联货架")
    goods_name = Column(String(200), nullable=True, comment="货物名称")
    goods_quantity = Column(Integer, default=0, comment="货物数量")
    last_read_time = Column(DateTime, nullable=True, comment="最后读取时间")
    last_read_strength = Column(Integer, nullable=True, comment="最后读取信号强度")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    shelf = relationship("Shelf", back_populates="rfid_tags")
    inspection_records = relationship("InspectionRecord", back_populates="rfid_tag")


class InspectionRecord(Base):
    """巡检记录表"""
    __tablename__ = "inspection_records"

    id = Column(Integer, primary_key=True, index=True)
    record_code = Column(String(50), unique=True, index=True, nullable=False, comment="记录编号")
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=False, comment="无人机ID")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="货架ID")
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), nullable=True, comment="RFID标签ID")

    # 巡检数据
    status = Column(SQLEnum(InspectionStatus), default=InspectionStatus.PENDING, comment="巡检状态")
    qr_code_data = Column(String(500), nullable=True, comment="二维码数据")
    rfid_data = Column(String(500), nullable=True, comment="RFID数据")
    image_path = Column(String(500), nullable=True, comment="拍摄图片路径")
    detected_qr_codes = Column(Text, nullable=True, comment="检测到的二维码JSON")
    detected_rfid_tags = Column(Text, nullable=True, comment="检测到的RFID标签JSON")

    # 位置数据
    drone_position_x = Column(Float, nullable=True)
    drone_position_y = Column(Float, nullable=True)
    drone_position_z = Column(Float, nullable=True)

    # 比对结果
    is_matched = Column(Boolean, nullable=True, comment="数据是否匹配")
    mismatch_reason = Column(Text, nullable=True, comment="不匹配原因")

    # 元数据
    inspection_time = Column(DateTime, nullable=True, comment="巡检时间")
    duration_ms = Column(Integer, nullable=True, comment="处理耗时(毫秒)")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="inspection_records")
    shelf = relationship("Shelf", back_populates="inspection_records")
    rfid_tag = relationship("RFIDTag", back_populates="inspection_records")


class Task(Base):
    """巡检任务表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_code = Column(String(50), unique=True, index=True, nullable=False, comment="任务编号")
    task_name = Column(String(200), nullable=False, comment="任务名称")
    task_type = Column(String(50), comment="任务类型: routine/emergency/custom")
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.CREATED, comment="任务状态")

    # 任务配置
    target_shelves = Column(Text, nullable=True, comment="目标货架列表JSON")
    flight_path = Column(Text, nullable=True, comment="飞行路径JSON")
    altitude = Column(Float, default=5.0, comment="飞行高度")
    speed = Column(Float, default=2.0, comment="飞行速度")

    # 分配信息
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True, comment="分配的无人机")

    # 执行结果
    start_time = Column(DateTime, nullable=True, comment="开始时间")
    end_time = Column(DateTime, nullable=True, comment="结束时间")
    total_records = Column(Integer, default=0, comment="总记录数")
    abnormal_records = Column(Integer, default=0, comment="异常记录数")

    # 关联画像
    total_images = Column(Integer, default=0, comment="图像总数")
    total_recognized = Column(Integer, default=0, comment="已识别数")
    total_failed = Column(Integer, default=0, comment="识别失败数")
    pending_count = Column(Integer, default=0, comment="待识别数")
    scanned_waypoints = Column(Integer, default=0, comment="已扫描航点")

    # 元数据
    created_by = Column(String(100), nullable=True, comment="创建人")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drone = relationship("Drone", back_populates="tasks")
    waypoints = relationship("Waypoint", back_populates="task", cascade="all, delete-orphan")
    image_records = relationship("ImageRecord", back_populates="task", cascade="all, delete-orphan")


# ========== 航点表 ==========
class Waypoint(Base):
    """巡检航点 — 任务下的每个扫描位置"""
    __tablename__ = "waypoints"

    id = Column(String(64), primary_key=True)
    task_id = Column(String(64), ForeignKey("tasks.task_code"), nullable=False, comment="关联任务编号")
    shelf_code = Column(String(50), nullable=True, comment="关联货架编号")
    position_x = Column(Float, default=0, comment="位置X")
    position_y = Column(Float, default=0, comment="位置Y")
    position_z = Column(Float, default=0, comment="位置Z")
    camera_angle = Column(Float, default=45.0, comment="摄像头俯仰角")
    expected_sku = Column(String(128), nullable=True, comment="预期SKU")
    expected_location = Column(String(256), nullable=True, comment="预期货架位置描述")
    status = Column(String(16), default="pending", comment="状态: pending / scanning / completed / aborted")
    sort_order = Column(Integer, default=0, comment="扫描顺序")
    scanned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def __init__(self, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = "wp_" + _gen_id("")
        super().__init__(**kwargs)

    task = relationship("Task", back_populates="waypoints")
    image_records = relationship("ImageRecord", back_populates="waypoint")


# ========== 图像记录表 ==========
class ImageRecord(Base):
    """图像记录 — 无人机上传的每张图像"""
    __tablename__ = "image_records"

    id = Column(String(128), primary_key=True, comment="image_id")
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True)
    task_id = Column(String(64), ForeignKey("tasks.task_code"), nullable=True)
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"), nullable=True)

    # 文件存储
    file_path = Column(String(512), comment="本地存储路径")
    file_name = Column(String(256))
    file_size = Column(Integer, comment="字节")
    file_format = Column(String(8), default="jpeg")

    # 采集元数据
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    camera_angle = Column(Float)
    capture_index = Column(Integer, default=0, comment="同一航点第几张")
    rfid_tags = Column(Text, nullable=True, comment="RFID标签JSON")

    # 识别状态
    status = Column(String(16), default="pending", comment="pending / processing / processed / failed")
    queued_at = Column(DateTime)
    processing_started_at = Column(DateTime)
    processed_at = Column(DateTime)
    error_message = Column(String(512), nullable=True)

    # 识别结果
    qr_data = Column(String(256), nullable=True, comment="二维码解码内容")
    confidence = Column(Float, nullable=True, comment="识别置信度 0-1")
    image_quality_score = Column(Float, nullable=True, comment="拉普拉斯方差")
    decoder_used = Column(String(32), nullable=True, comment="wechat_qrcode / pyzbar / none")

    # 库存判定
    inventory_status = Column(String(16), nullable=True, comment="normal/misplaced/missing/extra/duplicate")
    expected_sku = Column(String(128), nullable=True)
    inventory_message = Column(String(512), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    def __init__(self, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = "img_" + _gen_id("")
        super().__init__(**kwargs)

    drone = relationship("Drone")
    task = relationship("Task", back_populates="image_records")
    waypoint = relationship("Waypoint", back_populates="image_records")


# ========== 库存物品表 ==========
class InventoryItem(Base):
    """库存物品 — 识别成功后自动入库"""
    __tablename__ = "inventory_items"

    id = Column(String(128), primary_key=True)
    task_id = Column(String(64), ForeignKey("tasks.task_code"), nullable=True)
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"), nullable=True)
    image_id = Column(String(128), ForeignKey("image_records.id"), nullable=True)

    sku = Column(String(128), comment="识别出的SKU")
    expected_sku = Column(String(128), nullable=True, comment="预期SKU")
    expected_location = Column(String(256), nullable=True)
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    status = Column(String(16), comment="normal/misplaced/missing/extra/duplicate")
    message = Column(String(512), nullable=True)
    confidence = Column(Float, nullable=True)
    source_qr_data = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def __init__(self, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = "inv_" + _gen_id("")
        super().__init__(**kwargs)


# ========== 巡检报告表 ==========
class InspectionReport(Base):
    """巡检报告 — 任务完成后生成"""
    __tablename__ = "inspection_reports"

    id = Column(String(128), primary_key=True)
    task_id = Column(String(64), ForeignKey("tasks.task_code"), nullable=True)
    warehouse_id = Column(String(64), nullable=True)

    total_waypoints = Column(Integer, default=0)
    total_images = Column(Integer, default=0)
    total_recognized = Column(Integer, default=0)
    total_failed = Column(Integer, default=0)

    normal_count = Column(Integer, default=0)
    misplaced_count = Column(Integer, default=0)
    missing_count = Column(Integer, default=0)
    extra_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)
    accuracy = Column(Float, nullable=True)

    details = Column(Text, nullable=True, comment="异常详情JSON")
    generated_at = Column(DateTime, server_default=func.now())
    generated_by = Column(String(128), nullable=True)

    def __init__(self, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = "report_" + _gen_id("")
        super().__init__(**kwargs)


# ========== 用户表 ==========
class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    email = Column(String(100), unique=True, index=True, nullable=True, comment="邮箱")
    hashed_password = Column(String(512), nullable=False, comment="密码哈希")
    full_name = Column(String(100), nullable=True, comment="显示名")
    role = Column(String(20), default="user", comment="角色: admin/user/operator")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ========== RFID库存快照表 ==========
class Inventory(Base):
    """RFID实时库存快照 — 按RFID标签聚合，每次入库时更新"""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), unique=True, nullable=False, comment="RFID标签ID")
    goods_name = Column(String(200), nullable=True, comment="货物名称（冗余自rfid_tags）")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="当前所在货架")
    quantity = Column(Integer, default=0, comment="当前库存数量")
    last_read_at = Column(DateTime, nullable=True, comment="最后读取时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    rfid_tag = relationship("RFIDTag")
    shelf = relationship("Shelf")


# ========== RFID入库记录表 ==========
class InboundRecord(Base):
    """RFID自动入库流水记录"""
    __tablename__ = "inbound_records"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), nullable=True, comment="关联RFID标签(未注册时为空)")
    epc = Column(String(100), nullable=False, index=True, comment="读到的EPC标签号")
    goods_name = Column(String(200), nullable=True, comment="货物名称")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="货架")
    rssi = Column(Integer, nullable=True, comment="信号强度dBm")
    status = Column(String(20), default="success", comment="success / failed")
    message = Column(String(512), nullable=True, comment="备注（失败原因等）")
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # 关系
    rfid_tag = relationship("RFIDTag")
    shelf = relationship("Shelf")


# ========== 系统日志 ==========
class SystemLog(Base):
    """系统日志表"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, comment="日志级别: DEBUG/INFO/WARNING/ERROR")
    source = Column(String(100), comment="日志来源模块")
    message = Column(Text, nullable=False, comment="日志消息")
    details = Column(Text, nullable=True, comment="详细信息JSON")
    created_at = Column(DateTime, server_default=func.now(), index=True)
