"""
API路由 - 巡检记录 / 任务管理 / 航点管理 / 报告
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models.models import (
    Drone, Task, Waypoint, ImageRecord,
    InventoryItem, InspectionReport, TaskStatus,
    InspectionRecord, InspectionStatus, Shelf, User,
    InspectionSession, VideoData, RFIDData,
)
from ..schemas.schemas import (
    InspectionRecordCreate, InspectionRecordUpdate,
    InspectionRecordResponse, APIResponse, PaginatedResponse,
    TaskCreate, TaskResponse, TaskUpdate,
)
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(tags=["巡检管理"])


# ========== 巡检记录 CRUD ==========

@router.post("/inspection/records", response_model=APIResponse)
def create_record(record: InspectionRecordCreate, db: Session = Depends(get_db)):
    """创建巡检记录"""
    # 验证无人机
    drone = db.query(Drone).filter(Drone.id == record.drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")

    # 验证货架（如果提供）
    if record.shelf_id:
        shelf = db.query(Shelf).filter(Shelf.id == record.shelf_id).first()
        if not shelf:
            raise HTTPException(status_code=404, detail="货架不存在")

    new_record = InspectionRecord(
        record_code=record.record_code,
        drone_id=record.drone_id,
        shelf_id=record.shelf_id,
        rfid_tag_id=record.rfid_tag_id,
        status=InspectionStatus.PENDING,
        qr_code_data=record.qr_code_data,
        rfid_data=record.rfid_data,
        image_path=record.image_path,
        inspection_time=datetime.utcnow(),
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    return APIResponse(success=True, message="创建成功", data={
        "id": new_record.id,
        "record_code": new_record.record_code,
    })


@router.get("/inspection/records", response_model=PaginatedResponse)
def list_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    drone_id: Optional[int] = None,
    task_code: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取巡检记录列表"""
    query = db.query(InspectionRecord)
    if status:
        query = query.filter(InspectionRecord.status == status)
    if drone_id:
        query = query.filter(InspectionRecord.drone_id == drone_id)
    if task_code:
        query = query.filter(InspectionRecord.record_code.like(f"%{task_code}%"))

    total = query.count()
    records = query.order_by(InspectionRecord.created_at.desc()).offset((page-1)*page_size).limit(page_size).all()

    items = []
    for r in records:
        items.append({
            "id": r.id,
            "record_code": r.record_code,
            "drone_id": r.drone_id,
            "shelf_id": r.shelf_id,
            "status": r.status.value if hasattr(r.status, 'value') else str(r.status),
            "qr_code_data": r.qr_code_data,
            "rfid_data": r.rfid_data,
            "image_path": r.image_path,
            "is_matched": r.is_matched,
            "mismatch_reason": r.mismatch_reason,
            "inspection_time": r.inspection_time.isoformat() if r.inspection_time else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/inspection/records/{record_id}", response_model=InspectionRecordResponse)
def get_record(record_id: int, db: Session = Depends(get_db)):
    """获取巡检记录详情"""
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@router.patch("/inspection/records/{record_id}", response_model=APIResponse)
def update_record(record_id: int, update: InspectionRecordUpdate, db: Session = Depends(get_db)):
    """更新巡检记录"""
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(record, key, value)
    db.commit()
    db.refresh(record)

    return APIResponse(success=True, message="更新成功", data={"id": record.id})


@router.delete("/inspection/records/{record_id}", response_model=APIResponse)
def delete_record(record_id: int, db: Session = Depends(get_db)):
    """删除巡检记录（软删除标记）"""
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    record.status = InspectionStatus.ABNORMAL
    record.mismatch_reason = "已删除"
    db.commit()

    return APIResponse(success=True, message="删除成功（软删除）")


# ========== 任务管理 (基站操作员使用) ==========

@router.post("/inspection/tasks", response_model=APIResponse)
def create_task(task: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    创建巡检任务（基站操作员使用）。

    请求示例:
        {"task_code":"TASK001","task_name":"A区巡检","task_type":"routine",
         "target_shelves":[1,2,3],"altitude":5.0,"speed":2.0}
    """
    t = Task(
        task_code=task.task_code,
        task_name=task.task_name,
        task_type=task.task_type,
        drone_id=task.drone_id,
        altitude=task.altitude,
        speed=task.speed,
        target_shelves=json.dumps(task.target_shelves) if task.target_shelves else None,
        status=TaskStatus.CREATED,
    )
    db.add(t)
    db.commit()
    db.refresh(t)

    logger.info(f"创建任务: {task.task_code} - {task.task_name}")
    return APIResponse(success=True, message="任务创建成功", data={
        "task_code": t.task_code,
        "task_name": t.task_name,
    })


@router.get("/inspection/tasks", response_model=APIResponse)
def list_tasks(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取任务列表"""
    try:
        q = db.query(Task)
        if status:
            try:
                q = q.filter(Task.status == status)
            except Exception:
                q = q.filter(Task.status == status.upper())

        total = q.count()
        tasks = q.order_by(Task.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        # 批量获取 drone_code 映射，避免 N+1 查询
        drone_ids = [t.drone_id for t in tasks if t.drone_id]
        drone_map = {}
        if drone_ids:
            drones = db.query(Drone).filter(Drone.id.in_(drone_ids)).all()
            drone_map = {d.id: d.drone_code for d in drones}

        # 批量获取航点计数
        task_codes = [t.task_code for t in tasks]
        wp_counts = {}
        if task_codes:
            from sqlalchemy import func as sa_func
            wp_rows = (
                db.query(Waypoint.task_id, sa_func.count(Waypoint.id))
                .filter(Waypoint.task_id.in_(task_codes))
                .group_by(Waypoint.task_id)
                .all()
            )
            wp_counts = {row[0]: row[1] for row in wp_rows}

        items = []
        for t in tasks:
            status_str = t.status.value if hasattr(t.status, 'value') else str(t.status)
            drone_code = drone_map.get(t.drone_id) if t.drone_id else None
            items.append({
                "task_code": t.task_code,
                "task_name": t.task_name,
                "task_type": t.task_type,
                "status": status_str,
                "drone_code": drone_code,
                "total_waypoints": wp_counts.get(t.task_code, 0),
                "scanned_waypoints": t.scanned_waypoints or 0,
                "total_images": t.total_images or 0,
                "total_recognized": t.total_recognized or 0,
                "start_time": t.start_time.isoformat() if t.start_time else None,
                "end_time": t.end_time.isoformat() if t.end_time else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })

        return APIResponse(success=True, data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        })
    except Exception as e:
        logger.error(f"获取任务列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@router.get("/inspection/tasks/{task_code}", response_model=APIResponse)
def get_task(task_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取任务详情"""
    try:
        t = db.query(Task).filter(Task.task_code == task_code).first()
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在")

        drone_code = None
        if t.drone_id:
            d = db.query(Drone).filter(Drone.id == t.drone_id).first()
            drone_code = d.drone_code if d else None

        total_waypoints = db.query(Waypoint).filter(Waypoint.task_id == task_code).count()

        return APIResponse(success=True, data={
            "task_code": t.task_code,
            "task_name": t.task_name,
            "task_type": t.task_type,
            "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
            "drone_code": drone_code,
            "altitude": t.altitude,
            "speed": t.speed,
            "total_waypoints": total_waypoints,
            "scanned_waypoints": t.scanned_waypoints or 0,
            "total_images": t.total_images or 0,
            "total_recognized": t.total_recognized or 0,
            "total_failed": t.total_failed or 0,
            "pending_count": t.pending_count or 0,
            "start_time": t.start_time.isoformat() if t.start_time else None,
            "end_time": t.end_time.isoformat() if t.end_time else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务详情失败 (task_code={task_code}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取任务详情失败: {str(e)}")


@router.patch("/inspection/tasks/{task_code}", response_model=APIResponse)
def update_task(task_code: str, update: TaskUpdate, db: Session = Depends(get_db)):
    """更新任务信息"""
    t = db.query(Task).filter(Task.task_code == task_code).first()
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")

    if update.status is not None:
        t.status = update.status
    if update.drone_id is not None:
        t.drone_id = update.drone_id
    if update.session_id is not None:
        t.session_id = update.session_id
    if update.start_time is not None:
        t.start_time = update.start_time
    if update.end_time is not None:
        t.end_time = update.end_time
    db.commit()

    return APIResponse(success=True, message="更新成功")


# ========== 航点管理 ==========

@router.post("/inspection/tasks/{task_code}/waypoints")
def add_waypoints(task_code: str, payload: dict, db: Session = Depends(get_db)):
    """
    为任务批量添加航点。

    请求体:
        {"waypoints": [{"position_x":1.0,"position_y":2.0,"position_z":3.0,
         "expected_sku":"SKU001","expected_location":"A-01-03","camera_angle":45.0,
         "sort_order":1}, ...]}
    """
    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    items = payload.get("waypoints", [])
    added = 0
    for wp_data in items:
        wp = Waypoint(
            task_id=task_code,
            shelf_code=wp_data.get("shelf_code"),
            position_x=wp_data.get("position_x", 0),
            position_y=wp_data.get("position_y", 0),
            position_z=wp_data.get("position_z", 0),
            camera_angle=wp_data.get("camera_angle", 45.0),
            expected_sku=wp_data.get("expected_sku"),
            expected_location=wp_data.get("expected_location"),
            status="pending",
            sort_order=wp_data.get("sort_order", added),
        )
        db.add(wp)
        added += 1

    db.commit()
    return APIResponse(success=True, message=f"已添加 {added} 个航点")


# ========== 报告生成 ==========

@router.post("/inspection/tasks/{task_code}/report")
def generate_report(task_code: str, db: Session = Depends(get_db)):
    """手动/自动生成盘点报告"""
    report = _generate_report_for_task(task_code, db)
    return APIResponse(success=True, message="报告生成成功", data={
        "report_id": report.id,
        "task_code": task_code,
        "accuracy": report.accuracy,
        "normal": report.normal_count,
        "abnormal": sum([report.misplaced_count or 0, report.missing_count or 0,
                         report.extra_count or 0, report.duplicate_count or 0]),
    })


@router.get("/inspection/reports/{report_id}", response_model=APIResponse)
def get_report(report_id: str, db: Session = Depends(get_db)):
    """获取报告详情"""
    r = db.query(InspectionReport).filter(InspectionReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    return APIResponse(success=True, data={
        "report_id": r.id,
        "task_id": r.task_id,
        "total_waypoints": r.total_waypoints,
        "total_images": r.total_images,
        "total_recognized": r.total_recognized,
        "total_failed": r.total_failed,
        "normal_count": r.normal_count,
        "misplaced_count": r.misplaced_count,
        "missing_count": r.missing_count,
        "extra_count": r.extra_count,
        "duplicate_count": r.duplicate_count,
        "accuracy": r.accuracy,
        "details": json.loads(r.details) if r.details else [],
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "generated_by": r.generated_by,
    })


@router.get("/inspection/reports/{report_id}/export")
def export_report(report_id: str, db: Session = Depends(get_db)):
    """导出报告 (JSON格式)"""
    r = db.query(InspectionReport).filter(InspectionReport.id == report_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="报告不存在")

    items = (
        db.query(InventoryItem)
        .filter(InventoryItem.task_id == r.task_id)
        .order_by(InventoryItem.created_at.asc())
        .all()
    )

    return {
        "report_id": r.id,
        "task_id": r.task_id,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "summary": {
            "total": r.total_waypoints,
            "total_images": r.total_images,
            "normal": r.normal_count,
            "misplaced": r.misplaced_count,
            "missing": r.missing_count,
            "extra": r.extra_count,
            "duplicate": r.duplicate_count,
            "accuracy": r.accuracy,
        },
        "details": [
            {
                "sku": item.sku,
                "expected_sku": item.expected_sku,
                "status": item.status,
                "message": item.message,
                "position": {"x": item.position_x, "y": item.position_y, "z": item.position_z},
                "image_id": item.image_id,
                "confidence": item.confidence,
            }
            for item in items
        ]
    }


def _generate_report_for_task(task_code: str, db: Session) -> InspectionReport:
    """内部函数: 根据任务汇总生成报告"""
    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise ValueError(f"任务不存在: {task_code}")

    images = db.query(ImageRecord).filter(ImageRecord.task_id == task_code).all()
    total_images = len(images)
    recognized = [i for i in images if i.qr_data]
    total_recognized = len(recognized)
    total_failed = sum(1 for i in images if i.status == "failed")

    normal_c = sum(1 for i in images if i.inventory_status == "normal")
    misplaced_c = sum(1 for i in images if i.inventory_status == "misplaced")
    missing_c = sum(1 for i in images if i.inventory_status == "missing")
    extra_c = sum(1 for i in images if i.inventory_status == "extra")
    dup_c = sum(1 for i in images if i.inventory_status == "duplicate")

    accuracy = round((normal_c / total_images * 100), 1) if total_images > 0 else 0.0

    details = [
        {
            "sku": i.qr_data,
            "expected_sku": i.expected_sku,
            "status": i.inventory_status,
            "message": i.inventory_message,
            "waypoint_id": i.waypoint_id,
            "image_id": i.id,
        }
        for i in images if i.inventory_status and i.inventory_status != "normal"
    ]

    wp_count = db.query(Waypoint).filter(Waypoint.task_id == task_code).count()

    report = InspectionReport(
        task_id=task_code,
        total_waypoints=wp_count,
        total_images=total_images,
        total_recognized=total_recognized,
        total_failed=total_failed,
        normal_count=normal_c,
        misplaced_count=misplaced_c,
        missing_count=missing_c,
        extra_count=extra_c,
        duplicate_count=dup_c,
        accuracy=accuracy,
        details=json.dumps(details, ensure_ascii=False),
        generated_by="system",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    logger.info(f"报告已生成: {report.id} (任务 {task_code}, 准确率 {accuracy}%)")
    return report


# ========== 巡检历史会话 (树干 → 树枝 → 树叶) ==========

@router.post("/inspection/sessions", response_model=APIResponse)
def create_session(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建巡检历史会话(树干)

    Body: {"container_code": "...", "task_code": "TASK001"(可选)}
    """
    import os as _os
    session = InspectionSession(
        session_code=f"SES_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{_os.urandom(3).hex()}",
        container_code=payload.get("container_code"),
        status="pending",
    )
    if payload.get("task_code"):
        task = db.query(Task).filter(Task.task_code == payload["task_code"]).first()
        if task:
            task.session_id = None  # 会在下面设置
    db.add(session)
    db.commit()
    db.refresh(session)
    if payload.get("task_code"):
        task = db.query(Task).filter(Task.task_code == payload["task_code"]).first()
        if task:
            task.session_id = session.id
            db.commit()
    return APIResponse(success=True, message="会话已创建", data={"session_id": session.id, "session_code": session.session_code})


@router.get("/inspection/sessions", response_model=APIResponse)
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出巡检历史会话(树干列表)"""
    query = db.query(InspectionSession).order_by(InspectionSession.created_at.desc())
    total = query.count()
    sessions = query.offset(offset).limit(limit).all()
    return APIResponse(success=True, data={
        "total": total,
        "items": [
            {
                "id": s.id,
                "session_code": s.session_code,
                "container_code": s.container_code,
                "start_time": s.start_time.isoformat() if s.start_time else None,
                "end_time": s.end_time.isoformat() if s.end_time else None,
                "abnormal_count": s.abnormal_count,
                "total_waypoints": s.total_waypoints,
                "total_records": s.total_records,
                "status": s.status,
                "extra_data": s.extra_data,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sessions
        ],
    })


@router.get("/inspection/sessions/{session_id}", response_model=APIResponse)
def get_session_tree(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取巡检历史会话的完整树形结构

    结构: Session(树干) → Task[](树枝) → {VideoData, RFIDData, InspectionRecord, ImageRecord}(树叶)
    """
    session = db.query(InspectionSession).filter(InspectionSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    tasks = db.query(Task).filter(Task.session_id == session_id).all()
    task_codes = [t.task_code for t in tasks]

    # 批量查询树叶数据
    videos = db.query(VideoData).filter(VideoData.task_code.in_(task_codes)).all() if task_codes else []
    rfids = db.query(RFIDData).filter(RFIDData.task_code.in_(task_codes)).all() if task_codes else []
    records = db.query(InspectionRecord).filter(InspectionRecord.task_code.in_(task_codes)).all() if task_codes else []
    images = db.query(ImageRecord).filter(ImageRecord.task_id.in_(task_codes)).all() if task_codes else []

    # 按 task_code 分组
    videos_by_task = {}
    for v in videos:
        videos_by_task.setdefault(v.task_code, []).append({
            "id": v.id, "file_name": v.file_name, "file_path": v.file_path,
            "file_size": v.file_size, "duration": v.duration,
            "frame_extracted": v.frame_extracted, "frame_count": v.frame_count,
            "qr_recognized": v.qr_recognized,
            "qr_codes": json.loads(v.qr_codes_json) if v.qr_codes_json else [],
            "processing_status": v.processing_status,
            "waypoint_id": v.waypoint_id,
            "captured_at": v.captured_at.isoformat() if v.captured_at else None,
        })
    rfids_by_task = {}
    for r in rfids:
        rfids_by_task.setdefault(r.task_code, []).append({
            "id": r.id, "rfid_tag": r.rfid_tag,
            "signal_strength": r.signal_strength,
            "waypoint_id": r.waypoint_id,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        })
    records_by_task = {}
    for rec in records:
        records_by_task.setdefault(rec.task_code, []).append({
            "id": rec.id, "record_code": rec.record_code,
            "status": rec.status.value if hasattr(rec.status, 'value') else str(rec.status),
            "qr_code_data": rec.qr_code_data,
            "rfid_data": rec.rfid_data,
            "qr_rfid_match": rec.qr_rfid_match,
            "cross_validation": json.loads(rec.cross_validation_json) if rec.cross_validation_json else None,
            "abnormal_tags": json.loads(rec.abnormal_tags_json) if rec.abnormal_tags_json else None,
            "mismatch_reason": rec.mismatch_reason,
            "waypoint_id": rec.waypoint_id,
            "inspection_time": rec.inspection_time.isoformat() if rec.inspection_time else None,
        })
    images_by_task = {}
    for img in images:
        images_by_task.setdefault(img.task_id, []).append({
            "id": img.id, "file_name": img.file_name,
            "qr_data": img.qr_data, "status": img.status,
            "inventory_status": img.inventory_status,
            "waypoint_id": img.waypoint_id,
        })

    # 组装树形结构
    task_tree = []
    for t in tasks:
        task_tree.append({
            "task_code": t.task_code,
            "task_name": t.task_name,
            "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
            "start_time": t.start_time.isoformat() if t.start_time else None,
            "end_time": t.end_time.isoformat() if t.end_time else None,
            "total_records": t.total_records,
            "abnormal_records": t.abnormal_records,
            "leaves": {
                "videos": videos_by_task.get(t.task_code, []),
                "rfid_data": rfids_by_task.get(t.task_code, []),
                "inspection_records": records_by_task.get(t.task_code, []),
                "image_records": images_by_task.get(t.task_code, []),
            },
        })

    return APIResponse(success=True, data={
        "session": {
            "id": session.id,
            "session_code": session.session_code,
            "container_code": session.container_code,
            "start_time": session.start_time.isoformat() if session.start_time else None,
            "end_time": session.end_time.isoformat() if session.end_time else None,
            "abnormal_count": session.abnormal_count,
            "total_waypoints": session.total_waypoints,
            "total_records": session.total_records,
            "status": session.status,
            "extra_data": session.extra_data,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        },
        "tasks": task_tree,
    })
