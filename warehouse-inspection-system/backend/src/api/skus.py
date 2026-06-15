"""
API路由 - SKU管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..db.database import get_db
from ..models.models import InventoryItem, SKU as SKUModel, RFIDTag
from ..schemas.schemas import APIResponse

router = APIRouter(prefix="/skus", tags=["SKU管理"])


@router.get("/", response_model=APIResponse)
def list_skus(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取SKU列表（合并主数据表 + 巡检库存数据）"""
    items = []

    # 1. 从 SKU 主数据表获取
    sku_query = db.query(SKUModel).filter(SKUModel.is_active == True)
    all_skus = sku_query.order_by(SKUModel.id).all()

    # 收集已有 SKU 编码用于去重
    seen_codes = set()
    for s in all_skus:
        items.append({
            "id": s.id,
            "sku": s.sku_code,
            "sku_name": s.name,
            "category": s.category,
            "description": s.description,
            "unit": s.unit,
            "expected_location": None,
            "total_count": 0,
            "has_rfid": db.query(RFIDTag).filter(RFIDTag.sku_id == s.id).count() > 0,
        })
        seen_codes.add(s.sku_code)

    # 2. 从 InventoryItem 补充（巡检发现的 SKU，可能不在主数据表中）
    inv_query = db.query(InventoryItem.sku, InventoryItem.expected_location).filter(InventoryItem.sku.isnot(None))
    if status:
        inv_query = inv_query.filter(InventoryItem.status == status)
    inv_skus = inv_query.distinct().all()
    for sku_code, location in inv_skus:
        if sku_code not in seen_codes:
            count = db.query(InventoryItem).filter(InventoryItem.sku == sku_code).count()
            items.append({
                "id": None,
                "sku": sku_code,
                "sku_name": None,
                "category": None,
                "description": None,
                "unit": None,
                "expected_location": location,
                "total_count": count,
                "has_rfid": False,
            })

    total = len(items)
    paged = items[(page-1)*page_size: page*page_size]

    return APIResponse(success=True, data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": paged,
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
