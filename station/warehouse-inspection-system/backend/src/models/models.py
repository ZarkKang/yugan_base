"""
数据模型 - 数据库表结构定义
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum, JSON, BigInteger
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
    """无人机表 — 两个系统共用，统一字段"""
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    drone_code = Column(String(50), unique=True, index=True, nullable=False, comment="无人机编号")
    drone_name = Column(String(100), comment="无人机名称")
    name = Column(String(100), nullable=True, comment="无人机名称（兼容无人机数据系统）")
    model = Column(String(100), comment="型号")
    manufacturer = Column(String(100), nullable=True, comment="制造商")

    status = Column(String(20), default="idle", comment="状态: idle/flying/maintenance/retired/online/offline")

    # 位置信息（GPS坐标）
    latitude = Column(Float, nullable=True, comment="纬度")
    longitude = Column(Float, nullable=True, comment="经度")
    altitude = Column(Float, nullable=True, comment="海拔高度(米)")

    # 仓库坐标（基站坐标系）
    last_position_x = Column(Float, nullable=True, comment="最后位置X")
    last_position_y = Column(Float, nullable=True, comment="最后位置Y")
    last_position_z = Column(Float, nullable=True, comment="最后位置Z")

    # 飞行参数
    max_speed = Column(Float, nullable=True, comment="最大速度(km/h)")
    max_altitude = Column(Float, nullable=True, comment="最大飞行高度(米)")
    flight_duration = Column(Integer, nullable=True, comment="续航时间(分钟)")

    # 电池
    battery_level = Column(Float, default=100.0, comment="电池电量百分比")

    # 关联
    sku_id = Column(Integer, ForeignKey("skus.id"), unique=True, nullable=True, comment="关联SKU")
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="所属用户")

    # 备注
    description = Column(Text, nullable=True, comment="描述")
    is_active = Column(Boolean, default=True, comment="是否启用")

    last_seen = Column(DateTime, nullable=True, comment="最后在线时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    sku = relationship("SKU", back_populates="drone", foreign_keys=[sku_id])
    owner = relationship("User", back_populates="drones", foreign_keys=[owner_id])
    inspection_records = relationship("InspectionRecord", back_populates="drone")
    tasks = relationship("Task", back_populates="drone")
    video_data = relationship("VideoData", back_populates="drone")
    image_data = relationship("ImageData", back_populates="drone")
    rfid_data = relationship("RFIDData", back_populates="drone")


class Shelf(Base):
    """货架表

    货架数据由无人机端 shelves.yaml 推送同步，基站端不再手动创建。
    archived_at 用于软删除：无人机端删除货架后，基站端标记归档时间，
    保留历史数据关联，允许 shelf_code 在归档后被重新使用。
    """
    __tablename__ = "shelves"

    id = Column(Integer, primary_key=True, index=True)
    # 非唯一索引：允许已归档(archived_at IS NOT NULL)的 shelf_code 被重新使用
    shelf_code = Column(String(50), index=True, nullable=False, comment="货架编号(来自无人机端shelf_id)")
    shelf_name = Column(String(100), comment="货架名称/位置描述")
    zone = Column(String(50), comment="区域")
    position_x = Column(Float, comment="位置X坐标")
    position_y = Column(Float, comment="位置Y坐标")
    position_z = Column(Float, comment="位置Z坐标")
    yaw_rad = Column(Float, nullable=True, comment="偏航角(弧度,来自无人机端)")
    arrival_radius_m = Column(Float, nullable=True, comment="到达半径(米,来自无人机端)")
    dwell_time_s = Column(Float, nullable=True, comment="停留时间(秒,来自无人机端)")
    rows = Column(Integer, default=1, comment="行数")
    columns = Column(Integer, default=1, comment="列数")
    levels = Column(Integer, default=1, comment="层数")
    qr_code = Column(String(200), nullable=True, comment="关联二维码")
    status = Column(String(20), default="normal", comment="状态: normal/damaged/maintenance/archived")
    archived_at = Column(DateTime, nullable=True, comment="归档时间(无人机端删除后标记)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_synced_at = Column(DateTime, nullable=True, comment="最后一次无人机同步时间")

    # 关系
    inspection_records = relationship("InspectionRecord", back_populates="shelf")
    rfid_tags = relationship("RFIDTag", back_populates="shelf")


class RFIDTag(Base):
    """RFID标签表"""
    __tablename__ = "rfid_tags"

    id = Column(Integer, primary_key=True, index=True)
    tag_id = Column(String(100), unique=True, index=True, nullable=False, comment="标签UID")
    tag_type = Column(String(50), comment="标签类型")
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=True, comment="关联SKU")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="关联货架")
    goods_name = Column(String(200), nullable=True, comment="货物名称")
    goods_quantity = Column(Integer, default=0, comment="货物数量")
    last_read_time = Column(DateTime, nullable=True, comment="最后读取时间")
    last_read_strength = Column(Integer, nullable=True, comment="最后读取信号强度")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    sku = relationship("SKU")
    shelf = relationship("Shelf", back_populates="rfid_tags")
    inspection_records = relationship("InspectionRecord", back_populates="rfid_tag")


class InspectionSession(Base):
    """巡检历史会话 — 树干

    聚合多次巡检任务（Task），作为巡检历史的顶层容器。
    结构：Session(树干) → Task(树枝) → VideoData/RFIDData/ImageRecord/InspectionRecord(树叶)
    一对多关系：一个 Session 可包含多个 Task（通过 Task.session_id 反向关联）。

    扩展设计：extra_data JSON 字段供后续添加字段时使用，
    新增字段的旧数据为 NULL 不会导致结构变化错误。
    """
    __tablename__ = "inspection_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_code = Column(String(50), unique=True, index=True, nullable=False, comment="会话编号")
    container_code = Column(String(100), nullable=True, comment="货柜号")

    # 时间
    start_time = Column(DateTime, nullable=True, comment="开始时间")
    end_time = Column(DateTime, nullable=True, comment="结束时间")

    # 统计
    abnormal_count = Column(Integer, default=0, comment="异常数")
    total_waypoints = Column(Integer, default=0, comment="总航点数")
    total_records = Column(Integer, default=0, comment="总记录数")

    # 状态
    status = Column(String(20), default="pending", comment="状态: pending/running/completed/abnormal")

    # 扩展字段（供后续添加字段时使用，旧数据不受结构变化影响）
    extra_data = Column(JSON, nullable=True, comment="扩展数据JSON（后续字段扩展用）")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系（一对多：一个会话包含多个任务）
    tasks = relationship("Task", back_populates="inspection_session", foreign_keys="Task.session_id")


class InspectionRecord(Base):
    """巡检记录表 — 树叶层

    航点级巡检快照，关联到 Task 和 Waypoint。
    """
    __tablename__ = "inspection_records"

    id = Column(Integer, primary_key=True, index=True)
    record_code = Column(String(128), unique=True, index=True, nullable=False, comment="记录编号")
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=False, comment="无人机ID")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="货架ID")
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), nullable=True, comment="RFID标签ID")

    # 树叶关联（关联到树枝 Task 和 Waypoint）
    task_code = Column(String(50), ForeignKey("tasks.task_code"), nullable=True, comment="关联任务编号")
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"), nullable=True, comment="关联航点ID")

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

    # QR×RFID 交叉校验结果（Q18: RFID有QR无 / QR有RFID无 均标记异常）
    qr_rfid_match = Column(Boolean, nullable=True, comment="QR与RFID交叉校验是否通过")
    cross_validation_json = Column(Text, nullable=True, comment="交叉校验明细JSON: {qr_only:[], rfid_only:[], matched:[]}")
    abnormal_tags_json = Column(Text, nullable=True, comment="异常标签明细JSON")

    # 元数据
    inspection_time = Column(DateTime, nullable=True, comment="巡检时间")
    duration_ms = Column(Integer, nullable=True, comment="处理耗时(毫秒)")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="inspection_records")
    shelf = relationship("Shelf", back_populates="inspection_records")
    rfid_tag = relationship("RFIDTag", back_populates="inspection_records")
    task = relationship("Task", back_populates="inspection_records", foreign_keys=[task_code])
    waypoint = relationship("Waypoint", foreign_keys=[waypoint_id])


class Task(Base):
    """巡检任务表 — 树枝层

    属于某个 InspectionSession（树干），下挂 Waypoint/ImageRecord/VideoData/RFIDData（树叶）。
    """
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

    # 树枝关联（关联到树干 InspectionSession）
    session_id = Column(Integer, ForeignKey("inspection_sessions.id"), nullable=True, comment="关联巡检历史会话")

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
    video_data = relationship("VideoData", back_populates="task", foreign_keys="VideoData.task_code")
    rfid_data = relationship("RFIDData", back_populates="task", foreign_keys="RFIDData.task_code")
    inspection_records = relationship("InspectionRecord", back_populates="task", foreign_keys="InspectionRecord.task_code")
    inspection_session = relationship("InspectionSession", back_populates="tasks", foreign_keys="Task.session_id")


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
    """用户表 — 两个系统共用"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    email = Column(String(100), unique=True, index=True, nullable=True, comment="邮箱")
    hashed_password = Column(String(512), nullable=False, comment="密码哈希")
    full_name = Column(String(100), nullable=True, comment="显示名")
    role = Column(String(20), default="operator", comment="角色: admin/operator/viewer")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drones = relationship("Drone", back_populates="owner", foreign_keys="Drone.owner_id")


