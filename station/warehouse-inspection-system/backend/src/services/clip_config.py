"""
航点视频截取配置服务
==================
封装 SystemConfig 表中 waypoint_clip_* 配置的读写，
提供类型安全的 Python 接口。

调用方：
  - VideoStreamAggregator.schedule_clip_capture() — 读取配置
  - api/system_config.py — CRUD 端点
"""
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from ..models.models import SystemConfig

logger = logging.getLogger(__name__)

# ── 默认值常量（DB 中无记录时的兜底）──────────────────────────

DEFAULTS: Dict[str, Any] = {
    "waypoint_clip_capture_enabled": True,
    "waypoint_clip_capture_delay_seconds": 0.0,
    "waypoint_clip_capture_duration_seconds": 10.0,
    "waypoint_clip_position_tolerance_meters": 0.2,
}

# key → value_type 映射
_KEY_TYPES: Dict[str, str] = {
    "waypoint_clip_capture_enabled": "boolean",
    "waypoint_clip_capture_delay_seconds": "float",
    "waypoint_clip_capture_duration_seconds": "float",
    "waypoint_clip_position_tolerance_meters": "float",
}


# ── 类型转换 ────────────────────────────────────────────────

def _cast(value: str, value_type: str) -> Any:
    """字符串值 → Python 类型"""
    if value_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    if value_type == "integer":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "json":
        import json
        return json.loads(value)
    return value  # string


def _to_str(value: Any) -> str:
    """Python 值 → 字符串存储"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ── 公共接口 ────────────────────────────────────────────────

def get_clip_config(db: Session) -> Dict[str, Any]:
    """获取所有截取配置，返回 {key: python_value} 字典

    DB 中未找到的 key 用 DEFAULTS 兜底。
    """
    rows = db.query(SystemConfig).filter(
        SystemConfig.key.in_(DEFAULTS.keys())
    ).all()
    config_map = {r.key: _cast(r.value, r.value_type) for r in rows}

    result = {}
    for key, default_val in DEFAULTS.items():
        result[key] = config_map.get(key, default_val)
    return result


def get_clip_config_value(db: Session, key: str) -> Any:
    """获取单个配置值"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        return DEFAULTS.get(key)
    return _cast(row.value, row.value_type)


def update_clip_config(db: Session, key: str, value: Any) -> bool:
    """更新单个配置（UPSERT）"""
    value_str = _to_str(value)
    value_type = _KEY_TYPES.get(key, "string")

    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row is None:
        row = SystemConfig(key=key, value=value_str, value_type=value_type)
        db.add(row)
    else:
        row.value = value_str
    db.commit()
    logger.info("[ClipConfig] 配置更新: %s = %s", key, value_str)
    return True


def update_clip_config_batch(db: Session, updates: Dict[str, Any]) -> Dict[str, Any]:
    """批量更新截取配置

    Args:
        updates: {key: python_value} 字典，仅包含需要更新的 key

    Returns:
        更新后的完整配置
    """
    for key, value in updates.items():
        if key in DEFAULTS:
            update_clip_config(db, key, value)
    return get_clip_config(db)


def reset_clip_config(db: Session) -> Dict[str, Any]:
    """重置截取配置为默认值（删除 DB 记录）"""
    db.query(SystemConfig).filter(
        SystemConfig.key.in_(DEFAULTS.keys())
    ).delete(synchronize_session=False)
    db.commit()
    logger.info("[ClipConfig] 配置已重置为默认值")
    return dict(DEFAULTS)
