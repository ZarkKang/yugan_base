"""
API路由 - SKU管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..db.database import get_db
from ..models.models import InventoryItem
from ..schemas.schemas import APIResponse

router = APIRouter(prefix="/skus", tags=["SKU管理"])


@router.get("/", response_model=APIResponse)
def list_skus(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取SKU列表（从库存物品聚合）"""
    query = db.query(InventoryItem.sku, InventoryItem.expected_location).filter(InventoryItem.sku.isnot(None))
    if status:
        query = query.filter(InventoryItem.status == status)

    # 去重统计
    skus = query.distinct().offset((page-1)*page_size).limit(page_size).all()
    total = query.distinct().count()

    items = []
    for sku, location in skus:
        count = db.query(InventoryItem).filter(InventoryItem.sku == sku).count()
        items.append({
            "sku": sku,
            "expected_location": location,
            "total_count": count,
        })

    return APIResponse(success=True, data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    })


@router.get("/{sku}", response_model=APIResponse)
def get_sku(sku: str, db: Session = Depends(get_db)):
    """获取SKU详情及库存记录"""
    items = db.query(InventoryItem).filter(InventoryItem.sku == sku).all()
    if not items:
        raise HTTPException(status_code=404, detail="SKU不存在")

    return APIResponse(success=True, data={
        "sku": sku,
        "expected_location": items[0].expected_location,
        "total_count": len(items),
        "records": [
            {
                "id": item.id,
                "status": item.status,
                "position": {"x": item.position_x, "y": item.position_y, "z": item.position_z},
                "confidence": item.confidence,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    })


@router.get("/{sku}/locations", response_model=APIResponse)
def get_sku_locations(sku: str, db: Session = Depends(get_db)):
    """获取SKU的所有存放位置"""
    items = db.query(InventoryItem).filter(InventoryItem.sku == sku).all()
    if not items:
        raise HTTPException(status_code=404, detail="SKU不存在")

    locations = []
    for item in items:
        locations.append({
            "id": item.id,
            "expected_location": item.expected_location,
            "actual_position": {"x": item.position_x, "y": item.position_y, "z": item.position_z},
            "status": item.status,
            "message": item.message,
        })

    return APIResponse(success=True, data={
        "sku": sku,
        "total_locations": len(locations),
        "locations": locations,
    })