# ========== RFID库存快照表 ==========
class Inventory(Base):
    """RFID实时库存快照 — 按RFID标签聚合，每次入库时更新"""
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), unique=True, nullable=False, comment="RFID标签ID")
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=True, comment="关联SKU")
    goods_name = Column(String(200), nullable=True, comment="货物名称（冗余自rfid_tags）")
    shelf_id = Column(Integer, ForeignKey("shelves.id"), nullable=True, comment="当前所在货架")
    quantity = Column(Integer, default=0, comment="当前库存数量")
    last_read_at = Column(DateTime, nullable=True, comment="最后读取时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    rfid_tag = relationship("RFIDTag")
    sku = relationship("SKU")
    shelf = relationship("Shelf")


# ========== RFID入库记录表 ==========
class InboundRecord(Base):
    """RFID自动入库流水记录"""
    __tablename__ = "inbound_records"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag_id = Column(Integer, ForeignKey("rfid_tags.id"), nullable=True, comment="关联RFID标签(未注册时为空)")
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=True, comment="关联SKU")
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


# ========== SKU表 ==========
class SKU(Base):
    """SKU表 — 两个系统共用"""
    __tablename__ = "skus"

    id = Column(Integer, primary_key=True, index=True)
    sku_code = Column(String(50), unique=True, index=True, nullable=False, comment="SKU编码")
    name = Column(String(100), nullable=False, comment="SKU名称")
    description = Column(Text, nullable=True, comment="描述")
    category = Column(String(50), index=True, comment="分类")
    unit = Column(String(20), default="个", comment="单位")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drone = relationship("Drone", back_populates="sku", uselist=False, foreign_keys="Drone.sku_id")


