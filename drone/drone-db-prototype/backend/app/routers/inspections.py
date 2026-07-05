from datetime import datetime
"""
巡检查询 API — 只读端点

树状结构查询: Session(树干) → Task(树枝) → Waypoint/InspectionRecord(树叶)
写入操作仍由 warehouse 的 gateway 端点负责。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import json

from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.inspection import (
    InspectionSession,
    Task,
    Waypoint,
    InspectionRecord,
    Shelf,
    RFIDTag,
)
from ..models.video_data import VideoData
from ..models.rfid_data import RFIDData
from ..models.inventory_item import InventoryItem
from ..schemas.inspection import (
    InspectionSessionResponse,
    TaskResponse,
    WaypointResponse,
    InspectionRecordResponse,
    ShelfResponse,
    RFIDTagResponse,
    InventoryItemResponse,
)
from ..schemas.video_data import VideoDataResponse
from ..schemas.rfid_data import RFIDDataResponse

router = APIRouter(prefix="/api/inspections", tags=["巡检查询"])


# ── 巡检会话 ──

@router.get("/sessions", response_model=List[InspectionSessionResponse])
def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, description="按状态过滤: pending/running/completed/abnormal"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """巡检会话列表（支持分页、状态过滤）"""
    query = db.query(InspectionSession).filter(InspectionSession.status != "archived")
    if status == "archived":
        query = db.query(InspectionSession).filter(InspectionSession.status == "archived")
    elif status:
        query = query.filter(InspectionSession.status == status)
    return query.order_by(InspectionSession.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/sessions/{session_id}", response_model=InspectionSessionResponse)
def get_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """单个会话详情（含 tasks 树枝）"""
    session = db.query(InspectionSession).filter(InspectionSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="巡检会话不存在")
    return session


@router.get("/sessions/{session_id}/tree")
def get_session_tree(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """完整树状结构（session → tasks → waypoints + records + videos + inventory_items）"""
    session = (
        db.query(InspectionSession)
        .filter(InspectionSession.id == session_id)
        .options(
            joinedload(InspectionSession.tasks)
            .joinedload(Task.waypoints)
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="巡检会话不存在")

    # 获取该 session 下所有 task_code
    task_codes = [t.task_code for t in session.tasks if t.task_code]

    # 获取关联的视频数据
    videos = db.query(VideoData).filter(VideoData.task_code.in_(task_codes)).all() if task_codes else []

    # 获取关联的库存物品
    inventory_items = db.query(InventoryItem).filter(InventoryItem.task_id.in_(task_codes)).all() if task_codes else []

    # 获取关联的巡检记录
    records = db.query(InspectionRecord).filter(InspectionRecord.task_code.in_(task_codes)).all() if task_codes else []

    # 获取关联的RFID数据
    rfid_data = db.query(RFIDData).filter(RFIDData.task_code.in_(task_codes)).all() if task_codes else []

    return {
        "session": {
            "id": session.id,
            "session_code": session.session_code,
            "container_code": session.container_code,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "status": session.status,
            "total_waypoints": session.total_waypoints,
            "total_records": session.total_records,
            "abnormal_count": session.abnormal_count,
            "created_at": session.created_at,
        },
        "tasks": [
            {
                "id": t.id,
                "task_code": t.task_code,
                "task_name": t.task_name,
                "task_type": t.task_type,
                "status": t.status,
                "drone_id": t.drone_id,
                "session_id": t.session_id,
                "waypoints": [
                    {
                        "id": wp.id,
                        "waypoint_id": wp.waypoint_id,
                        "x": wp.x,
                        "y": wp.y,
                        "z": wp.z,
                        "status": wp.status,
                        "reached_at": wp.reached_at,
                    }
                    for wp in t.waypoints
                ],
            }
            for t in session.tasks
        ],
        "videos": [
            {
                "id": v.id,
                "file_name": v.file_name,
                "file_size": v.file_size,
                "task_code": v.task_code,
                "drone_id": v.drone_id,
                "processing_status": v.processing_status,
                "frame_count": v.frame_count,
                "qr_recognized": v.qr_recognized,
                "qr_codes": json.loads(v.qr_codes_json) if v.qr_codes_json else [],
                "captured_at": v.captured_at.isoformat() if v.captured_at else None,
            }
            for v in videos
        ],
        "inventory_items": [
            {
                "id": item.id,
                "sku": item.sku,
                "expected_sku": item.expected_sku,
                "status": item.status,
                "message": item.message,
                "confidence": item.confidence,
                "source_qr_data": item.source_qr_data,
                "task_id": item.task_id,
            }
            for item in inventory_items
        ],
        "records": [
            {
                "id": r.id,
                "record_code": r.record_code,
                "task_code": r.task_code,
                "waypoint_id": r.waypoint_id,
                "drone_id": r.drone_id,
                "status": r.status,
                "qr_rfid_match": r.qr_rfid_match,
                "cross_validation_json": r.cross_validation_json,
                "abnormal_tags_json": r.abnormal_tags_json,
                "inspection_time": r.inspection_time.isoformat() if r.inspection_time else None,
            }
            for r in records
        ],
        "rfid_data": [
            {
                "id": rd.id,
                "rfid_tag": rd.rfid_tag,
                "task_code": rd.task_code,
                "waypoint_id": rd.waypoint_id,
                "drone_id": rd.drone_id,
                "read_at": rd.read_at.isoformat() if rd.read_at else None,
            }
            for rd in rfid_data
        ],
    }

# ── 巡检记录 ──

@router.get("/records", response_model=List[InspectionRecordResponse])
def list_records(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session_id: Optional[int] = Query(None, description="按会话ID过滤"),
    task_code: Optional[str] = Query(None, description="按任务编号过滤"),
    drone_id: Optional[int] = Query(None, description="按无人机ID过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """巡检记录列表（支持 session_id/task_code/drone_id/status 过滤）

    注意: InspectionRecord 通过 task_code 关联到 Task，而 Task 通过 session_id 关联到 Session。
    因此按 session_id 过滤时需先查该 session 下所有 task_code。
    """
    query = db.query(InspectionRecord)

    if session_id:
        # 通过 session → tasks → records 间接过滤
        task_codes = (
            db.query(Task.task_code)
            .filter(Task.session_id == session_id)
            .all()
        )
        task_code_list = [tc[0] for tc in task_codes]
        query = query.filter(InspectionRecord.task_code.in_(task_code_list))

    if task_code:
        query = query.filter(InspectionRecord.task_code == task_code)

    if drone_id:
        query = query.filter(InspectionRecord.drone_id == drone_id)

    if status:
        query = query.filter(InspectionRecord.status == status)

    return query.order_by(InspectionRecord.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/records/{record_id}", response_model=InspectionRecordResponse)
def get_record(
    record_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """单条记录详情"""
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="巡检记录不存在")
    return record


# ── 任务 ──

@router.get("/tasks", response_model=List[TaskResponse])
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session_id: Optional[int] = Query(None, description="按会话ID过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """任务列表（支持会话和状态过滤）"""
    query = db.query(Task)
    if session_id:
        query = query.filter(Task.session_id == session_id)
    if status:
        query = query.filter(Task.status == status)
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """任务详情（含航点子节点）"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


