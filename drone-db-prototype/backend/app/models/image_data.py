from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class ImageData(Base):
    __tablename__ = "image_data"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False)  # 文件名
    file_path = Column(String(500), nullable=False)  # 存储路径
    file_size = Column(BigInteger)  # 文件大小(字节)

    # 图片参数
    width = Column(Integer, nullable=True)  # 宽度
    height = Column(Integer, nullable=True)  # 高度
    format = Column(String(20), nullable=True)  # 格式 JPG/PNG

    # 拍摄信息
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)

    # 关联
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)

    # 元数据
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="image_data")
