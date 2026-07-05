"""
图像管理路由:
  POST /api/images/upload                无人机上传图像 (multipart/form-data)
  GET  /api/images/{image_id}            获取图像元信息
  GET  /api/images/{image_id}/file       下载图像源文件
  GET  /api/images/{image_id}/result     获取识别结果 (供无人机轮询)
  GET  /api/images/task/{task_id}        某任务的所有图像列表
  POST /api/images/{image_id}/retry      手动触发重新识别
"""
import os
import shutil
import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..db.database import get_db
from ..models.models import Drone, Task, Waypoint, ImageRecord, InventoryItem, User
from ..schemas.schemas import APIResponse
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["图像管理"])

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
IMAGES_DIR = os.path.join(STORAGE_ROOT, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)


@router.post("/upload")
async def upload_image(
    image: UploadFile = File(..., description="图像文件 (JPEG/PNG)"),
    drone_code: str = Form(..., description="无人机编号"),
    task_code: str = Form(..., description="任务编号"),
    waypoint_id: str = Form("", description="航点ID"),
    position_x: float = Form(0.0),
    position_y: float = Form(0.0),
    position_z: float = Form(0.0),
    camera_angle: float = Form(45.0),
    capture_index: int = Form(0, description="同一航点第几张: 0,1,2..."),
    rfid_tags: Optional[str] = Form(None, description='RFID标签JSON: ["TAG001","TAG002"]'),
    db: Session = Depends(get_db),
):
    """
    接收无人机上传的图像，保存文件 → 写入数据库 → 触发异步二维码识别。

    **curl 测试:**
    ```
    curl -X POST http://192.168.1.200:8000/api/v1/api/images/upload \
      -F "image=@capture.jpg" \
      -F "drone_code=DRONE001" \
      -F "task_code=TASK001" \
      -F "waypoint_id=wp_001" \
      -F "position_x=1.5" -F "position_y=2.0" -F "position_z=3.0" \
      -F "capture_index=0"
    ```
    返回: `{"success":true, "image_id":"img_...", "status":"pending", "message":"..."}`
    """
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: {drone_code}")

    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    wp = None
    if waypoint_id:
        wp = db.query(Waypoint).filter(Waypoint.id == waypoint_id).first()
        if not wp:
            raise HTTPException(status_code=404, detail=f"航点不存在: {waypoint_id}")

    # 生成唯一 image_id
    image_id = f"img_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task_dir = os.path.join(IMAGES_DIR, task_code, drone_code)
    os.makedirs(task_dir, exist_ok=True)

    safe_filename = f"{image_id}_{image.filename or 'image.jpg'}"
    file_path = os.path.join(task_dir, safe_filename)

    # 保存文件
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        logger.error(f"保存文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    file_size = os.path.getsize(file_path)

    # 写入数据库
    try:
        record = ImageRecord(
            id=image_id,
            drone_id=drone.id,
            task_id=task_code,
            waypoint_id=waypoint_id if waypoint_id else None,
            file_path=file_path,
            file_name=safe_filename,
            file_size=file_size,
            file_format="jpeg",
            position_x=position_x,
            position_y=position_y,
            position_z=position_z,
            camera_angle=camera_angle,
            capture_index=capture_index,
            rfid_tags=rfid_tags,
            status="pending",
            queued_at=datetime.utcnow(),
            expected_sku=wp.expected_sku if wp else None,
        )
        db.add(record)

        task.pending_count = (task.pending_count or 0) + 1
        task.scanned_waypoints = (task.scanned_waypoints or 0) + 1
        if task.total_images is None:
            task.total_images = 0
        task.total_images += 1

        if wp:
            wp.status = "scanning"

        db.commit()
        logger.info(f"图像已保存: {image_id} ({file_size/1024:.1f}KB) task={task_code}")
    except Exception as e:
        db.rollback()
        if os.path.exists(file_path):
            os.remove(file_path)
        logger.error(f"写入数据库失败: {e}")
        raise HTTPException(status_code=500, detail=f"写入数据库失败: {e}")

    # 触发异步识别
    try:
        from ..image.qr_worker import get_recognition_engine
        engine = get_recognition_engine()
        engine.submit(
            image_id=image_id,
            file_path=file_path,
            expected_sku=wp.expected_sku if wp else None
        )
    except Exception as e:
        logger.warning(f"触发异步识别失败 (将由兜底扫描处理): {e}")

    return APIResponse(
        success=True,
        message="图像已接收，正在后台识别二维码",
        data={
            "image_id": image_id,
            "status": "pending",
            "file_name": safe_filename,
            "file_size": file_size,
        }
    )


@router.get("/{image_id}")
async def get_image_info(image_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取图像元信息（不下载文件）"""
    record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="图像不存在")

    return APIResponse(success=True, data={
        "image_id": record.id,
        "task_id": record.task_id,
        "waypoint_id": record.waypoint_id,
        "drone_id": record.drone_id,
        "file_name": record.file_name,
        "file_size": record.file_size,
        "position": {"x": record.position_x, "y": record.position_y, "z": record.position_z},
        "capture_index": record.capture_index,
        "recognition_status": record.status,
        "qr_data": record.qr_data,
        "confidence": record.confidence,
        "image_quality": record.image_quality_score,
        "decoder_used": record.decoder_used,
        "inventory_status": record.inventory_status,
        "expected_sku": record.expected_sku,
        "inventory_message": record.inventory_message,
        # QR 双图证据路径（2026-07 新增）
        "qr_cropped_path": record.qr_cropped_path,
        "annotated_path": record.annotated_path,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "processed_at": record.processed_at.isoformat() if record.processed_at else None,
        "error_message": record.error_message,
    })


@router.get("/{image_id}/file")
async def download_image(image_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """下载图像源文件（用于前端查看/证据图）"""
    record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="图像不存在")
    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="源文件已被删除或移动")

    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=f"image/{record.file_format or 'jpeg'}"
    )


@router.get("/{image_id}/result")
async def get_recognition_result(image_id: str, db: Session = Depends(get_db)):
    """
    获取二维码识别结果（供无人机轮询）。

    返回示例（识别中）:
        {"success":true, "data":{"status":"processing", "expected_sku":"SKU001", "message":"处理中..."}}

    返回示例（识别成功）:
        {"success":true, "data":{"status":"processed","qr_data":"SKU123456",
         "confidence":0.95,"image_quality":85.0,"decoder_used":"pyzbar",
         "inventory_status":"normal","message":"SKU与预期一致"}}
    """
    record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="图像不存在")

    if record.status in ("pending", "processing"):
        return APIResponse(success=True, data={
            "image_id": record.id,
            "status": record.status,
            "qr_data": None,
            "confidence": 0,
            "image_quality": None,
            "decoder_used": None,
            "inventory_status": None,
            "expected_sku": record.expected_sku,
            "message": "处理中，请继续轮询",
        })

    return APIResponse(success=True, data={
        "image_id": record.id,
        "status": record.status,
        "qr_data": record.qr_data,
        "confidence": record.confidence or 0,
        "image_quality": record.image_quality_score,
        "decoder_used": record.decoder_used,
        "inventory_status": record.inventory_status,
        "expected_sku": record.expected_sku,
        "message": record.inventory_message or "",
    })


@router.get("/task/{task_code}")
async def list_task_images(task_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取某任务的所有图像列表（含识别状态）"""
    images = (
        db.query(ImageRecord)
        .filter(ImageRecord.task_id == task_code)
        .order_by(desc(ImageRecord.created_at))
        .limit(500)
        .all()
    )
    items = []
    for img in images:
        items.append({
            "image_id": img.id,
            "waypoint_id": img.waypoint_id,
            "capture_index": img.capture_index,
            "status": img.status,
            "qr_data": img.qr_data,
            "confidence": img.confidence,
            "inventory_status": img.inventory_status,
            "file_size": img.file_size,
            "error_message": img.error_message,
            "created_at": img.created_at.isoformat() if img.created_at else None,
        })
    return APIResponse(success=True, data={"total": len(items), "items": items})


@router.post("/{image_id}/retry")
async def retry_recognition(image_id: str, db: Session = Depends(get_db)):
    """手动触发重新识别"""
    record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="图像不存在")
    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="源文件不存在")

    record.status = "pending"
    record.queued_at = datetime.utcnow()
    db.commit()

    try:
        from ..image.qr_worker import get_recognition_engine
        engine = get_recognition_engine()
        engine.submit(
            image_id=record.id,
            file_path=record.file_path,
            expected_sku=record.expected_sku
        )
    except Exception as e:
        logger.warning(f"重新触发识别失败: {e}")

    return APIResponse(success=True, message="已重新提交识别任务", data={"image_id": image_id})