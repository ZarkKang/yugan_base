"""
数据模型 - 数据库表结构定义
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..db.database import Base
import enum


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

    # 元数据
    created_by = Column(String(100), nullable=True, comment="创建人")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 关系
    drone = relationship("Drone", back_populates="tasks")


class SystemLog(Base):
    """系统日志表"""
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False, comment="日志级别: DEBUG/INFO/WARNING/ERROR")
    source = Column(String(100), comment="日志来源模块")
    message = Column(Text, nullable=False, comment="日志消息")
    details = Column(Text, nullable=True, comment="详细信息JSON")
    created_at = Column(DateTime, server_default=func.now(), index=True)