# ── 航点 ──

@router.get("/waypoints", response_model=List[WaypointResponse])
def list_waypoints(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    task_id: Optional[str] = Query(None, description="按任务编号(task_code)过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """航点列表"""
    query = db.query(Waypoint)
    if task_id:
        query = query.filter(Waypoint.task_id == task_id)
    if status:
        query = query.filter(Waypoint.status == status)
    return query.order_by(Waypoint.sort_order.asc(), Waypoint.created_at.asc()).offset(skip).limit(limit).all()


# ── 货架 ──

@router.get("/shelves", response_model=List[ShelfResponse])
def list_shelves(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    include_archived: bool = Query(False, description="是否包含已归档货架"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """货架列表"""
    query = db.query(Shelf)
    if not include_archived:
        query = query.filter(Shelf.archived_at.is_(None))
    return query.order_by(Shelf.created_at.desc()).offset(skip).limit(limit).all()


# ── RFID 标签 ──

@router.get("/rfid-tags", response_model=List[RFIDTagResponse])
def list_rfid_tags(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    shelf_id: Optional[int] = Query(None, description="按货架ID过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """RFID标签列表"""
    query = db.query(RFIDTag)
    if shelf_id:
        query = query.filter(RFIDTag.shelf_id == shelf_id)
    return query.order_by(RFIDTag.created_at.desc()).offset(skip).limit(limit).all()


# ── 视频数据（巡检关联视图） ──

@router.get("/videos", response_model=List[VideoDataResponse])
def list_inspection_videos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    task_code: Optional[str] = Query(None, description="按任务编号过滤"),
    processing_status: Optional[str] = Query(None, description="按处理状态过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """视频数据列表（含巡检关联字段，支持任务和处理状态过滤）"""
    query = db.query(VideoData)
    if task_code:
        query = query.filter(VideoData.task_code == task_code)
    if processing_status:
        query = query.filter(VideoData.processing_status == processing_status)
    return query.order_by(VideoData.created_at.desc()).offset(skip).limit(limit).all()


# ── RFID 数据（巡检关联视图） ──

@router.get("/rfid-data", response_model=List[RFIDDataResponse])
def list_inspection_rfid_data(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    task_code: Optional[str] = Query(None, description="按任务编号过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """RFID数据列表（含巡检关联字段，支持任务过滤）"""
    query = db.query(RFIDData)
    if task_code:
        query = query.filter(RFIDData.task_code == task_code)
    return query.order_by(RFIDData.created_at.desc()).offset(skip).limit(limit).all()



# ── 库存物品 ──

@router.get("/inventory-items", response_model=List[InventoryItemResponse])
def list_inventory_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    task_code: Optional[str] = Query(None, description="按任务编号过滤"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """库存物品列表（QR识别结果，支持任务过滤）"""
    query = db.query(InventoryItem)
    if task_code:
        query = query.filter(InventoryItem.task_id == task_code)
    return query.order_by(InventoryItem.created_at.desc()).offset(skip).limit(limit).all()


@router.put("/sessions/{session_id}/archive")
def archive_session(session_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_active_user)):
    """归档巡检会话（软删除，默认查询不显示）"""
    session = db.query(InspectionSession).filter(InspectionSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="巡检会话不存在")
    session.status = "archived"
    session.end_time = session.end_time or datetime.utcnow()
    db.commit()
    db.refresh(session)
    return {"success": True, "message": "会话已归档", "data": {"id": session.id, "session_code": session.session_code, "status": session.status}}


@router.put("/sessions/{session_id}/unarchive")
def unarchive_session(session_id: int, db: Session = Depends(get_db), current_user = Depends(get_current_active_user)):
    """取消归档巡检会话"""
    session = db.query(InspectionSession).filter(InspectionSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="巡检会话不存在")
    session.status = "completed"
    db.commit()
    db.refresh(session)
    return {"success": True, "message": "会话已取消归档", "data": {"id": session.id, "session_code": session.session_code, "status": session.status}}


@router.put("/sessions/batch-archive")
def batch_archive_sessions(session_ids: list[int] = None, db: Session = Depends(get_db), current_user = Depends(get_current_active_user)):
    """批量归档巡检会话"""
    if not session_ids:
        # 归档所有非归档会话
        sessions = db.query(InspectionSession).filter(InspectionSession.status != "archived").all()
    else:
        sessions = db.query(InspectionSession).filter(InspectionSession.id.in_(session_ids)).all()
    count = 0
    for s in sessions:
        s.status = "archived"
        s.end_time = s.end_time or datetime.utcnow()
        count += 1
    db.commit()
    return {"success": True, "message": f"已归档 {count} 个会话", "data": {"archived_count": count}}
