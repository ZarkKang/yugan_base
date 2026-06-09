from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Float, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from ..core.database import Base


class DroneStatus(str, enum.Enum):
    IDLE = "idle"
    FLYING = "flying"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class Drone(Base):
    __tablename__ = "drones"

    id = Column(Integer, primary_key=True, index=True)
    drone_code = Column(String(50), unique=True, index=True, nullable=False)  # 无人机编号
    name = Column(String(100), nullable=False)  # 无人机名称
    model = Column(String(100))  # 型号
    manufacturer = Column(String(100))  # 制造商
    status = Column(Enum(DroneStatus), default=DroneStatus.IDLE)

    # 位置信息
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)  # 海拔高度(米)

    # 飞行参数
    max_speed = Column(Float, nullable=True)  # 最大速度 (km/h)
    max_altitude = Column(Float, nullable=True)  # 最大飞行高度 (米)
    flight_duration = Column(Integer, nullable=True)  # 续航时间(分钟)

    # 关联
    sku_id = Column(Integer, ForeignKey("skus.id"), unique=True, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # 备注
    description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    sku = relationship("SKU", back_populates="drone")
    owner = relationship("User", back_populates="drones")
    video_data = relationship("VideoData", back_populates="drone")
    image_data = relationship("ImageData", back_populates="drone")
    rfid_data = relationship("RFIDData", back_populates="drone")
