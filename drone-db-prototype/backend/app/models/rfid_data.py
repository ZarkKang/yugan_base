from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class RFIDData(Base):
    __tablename__ = "rfid_data"

    id = Column(Integer, primary_key=True, index=True)
    rfid_tag = Column(String(100), unique=True, index=True, nullable=False)  # RFID标签ID
    tag_type = Column(String(50), nullable=True)  # 标签类型

    # 位置信息
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)

    # 信号强度
    signal_strength = Column(Float, nullable=True)  # dBm

    # 关联无人机
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True)

    # 检测时间
    detected_at = Column(DateTime(timezone=True), nullable=True)

    # 元数据
    description = Column(Text, nullable=True)
    is_valid = Column(Boolean, default=True)  # 是否有效
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="rfid_data")
