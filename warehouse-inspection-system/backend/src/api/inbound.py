"""
API路由 - RFID自动入库管理
"""
from fastapi import APIRouter
from ..schemas.schemas import APIResponse
from ..services.inbound_service import get_inbound_service

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