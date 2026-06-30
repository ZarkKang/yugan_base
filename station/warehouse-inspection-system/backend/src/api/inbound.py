"""
API路由 - RFID自动入库管理
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from ..schemas.schemas import APIResponse
from ..services.inbound_service import get_inbound_service
from ..models.models import InboundRecord, Inventory, RFIDTag
from ..db.database import get_db

router = APIRouter(prefix="/inbound", tags=["RFID入库"])


@router.post("/start", response_model=APIResponse)
def inbound_start():
    """启动RFID自动入库"""
    service = get_inbound_service()
    result = service.start()
    return APIResponse(success=result["success"], message=result["message"])


@router.post("/stop", response_model=APIResponse)
def inbound_stop():
    """停止RFID自动入库"""
    service = get_inbound_service()
    result = service.stop()
    return APIResponse(
        success=result["success"],
        message=result["message"],
        data=result.get("data"),
    )


@router.get("/status", response_model=APIResponse)
def inbound_status():
    """获取入库服务状态"""
    service = get_inbound_service()
    result = service.status()
    return APIResponse(success=True, data=result["data"])


@router.get("/records")
def list_records(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询入库流水记录（最新在前）"""
    records = (
        db.query(InboundRecord)
        .order_by(desc(InboundRecord.created_at))
        .limit(limit)
        .all()
    )
    data = [
        {
            "id": r.id,
            "epc": r.epc,
            "goods_name": r.goods_name,
            "rssi": r.rssi,
            "status": r.status,
            "message": r.message,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]
    return APIResponse(success=True, data={"records": data, "total": len(data)})


@router.get("/inventory")
def list_inventory(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """查询当前库存快照"""
    items = (
        db.query(Inventory)
        .join(RFIDTag, Inventory.rfid_tag_id == RFIDTag.id, isouter=True)
        .order_by(desc(Inventory.updated_at))
        .limit(limit)
        .all()
    )
    data = [
        {
            "id": inv.id,
            "epc": inv.rfid_tag.tag_id if inv.rfid_tag else None,
            "goods_name": inv.rfid_tag.goods_name if inv.rfid_tag else None,
            "quantity": inv.quantity,
            "last_read_at": inv.last_read_at.isoformat() if inv.last_read_at else None,
            "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
        }
        for inv in items
    ]
    return APIResponse(success=True, data={"items": data, "total": len(data)})