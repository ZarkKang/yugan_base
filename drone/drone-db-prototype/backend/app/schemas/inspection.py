"""
巡检树状结构 Pydantic schemas — 查询响应模型

结构: InspectionSessionResponse(树干) → TaskResponse(树枝) → WaypointResponse/InspectionRecordResponse(树叶)
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# ── Waypoint ──
class WaypointResponse(BaseModel):
    id: str  # String(64) 主键
    task_id: Optional[str] = None
    shelf_code: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    position_z: Optional[float] = None
    camera_angle: Optional[float] = None
    expected_sku: Optional[str] = None
    expected_location: Optional[str] = None
    status: Optional[str] = None
    sort_order: Optional[int] = None
    scanned_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Task (含 waypoints 子节点) ──
class TaskResponse(BaseModel):
    id: int
    task_code: str
    task_name: Optional[str] = None
    task_type: Optional[str] = None
    status: Optional[str] = None
    drone_id: Optional[int] = None
    session_id: Optional[int] = None
    target_shelves: Optional[str] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_records: Optional[int] = 0
    abnormal_records: Optional[int] = 0
    total_images: Optional[int] = 0
    total_recognized: Optional[int] = 0
    total_failed: Optional[int] = 0
    pending_count: Optional[int] = 0
    scanned_waypoints: Optional[int] = 0
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 子节点
    waypoints: List[WaypointResponse] = []

    class Config:
        from_attributes = True


# ── InspectionSession (含 tasks 子节点) ──
class InspectionSessionResponse(BaseModel):
    id: int
    session_code: str
    container_code: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    abnormal_count: Optional[int] = 0
    total_waypoints: Optional[int] = 0
    total_records: Optional[int] = 0
    status: Optional[str] = None
    extra_data: Optional[dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # 子节点
    tasks: List[TaskResponse] = []

    class Config:
        from_attributes = True


# ── InspectionRecord (树叶节点) ──
class InspectionRecordResponse(BaseModel):
    id: int
    record_code: str
    drone_id: Optional[int] = None
    shelf_id: Optional[int] = None
    rfid_tag_id: Optional[int] = None
    task_code: Optional[str] = None
    waypoint_id: Optional[str] = None
    status: Optional[str] = None
    qr_code_data: Optional[str] = None
    rfid_data: Optional[str] = None
    image_path: Optional[str] = None
    detected_qr_codes: Optional[str] = None
    detected_rfid_tags: Optional[str] = None
    drone_position_x: Optional[float] = None
    drone_position_y: Optional[float] = None
    drone_position_z: Optional[float] = None
    is_matched: Optional[bool] = None
    mismatch_reason: Optional[str] = None
    qr_rfid_match: Optional[bool] = None
    cross_validation_json: Optional[str] = None
    abnormal_tags_json: Optional[str] = None
    inspection_time: Optional[datetime] = None
    duration_ms: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Shelf ──
class ShelfResponse(BaseModel):
    id: int
    shelf_code: str
    shelf_name: Optional[str] = None
    zone: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    position_z: Optional[float] = None
    yaw_rad: Optional[float] = None
    arrival_radius_m: Optional[float] = None
    dwell_time_s: Optional[float] = None
    rows: Optional[int] = 1
    columns: Optional[int] = 1
    levels: Optional[int] = 1
    qr_code: Optional[str] = None
    status: Optional[str] = None
    archived_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── RFIDTag ──
class RFIDTagResponse(BaseModel):
    id: int
    tag_id: str
    tag_type: Optional[str] = None
    sku_id: Optional[int] = None
    shelf_id: Optional[int] = None
    goods_name: Optional[str] = None
    goods_quantity: Optional[int] = 0
    last_read_time: Optional[datetime] = None
    last_read_strength: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True



# ── InventoryItem ──
class InventoryItemResponse(BaseModel):
    id: str
    task_id: Optional[str] = None
    waypoint_id: Optional[str] = None
    sku: Optional[str] = None
    expected_sku: Optional[str] = None
    expected_location: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    confidence: Optional[float] = None
    source_qr_data: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
