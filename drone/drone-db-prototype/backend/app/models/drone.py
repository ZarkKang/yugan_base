from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class Drone(Base):
    """无人机表 — 两个系统共用，统一字段"""
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    drone_code = Column(String(50), unique=True, index=True, nullable=False)
    drone_name = Column(String(100), nullable=True)
    name = Column(String(100), nullable=True)
    model = Column(String(100))
    manufacturer = Column(String(100), nullable=True)

    status = Column(String(20), default="idle")

    # 位置信息（GPS坐标）
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)

    # 仓库坐标（基站坐标系）
    last_position_x = Column(Float, nullable=True)
    last_position_y = Column(Float, nullable=True)
    last_position_z = Column(Float, nullable=True)

    # 飞行参数
    max_speed = Column(Float, nullable=True)
    max_altitude = Column(Float, nullable=True)
    flight_duration = Column(Integer, nullable=True)

    # 电池
    battery_level = Column(Float, default=100.0)

    # 关联
    sku_id = Column(Integer, ForeignKey("skus.id"), unique=True, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # 备注
    description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    sku = relationship("SKU", back_populates="drone")
    owner = relationship("User", back_populates="drones")
    video_data = relationship("VideoData", back_populates="drone")
    image_data = relationship("ImageData", back_populates="drone")
    rfid_data = relationship("RFIDData", back_populates="drone")
    # 巡检关联关系
    inspection_records = relationship("InspectionRecord", back_populates="drone")
    tasks = relationship("Task", back_populates="drone")
