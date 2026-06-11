"""
系统状态API - 连接检测、健康状态
  GET /api/v1/system/status       获取所有连接状态
  GET /api/v1/system/health       增强版健康检查
  POST /api/v1/system/reconnect   重新检测所有连接
"""
import logging
from fastapi import APIRouter

from ..services.connection_monitor import get_connection_monitor
from ..schemas.schemas import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["系统状态"])


@router.get("/status")
def get_system_status():
    """获取所有模块连接状态: 图传模块、后端API、网关、RFID、数据库、Redis"""
    monitor = get_connection_monitor()
    statuses = monitor.get_all_status()
    ready = monitor.is_ready()

    return APIResponse(success=True, data={
        "ready": ready,
        "modules": statuses,
    })


@router.get("/health")
def health_check():
    """增强版健康检查 - 返回详细状态"""
    monitor = get_connection_monitor()
    statuses = monitor.get_all_status()

    all_healthy = all(
        s.get("connected", False)
        for k, s in statuses.items()
        if k in ("backend_api", "database")
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "modules": statuses,
    }


@router.get("/module/{module_id}")
def get_module_status(module_id: str):
    """获取单个模块连接状态"""
    monitor = get_connection_monitor()
    status = monitor.get_status(module_id)
    if status is None:
        return APIResponse(success=False, message=f"未知模块: {module_id}")
    return APIResponse(success=True, data={
        "name": status.name,
        "connected": status.connected,
        "last_check_time": status.last_check_time.isoformat() if status.last_check_time else None,
        "response_time_ms": status.response_time_ms,
        "error_message": status.error_message,
        "details": status.details,
    })


@router.post("/reconnect")
def reconnect_all():
    """强制重新检测所有连接"""
    monitor = get_connection_monitor()
    # 触发立即检测
    monitor.check_video_transmitter()
    statuses = monitor.get_all_status()
    return APIResponse(success=True, message="已重新检测所有连接", data={"modules": statuses})