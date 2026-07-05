from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class ImageData(Base):
    """无人机图片数据表

    对齐 warehouse-inspection-system 的 image_data 表结构。
    warehouse 的 image_data 表目前无 task_code/waypoint_id 字段
    （巡检图片走 image_records 表），此处保持与实际表一致。
    """
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