# ========== 视频数据表 ==========
class VideoData(Base):
    """无人机视频数据表 — 树叶层

    属于某个 Task（树枝），可关联到 Waypoint。
    用于抽帧后 QR 识别与库存比对的数据源。
    """
    __tablename__ = "video_data"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False, comment="文件名")
    file_path = Column(String(500), nullable=False, comment="存储路径")
    file_size = Column(BigInteger, comment="文件大小(字节)")
    duration = Column(Float, nullable=True, comment="视频时长(秒)")

    # 视频参数
    resolution = Column(String(20), nullable=True, comment="分辨率如1920x1080")
    frame_rate = Column(Float, nullable=True, comment="帧率")
    codec = Column(String(50), nullable=True, comment="编码格式")

    # 拍摄信息
    latitude = Column(Float, nullable=True, comment="拍摄位置纬度")
    longitude = Column(Float, nullable=True, comment="拍摄位置经度")
    altitude = Column(Float, nullable=True, comment="飞行高度")

    # 关联
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True, comment="关联无人机")
    # 树叶关联（关联到树枝 Task 和 Waypoint）
    task_code = Column(String(50), ForeignKey("tasks.task_code"), nullable=True, comment="关联任务编号")
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"), nullable=True, comment="关联航点ID")
    captured_at = Column(DateTime, nullable=True, comment="拍摄时间")

    # 抽帧/识别状态
    frame_extracted = Column(Boolean, default=False, comment="是否已完成抽帧")
    frame_count = Column(Integer, default=0, comment="抽帧总数")
    qr_recognized = Column(Boolean, default=False, comment="是否已完成QR识别")
    qr_codes_json = Column(Text, nullable=True, comment="视频中识别到的二维码JSON列表")
    processing_status = Column(String(20), default="pending", comment="处理状态: pending/extracting/recognizing/completed/failed")
    processing_error = Column(Text, nullable=True, comment="处理失败原因")

    # 元数据
    description = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drone = relationship("Drone", back_populates="video_data")
    task = relationship("Task", foreign_keys=[task_code])
    waypoint = relationship("Waypoint", foreign_keys=[waypoint_id])


