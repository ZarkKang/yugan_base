"""
巡检树状结构模型 — 严格对齐 warehouse-inspection-system 的实际表结构

结构: InspectionSession(树干) → Task(树枝) → Waypoint/VideoData/RFIDData/InspectionRecord(树叶)

注意事项:
- Waypoint.id 是 String(64) 主键（不是 Integer）
- Waypoint.task_id 是 FK 到 tasks.task_code（String），不是 tasks.id
- InspectionRecord.task_code 是 FK 到 tasks.task_code
- InspectionRecord.waypoint_id 是 FK 到 waypoints.id（String(64)）
- 这些表已由 warehouse 创建，drone-db 只需 ORM 映射，不做 DDL 变更
"""
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, Text, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from ..core.database import Base


class InspectionStatus(str, enum.Enum):
    """巡检状态枚举 — 对齐 warehouse"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABNORMAL = "abnormal"


class TaskStatus(str, enum.Enum):
    """任务状态枚举 — 对齐 warehouse"""
    CREATED = "created"
    ASSIGNED = "assigned"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class InspectionSession(Base):
    """巡检历史会话 — 树干

    对齐 warehouse inspection_sessions 表。
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

    # 扩展字段
    extra_data = Column(JSON, nullable=True, comment="扩展数据JSON")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系（一对多：一个会话包含多个任务）
    tasks = relationship("Task", back_populates="inspection_session", foreign_keys="Task.session_id")


class Task(Base):
    """巡检任务表 — 树枝层

    对齐 warehouse tasks 表。
    属于某个 InspectionSession（树干），下挂 Waypoint/VideoData/RFIDData/InspectionRecord（树叶）。
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
    video_data = relationship("VideoData", back_populates="task", foreign_keys="VideoData.task_code")
    rfid_data = relationship("RFIDData", back_populates="task", foreign_keys="RFIDData.task_code")
    inspection_records = relationship("InspectionRecord", back_populates="task", foreign_keys="InspectionRecord.task_code")
    inspection_session = relationship("InspectionSession", back_populates="tasks", foreign_keys="Task.session_id")


class Waypoint(Base):
    """巡检航点 — 任务下的每个扫描位置

    对齐 warehouse waypoints 表。
    注意：id 是 String(64) 主键，task_id 是 FK 到 tasks.task_code。
    """
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
    status = Column(String(16), default="pending", comment="状态: pending/scanning/completed/aborted")
    sort_order = Column(Integer, default=0, comment="扫描顺序")
    scanned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # 关系
    task = relationship("Task", back_populates="waypoints")


class InspectionRecord(Base):
    """巡检记录表 — 树叶层

    对齐 warehouse inspection_records 表。
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

    # QR x RFID 交叉校验结果
    qr_rfid_match = Column(Boolean, nullable=True, comment="QR与RFID交叉校验是否通过")
    cross_validation_json = Column(Text, nullable=True, comment="交叉校验明细JSON")
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


class Shelf(Base):
    """货架表 — 对齐 warehouse shelves 表

    货架数据由无人机端 shelves.yaml 推送同步。
    Waypoint 的 shelf_code 引用此表的 shelf_code。
    """
    __tablename__ = "shelves"

    id = Column(Integer, primary_key=True, index=True)
    shelf_code = Column(String(50), index=True, nullable=False, comment="货架编号")
    shelf_name = Column(String(100), comment="货架名称/位置描述")
    zone = Column(String(50), comment="区域")
    position_x = Column(Float, comment="位置X坐标")
    position_y = Column(Float, comment="位置Y坐标")
    position_z = Column(Float, comment="位置Z坐标")
    yaw_rad = Column(Float, nullable=True, comment="偏航角(弧度)")
    arrival_radius_m = Column(Float, nullable=True, comment="到达半径(米)")
    dwell_time_s = Column(Float, nullable=True, comment="停留时间(秒)")
    rows = Column(Integer, default=1, comment="行数")
    columns = Column(Integer, default=1, comment="列数")
    levels = Column(Integer, default=1, comment="层数")
    qr_code = Column(String(200), nullable=True, comment="关联二维码")
    status = Column(String(20), default="normal", comment="状态")
    archived_at = Column(DateTime, nullable=True, comment="归档时间")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_synced_at = Column(DateTime, nullable=True, comment="最后同步时间")

    # 关系
    inspection_records = relationship("InspectionRecord", back_populates="shelf")
    rfid_tags = relationship("RFIDTag", back_populates="shelf")


class RFIDTag(Base):
    """RFID标签表 — 对齐 warehouse rfid_tags 表"""
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
