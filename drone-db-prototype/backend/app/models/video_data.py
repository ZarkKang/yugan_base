from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class VideoData(Base):
    __tablename__ = "video_data"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String(255), nullable=False)  # 文件名
    file_path = Column(String(500), nullable=False)  # 存储路径
    file_size = Column(BigInteger)  # 文件大小(字节)
    duration = Column(Float, nullable=True)  # 视频时长(秒)

    # 视频参数
    resolution = Column(String(20), nullable=True)  # 分辨率如 1920x1080
    frame_rate = Column(Float, nullable=True)  # 帧率
    codec = Column(String(50), nullable=True)  # 编码格式

    # 拍摄信息
    latitude = Column(Float, nullable=True)  # 拍摄位置
    longitude = Column(Float, nullable=True)
    altitude = Column(Float, nullable=True)  # 飞行高度

    # 关联
    drone_id = Column(Integer, ForeignKey("drones.id"), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)  # 拍摄时间

    # 元数据
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    drone = relationship("Drone", back_populates="video_data")