# ========== 图片数据表 ==========
class ImageData(Base):
    """无人机图片数据表"""
    __tablename__ = "image_data"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False, comment="文件名")
    file_path = Column(String(500), nullable=False, comment="存储路径")
    file_size = Column(BigInteger, comment="文件大小(字节)")

    # 图片参数
    width = Column(Integer, nullable=True, comment="宽度")
    height = Column(Integer, nullable=True, comment="高度")
    format = Column(String(20), nullable=True, comment="格式JPG/PNG")

    # 拍摄信息
    latitude = Column(Float, nullable=True, comment="拍摄位置纬度")
    longitude = Column(Float, nullable=True, comment="拍摄位置经度")
    altitude = Column(Float, nullable=True, comment="飞行高度")

    # 关联
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True, comment="关联无人机")
    captured_at = Column(DateTime, nullable=True, comment="拍摄时间")

    # 元数据
    description = Column(Text, nullable=True, comment="备注")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="image_data")


# ========== 无人机RFID读取数据表 ==========
class RFIDData(Base):
    """无人机RFID读取数据 — 树叶层

    无人机飞行中读取到的RFID标签记录，属于某个 Task（树枝），可关联到 Waypoint。
    rfid_tag 去除 unique 约束：同一标签在不同巡检/航点会被多次读取。
    """
    __tablename__ = "rfid_data"

    id = Column(Integer, primary_key=True, index=True)
    # 非唯一索引：同一EPC可在多次巡检/航点重复读取
    rfid_tag = Column(String(100), index=True, nullable=False, comment="RFID标签ID(EPC)")
    tag_type = Column(String(50), nullable=True, comment="标签类型")

    # 位置信息
    latitude = Column(Float, nullable=True, comment="纬度")
    longitude = Column(Float, nullable=True, comment="经度")
    altitude = Column(Float, nullable=True, comment="海拔")

    # 信号强度
    signal_strength = Column(Float, nullable=True, comment="信号强度dBm")

    # 关联无人机
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True, comment="读取无人机")
    # 树叶关联（关联到树枝 Task 和 Waypoint）
    task_code = Column(String(50), ForeignKey("tasks.task_code"), nullable=True, comment="关联任务编号")
    waypoint_id = Column(String(64), ForeignKey("waypoints.id"), nullable=True, comment="关联航点ID")

    # 检测时间
    detected_at = Column(DateTime, nullable=True, comment="检测时间")

    # 元数据
    description = Column(Text, nullable=True, comment="备注")
    is_valid = Column(Boolean, default=True, comment="是否有效")
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="rfid_data")
    task = relationship("Task", foreign_keys=[task_code])
    waypoint = relationship("Waypoint", foreign_keys=[waypoint_id])


# ========== 无人机图传设备配置表 ==========
class DroneDevice(Base):
    """无人机图传设备配置 — 存储无人机图传设备的通信参数"""
    __tablename__ = "drone_devices"

    id = Column(Integer, primary_key=True, index=True)
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=False, comment="关联无人机")
    device_name = Column(String(100), nullable=False, comment="设备名称")
    device_model = Column(String(100), nullable=True, comment="设备型号")
    firmware_version = Column(String(50), nullable=True, comment="固件版本")
    ip_address = Column(String(45), nullable=False, comment="设备IP地址")
    port = Column(Integer, default=8080, comment="通信端口")
    protocol = Column(String(20), default="HTTP", comment="通信协议: HTTP/RTSP/MQTT/WebSocket")
    auth_type = Column(String(20), default="none", comment="认证方式: none/basic/token/certificate")
    auth_credential = Column(Text, nullable=True, comment="认证凭据(加密存储)")
    encryption_enabled = Column(Boolean, default=False, comment="是否启用加密")
    encryption_type = Column(String(20), nullable=True, comment="加密方式: AES/TLS")
    encryption_key = Column(Text, nullable=True, comment="加密密钥")
    status = Column(String(20), default="offline", comment="设备状态: online/offline/connecting/error")
    last_connected_at = Column(DateTime, nullable=True, comment="最后连接时间")
    heartbeat_interval = Column(Integer, default=5, comment="心跳间隔(秒)")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drone = relationship("Drone", foreign_keys=[drone_id])
    communication_logs = relationship("CommunicationLog", back_populates="device", cascade="all, delete-orphan")
    automated_tasks = relationship("AutomatedTask", back_populates="device", cascade="all, delete-orphan")


