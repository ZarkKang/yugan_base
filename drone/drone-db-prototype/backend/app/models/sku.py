from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from ..core.database import Base


class SKU(Base):
    __tablename__ = "skus"

    id = Column(Integer, primary_key=True, index=True)
    sku_code = Column(String(50), unique=True, index=True, nullable=False)  # SKU编码
    name = Column(String(100), nullable=False)  # SKU名称
    description = Column(Text, nullable=True)  # 描述
    category = Column(String(50), index=True)  # 分类
    unit = Column(String(20), default="个")  # 单位
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # 关系
    drone = relationship("Drone", back_populates="sku", uselist=False)
