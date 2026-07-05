from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class RFIDData(Base):
    """无人机RFID读取数据 — 树叶层

    严格对齐 warehouse-inspection-system 的 rfid_data 表结构。
    rfid_tag 为非唯一索引（同一EPC可在多次巡检/航点重复读取）。
    包含巡检关联字段（task_code, waypoint_id）。
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