# ========== 通信日志表 ==========
class CommunicationLog(Base):
    """设备通信日志 — 记录无人机与基站之间的通信活动"""
    __tablename__ = "communication_logs"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("drone_devices.id"), nullable=False, comment="关联设备")
    log_type = Column(String(20), nullable=False, comment="日志类型: connection/data/error/heartbeat")
    direction = Column(String(10), nullable=False, comment="通信方向: send/receive")
    data_type = Column(String(30), nullable=True, comment="数据类型: video/rfid_json/image/qr_code/command")
    payload_summary = Column(String(500), nullable=True, comment="数据摘要")
    payload_size = Column(BigInteger, nullable=True, comment="数据大小(字节)")
    status = Column(String(20), default="success", comment="状态: success/failed/timeout")
    error_message = Column(Text, nullable=True, comment="错误信息")
    response_time_ms = Column(Integer, nullable=True, comment="响应时间(毫秒)")
    source_ip = Column(String(45), nullable=True, comment="源IP")
    target_ip = Column(String(45), nullable=True, comment="目标IP")
    created_at = Column(DateTime, server_default=func.now(), index=True)

    # 关系
    device = relationship("DroneDevice", back_populates="communication_logs")


# ========== 自动化任务表 ==========
class AutomatedTask(Base):
    """自动化任务配置 — 无人机定时采集与回传任务"""
    __tablename__ = "automated_tasks"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(Integer, ForeignKey("drone_devices.id"), nullable=False, comment="关联设备")
    task_name = Column(String(200), nullable=False, comment="任务名称")
    task_type = Column(String(30), nullable=False, comment="任务类型: video_capture/rfid_read/both")
    schedule_type = Column(String(20), default="interval", comment="调度类型: interval/cron/once")
    schedule_value = Column(String(100), nullable=False, comment="调度值: 秒数/cron表达式/ISO时间")
    target_storage_path = Column(String(500), nullable=False, comment="目标存储路径(基站192.168.1.200)")
    target_shelves = Column(Text, nullable=True, comment="目标货架编号JSON列表,如[\"SHELF-001\",\"SHELF-002\"]")
    video_duration = Column(Integer, default=30, comment="视频采集时长(秒)")
    video_resolution = Column(String(20), default="1920x1080", comment="视频分辨率")
    rfid_read_duration = Column(Integer, default=10, comment="RFID读取时长(秒)")
    json_filename_pattern = Column(String(200), default="drone_{device_id}_{timestamp}.json", comment="JSON文件名模板")
    enabled = Column(Boolean, default=True, comment="是否启用")
    last_run_at = Column(DateTime, nullable=True, comment="上次执行时间")
    last_run_status = Column(String(20), nullable=True, comment="上次执行状态: success/failed")
    next_run_at = Column(DateTime, nullable=True, comment="下次执行时间")
    run_count = Column(Integer, default=0, comment="执行次数")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    device = relationship("DroneDevice", back_populates="automated_tasks")


# ========== 网络扫描结果表 ==========
class NetworkScanResult(Base):
    """网络扫描结果 — 记录设备发现扫描的结果"""
    __tablename__ = "network_scan_results"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(String(50), index=True, nullable=False, comment="扫描批次ID")
    ip_address = Column(String(45), nullable=False, comment="发现的IP地址")
    hostname = Column(String(200), nullable=True, comment="主机名")
    mac_address = Column(String(17), nullable=True, comment="MAC地址")
    device_type = Column(String(50), nullable=True, comment="设备类型: drone_transmitter/base_station/unknown")
    open_ports = Column(Text, nullable=True, comment="开放端口列表JSON")
    response_time_ms = Column(Float, nullable=True, comment="响应时间(毫秒)")
    device_info = Column(Text, nullable=True, comment="设备详细信息JSON")
    verified = Column(Boolean, default=False, comment="是否已通过验证")
    registered = Column(Boolean, default=False, comment="是否已注册到系统")
    discovered_at = Column(DateTime, server_default=func.now(), index=True)
