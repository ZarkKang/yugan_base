from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func
from ..core.database import Base


class InventoryItem(Base):
    """库存物品 — QR识别成功后自动入库（对齐 warehouse inventory_items 表）"""
    __tablename__ = "inventory_items"

    id = Column(String(128), primary_key=True)
    task_id = Column(String(64), nullable=True)  # FK to tasks.task_code
    waypoint_id = Column(String(64), nullable=True)

    sku = Column(String(128))
    expected_sku = Column(String(128), nullable=True)
    expected_location = Column(String(256), nullable=True)
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    status = Column(String(16))  # normal/misplaced/missing/extra/duplicate
    message = Column(String(512), nullable=True)
    confidence = Column(Float, nullable=True)
    source_qr_data = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
