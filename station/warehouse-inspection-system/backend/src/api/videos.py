"""
API路由 - 视频管理
"""
import os
import uuid
import shutil
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..db.database import get_db
from ..models.models import Drone, Task, User
from ..schemas.schemas import APIResponse
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/videos", tags=["视频管理"])

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
VIDEOS_DIR = os.path.join(STORAGE_ROOT, "videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)


@router.post("/upload", response_model=APIResponse)
async def upload_video(
    video: UploadFile = File(..., description="视频文件 (MP4/AVI)"),
    drone_code: str = Form(..., description="无人机编号"),
    task_code: str = Form(..., description="任务编号"),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    接收无人机上传的视频文件，保存文件 → 写入数据库。

    **curl 测试:**
    ```
    curl -X POST http://localhost:8001/api/v1/videos/upload \
      -F "video=@capture.mp4" \
      -F "drone_code=DRONE001" \
      -F "task_code=TASK001"
    ```
    """
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: {drone_code}")

    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    # 生成唯一 video_id
    video_id = f"vid_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    task_dir = os.path.join(VIDEOS_DIR, task_code, drone_code)
    os.makedirs(task_dir, exist_ok=True)

    ext = os.path.splitext(video.filename)[1] if video.filename else ".mp4"
    safe_filename = f"{video_id}{ext}"
    file_path = os.path.join(task_dir, safe_filename)

    # 保存文件
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
    except Exception as e:
        logger.error(f"保存视频文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    file_size = os.path.getsize(file_path)

    # 写入数据库记录（复用 ImageRecord 表，用不同前缀区分）
    from ..models.models import ImageRecord
    record = ImageRecord(
        id=video_id,
        drone_id=drone.id,
        task_id=task_code,
        file_path=file_path,
        file_name=safe_filename,
        file_size=file_size,
        file_format=ext.lstrip("."),
        status="processed",
        qr_data=description,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()

    logger.info(f"视频已保存: {video_id} ({file_size/1024/1024:.1f}MB) task={task_code}")
    return APIResponse(
        success=True,
        message="视频已接收",
        data={
            "video_id": video_id,
            "file_name": safe_filename,
            "file_size": file_size,
        }
    )


@router.get("/{video_id}", response_model=APIResponse)
async def get_video_info(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取视频元信息"""
    from ..models.models import ImageRecord
    record = db.query(ImageRecord).filter(
        ImageRecord.id == video_id,
        ImageRecord.file_format.in_(["mp4", "avi", "mov", "mkv"])
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")

    return APIResponse(success=True, data={
        "video_id": record.id,
        "task_id": record.task_id,
        "drone_id": record.drone_id,
        "file_name": record.file_name,
        "file_size": record.file_size,
        "file_format": record.file_format,
        "description": record.qr_data,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    })


@router.get("/{video_id}/file")
async def download_video(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """下载视频源文件"""
    from ..models.models import ImageRecord
    record = db.query(ImageRecord).filter(ImageRecord.id == video_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")
    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="源文件已被删除")

    media_types = {"mp4": "video/mp4", "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska"}
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=media_types.get(record.file_format, "application/octet-stream")
    )


@router.get("/task/{task_code}", response_model=APIResponse)
async def list_task_videos(task_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取某任务的所有视频列表"""
    from ..models.models import ImageRecord
    videos = (
        db.query(ImageRecord)
        .filter(
            ImageRecord.task_id == task_code,
            ImageRecord.file_format.in_(["mp4", "avi", "mov", "mkv"])
        )
        .order_by(desc(ImageRecord.created_at))
        .all()
    )
    items = []
    for vid in videos:
        items.append({
            "video_id": vid.id,
            "file_name": vid.file_name,
            "file_size": vid.file_size,
            "file_format": vid.file_format,
            "description": vid.qr_data,
            "created_at": vid.created_at.isoformat() if vid.created_at else None,
        })
    return APIResponse(success=True, data={"total": len(items), "items": items})


@router.delete("/{video_id}", response_model=APIResponse)
async def delete_video(video_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """删除视频"""
    from ..models.models import ImageRecord
    record = db.query(ImageRecord).filter(ImageRecord.id == video_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 删除文件
    if os.path.exists(record.file_path):
        os.remove(record.file_path)

    db.delete(record)
    db.commit()
    return APIResponse(success=True, message="视频已删除")
