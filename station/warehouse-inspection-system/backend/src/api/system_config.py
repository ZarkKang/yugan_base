"""
系统配置 API — 航点视频截取配置
================================
提供航点视频截取参数的 CRUD 端点，需 JWT 认证。
"""
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db.database import SessionLocal, get_db
from .auth import get_current_user
from ..schemas.schemas import ClipCaptureConfigRequest, ClipCaptureConfigResponse
from ..services.clip_config import (
    get_clip_config,
    update_clip_config_batch,
    reset_clip_config,
)
from ..models.models import APIResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["系统配置"])


def _config_to_response(config: dict) -> ClipCaptureConfigResponse:
    """内部字典 → Response Schema"""
    return ClipCaptureConfigResponse(
        capture_enabled=config.get("waypoint_clip_capture_enabled", True),
        capture_delay_seconds=config.get("waypoint_clip_capture_delay_seconds", 0.0),
        capture_duration_seconds=config.get("waypoint_clip_capture_duration_seconds", 10.0),
        position_tolerance_meters=config.get("waypoint_clip_position_tolerance_meters", 0.2),
    )


@router.get("/config/clip", response_model=ClipCaptureConfigResponse)
async def get_clip_capture_config(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取航点视频截取配置"""
    config = get_clip_config(db)
    return _config_to_response(config)


@router.put("/config/clip", response_model=ClipCaptureConfigResponse)
async def update_clip_capture_config(
    body: ClipCaptureConfigRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """批量更新航点视频截取配置"""
    updates = {}
    if body.capture_enabled is not None:
        updates["waypoint_clip_capture_enabled"] = body.capture_enabled
    if body.capture_delay_seconds is not None:
        updates["waypoint_clip_capture_delay_seconds"] = body.capture_delay_seconds
    if body.capture_duration_seconds is not None:
        updates["waypoint_clip_capture_duration_seconds"] = body.capture_duration_seconds
    if body.position_tolerance_meters is not None:
        updates["waypoint_clip_position_tolerance_meters"] = body.position_tolerance_meters

    if not updates:
        config = get_clip_config(db)
        return _config_to_response(config)

    config = update_clip_config_batch(db, updates)
    logger.info("[ClipConfig] 配置已更新: %s", updates)
    return _config_to_response(config)


@router.post("/config/clip/reset", response_model=ClipCaptureConfigResponse)
async def reset_clip_capture_config(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """重置航点视频截取配置为默认值"""
    config = reset_clip_config(db)
    logger.info("[ClipConfig] 配置已重置为默认值")
    return _config_to_response(config)
