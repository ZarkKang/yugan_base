"""
看板API - 实时任务进度、库存大盘、识别状态俯览
  GET /api/v1/dashboard/overview       总览数据
  GET /api/v1/dashboard/tasks          任务进度
  GET /api/v1/dashboard/inventory      库存大盘
  GET /api/v1/dashboard/live           实时数据流
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case

from ..db.database import get_db
from ..models.models import (
    Task, Waypoint, ImageRecord, InventoryItem,
    InspectionReport, Drone, TaskStatus
)
from ..schemas.schemas import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["看板"])


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)):
    """总览数据 - 首页顶部卡片数据"""
    total_drones = db.query(Drone).count()
    online_drones = db.query(Drone).filter(Drone.status == "online").count()
    active_tasks = db.query(Task).filter(Task.status == TaskStatus.RUNNING).count()
    total_tasks = db.query(Task).count()

    # 今日数据
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_images = db.query(ImageRecord).filter(ImageRecord.created_at >= today).count()
    today_recognized = (
        db.query(ImageRecord)
        .filter(ImageRecord.created_at >= today, ImageRecord.qr_data.isnot(None))
        .count()
    )
    today_items = db.query(InventoryItem).filter(InventoryItem.created_at >= today).count()

    # 库存异常统计
    abnormal_items = (
        db.query(InventoryItem)
        .filter(InventoryItem.status.in_(["misplaced", "missing", "extra", "duplicate"]))
        .count()
    )

    # 最近报告
    latest_report = (
        db.query(InspectionReport)
        .order_by(desc(InspectionReport.generated_at))
        .first()
    )

    return APIResponse(success=True, data={
        "drones": {"total": total_drones, "online": online_drones},
        "tasks": {"active": active_tasks, "total": total_tasks},
        "today": {
            "images": today_images,
            "recognized": today_recognized,
            "items": today_items,
            "recognition_rate": round(today_recognized / today_images * 100, 1) if today_images > 0 else 0,
        },
        "inventory": {"abnormal_items": abnormal_items},
        "latest_report": {
            "id": latest_report.id if latest_report else None,
            "task_id": latest_report.task_id if latest_report else None,
            "accuracy": latest_report.accuracy if latest_report else None,
            "generated_at": latest_report.generated_at.isoformat() if latest_report and latest_report.generated_at else None,
        } if latest_report else None,
    })


@router.get("/tasks")
def get_tasks_progress(db: Session = Depends(get_db)):
    """任务进度 - 列出活跃任务及其各阶段进度"""
    tasks = (
        db.query(Task)
        .filter(Task.status.in_([TaskStatus.RUNNING, TaskStatus.ASSIGNED]))
        .order_by(desc(Task.updated_at))
        .all()
    )

    # 如果没有运行中的任务，返回最近完成的任务
    if not tasks:
        tasks = (
            db.query(Task)
            .filter(Task.status == TaskStatus.FINISHED)
            .order_by(desc(Task.end_time))
            .limit(5)
            .all()
        )

    items = []
    for t in tasks:
        drone_name = None
        if t.drone_id:
            d = db.query(Drone).filter(Drone.id == t.drone_id).first()
            drone_name = d.drone_name if d else None

        total_wp = db.query(Waypoint).filter(Waypoint.task_id == t.task_code).count()
        scanned_wp = (
            db.query(Waypoint)
            .filter(Waypoint.task_id == t.task_code, Waypoint.status == "completed")
            .count()
        )

        items.append({
            "task_code": t.task_code,
            "task_name": t.task_name,
            "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
            "drone_name": drone_name,
            "waypoints": {"total": total_wp, "scanned": scanned_wp},
            "images": {
                "total": t.total_images or 0,
                "recognized": t.total_recognized or 0,
                "pending": t.pending_count or 0,
                "failed": t.total_failed or 0,
            },
            "progress_percent": round(scanned_wp / total_wp * 100, 1) if total_wp > 0 else 0,
            "start_time": t.start_time.isoformat() if t.start_time else None,
            "task_type": t.task_type,
        })

    return APIResponse(success=True, data={"total": len(items), "items": items})


@router.get("/inventory")
def get_inventory_dashboard(
    status: Optional[str] = Query(None, description="筛选状态: normal/misplaced/missing/extra/duplicate"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """库存大盘 - 查看所有扫描库存"""
    q = db.query(InventoryItem)
    if status:
        q = q.filter(InventoryItem.status == status)

    total = q.count()
    items = (
        q.order_by(desc(InventoryItem.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 统计各状态数量
    status_counts = {}
    for s in ["normal", "misplaced", "missing", "extra", "duplicate"]:
        status_counts[s] = db.query(InventoryItem).filter(InventoryItem.status == s).count()

    result_items = []
    for item in items:
        result_items.append({
            "id": item.id,
            "sku": item.sku,
            "expected_sku": item.expected_sku,
            "expected_location": item.expected_location,
            "status": item.status,
            "message": item.message,
            "confidence": item.confidence,
            "position": {"x": item.position_x, "y": item.position_y, "z": item.position_z},
            "task_id": item.task_id,
            "waypoint_id": item.waypoint_id,
            "image_id": item.image_id,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return APIResponse(success=True, data={
        "total": total,
        "page": page,
        "page_size": page_size,
        "status_counts": status_counts,
        "items": result_items,
    })


@router.get("/live")
def get_live_data(db: Session = Depends(get_db)):
    """实时数据流 - 用于看板实时刷新"""
    # 最近1分钟内的活动
    recent_1m = datetime.utcnow() - timedelta(minutes=1)

    recent_images = (
        db.query(ImageRecord)
        .filter(ImageRecord.created_at >= recent_1m)
        .order_by(desc(ImageRecord.created_at))
        .limit(20)
        .all()
    )

    # 待处理队列
    pending_count = (
        db.query(ImageRecord)
        .filter(ImageRecord.status.in_(["pending", "processing"]))
        .count()
    )

    # 最近识别结果
    recent_recognitions = []
    for img in recent_images:
        recent_recognitions.append({
            "image_id": img.id,
            "task_id": img.task_id,
            "waypoint_id": img.waypoint_id,
            "status": img.status,
            "qr_data": img.qr_data,
            "confidence": img.confidence,
            "inventory_status": img.inventory_status,
            "created_at": img.created_at.isoformat() if img.created_at else None,
            "processed_at": img.processed_at.isoformat() if img.processed_at else None,
        })

    # 识别速率 (最近1分钟)
    recognized_in_1m = sum(1 for i in recent_images if i.qr_data)

    return APIResponse(success=True, data={
        "pending_queue": pending_count,
        "recognition_rate_1m": recognized_in_1m,
        "recent_recognitions": recent_recognitions,
        "timestamp": datetime.utcnow().isoformat(),
    })