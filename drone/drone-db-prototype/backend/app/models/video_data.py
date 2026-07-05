from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Text, BigInteger, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class VideoData(Base):
    """无人机视频数据表 — 树叶层

    严格对齐 warehouse-inspection-system 的 video_data 表结构。
    包含巡检关联字段（task_code, waypoint_id）和抽帧/识别状态字段。
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
