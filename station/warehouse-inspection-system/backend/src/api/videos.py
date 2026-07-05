"""
API路由 - 视频管理
"""
import os
import uuid
import json
import shutil
import logging
import threading
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from ..db.database import get_db
from ..models.models import Drone, Task, User, VideoData
from ..schemas.schemas import APIResponse
from .auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/videos", tags=["视频管理"])

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
VIDEOS_DIR = os.path.join(STORAGE_ROOT, "videos")
os.makedirs(VIDEOS_DIR, exist_ok=True)


def _process_video_background(file_path: str, video_rec: VideoData, drone_id: int,
                               drone_code: str, task_code: Optional[str],
                               waypoint_id: Optional[str], description: Optional[str]):
    """后台线程入口: 抽帧 → 分组 → 拼接 → QR识别 → 写库存 → 交叉校验

    实际逻辑由 services.video_postprocess.postprocess_video 承载（与 gateway 共用），
    本函数仅作为线程入口的薄包装，保留原签名以兼容现有调用点。
    """
    from ..services.video_postprocess import postprocess_video
    postprocess_video(
        file_path=file_path,
        video_rec_id=video_rec.id,
        task_code=task_code,
        waypoint_id=waypoint_id,
        expected_sku=None,
        drone_code=drone_code,
        source="upload",
    )


@router.post("/upload", response_model=APIResponse)
async def upload_video(
    video: UploadFile = File(..., description="视频文件 (MP4/AVI)"),
    drone_code: str = Form(..., description="无人机编号"),
    task_code: str = Form(..., description="任务编号"),
    waypoint_id: str = Form("", description="航点ID"),
    description: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    接收无人机上传的视频文件，保存文件 → 写入 VideoData → 后台抽帧+QR识别 → 写巡检记录。

    **curl 测试:**
    ```
    curl -X POST http://192.168.1.200:8001/api/v1/videos/upload \
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

    # 自动关联 InspectionSession：如果 Task 尚无 session，则创建并关联
    from ..models.models import InspectionSession
    if not task.session_id:
        session_code = f"SES_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        session = InspectionSession(
            session_code=session_code,
            start_time=datetime.utcnow(),
            status="running",
            total_waypoints=0,
            total_records=0,
            abnormal_count=0,
        )
        db.add(session)
        db.flush()  # 获取 session.id
        task.session_id = session.id
        db.commit()
        logger.info(f"自动创建巡检会话: {session_code} (task={task_code})")

    # 航点可选校验
    wp_id = waypoint_id.strip() if waypoint_id else None
    if wp_id:
        from ..models.models import Waypoint
        wp = db.query(Waypoint).filter(Waypoint.id == wp_id).first()
        if not wp:
            raise HTTPException(status_code=404, detail=f"航点不存在: {wp_id}")

    # 保存文件
    task_dir = os.path.join(VIDEOS_DIR, task_code, drone_code)
    os.makedirs(task_dir, exist_ok=True)

    ext = os.path.splitext(video.filename)[1] if video.filename else ".mp4"
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_filename = f"vid_{drone_code}_{timestamp_str}{ext}"
    file_path = os.path.join(task_dir, safe_filename)

    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
    except Exception as e:
        logger.error(f"保存视频文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

    file_size = os.path.getsize(file_path)

    # 创建 VideoData 记录（树状结构叶子节点）
    video_rec = VideoData(
        file_name=safe_filename,
        file_path=file_path,
        file_size=file_size,
        drone_id=drone.id,
        task_code=task_code,
        waypoint_id=wp_id,
        captured_at=datetime.utcnow(),
        processing_status="extracting",
        source="upload",
    )
    db.add(video_rec)
    db.commit()
    db.refresh(video_rec)

    logger.info(f"视频已保存: id={video_rec.id} ({file_size/1024/1024:.1f}MB) task={task_code}")

    # 后台线程触发抽帧 + QR识别 + 写库存
    t = threading.Thread(
        target=_process_video_background,
        args=(file_path, video_rec, drone.id, drone_code, task_code, wp_id, description),
        daemon=True,
    )
    t.start()

    return APIResponse(
        success=True,
        message="视频已接收，正在后台抽帧识别二维码",
        data={
            "video_id": video_rec.id,
            "file_name": safe_filename,
            "file_size": file_size,
            "status": "extracting",
        }
    )


@router.get("/{video_id}", response_model=APIResponse)
async def get_video_info(video_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取视频元信息"""
    record = db.query(VideoData).filter(VideoData.id == video_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")

    return APIResponse(success=True, data={
        "video_id": record.id,
        "task_code": record.task_code,
        "drone_id": record.drone_id,
        "file_name": record.file_name,
        "file_size": record.file_size,
        "processing_status": record.processing_status,
        "frame_count": record.frame_count,
        "qr_recognized": record.qr_recognized,
        "qr_codes": json.loads(record.qr_codes_json) if record.qr_codes_json else [],
        "created_at": record.captured_at.isoformat() if record.captured_at else None,
    })


@router.get("/{video_id}/file")
async def download_video(video_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """下载视频源文件"""
    record = db.query(VideoData).filter(VideoData.id == video_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")
    if not os.path.exists(record.file_path):
        raise HTTPException(status_code=404, detail="源文件已被删除")

    media_types = {"mp4": "video/mp4", "avi": "video/x-msvideo", "mov": "video/quicktime", "mkv": "video/x-matroska"}
    ext = os.path.splitext(record.file_name)[1].lstrip(".") if record.file_name else "mp4"
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=media_types.get(ext, "application/octet-stream")
    )


@router.get("/task/{task_code}", response_model=APIResponse)
async def list_task_videos(task_code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取某任务的所有视频列表"""
    videos = (
        db.query(VideoData)
        .filter(VideoData.task_code == task_code)
        .order_by(desc(VideoData.captured_at))
        .all()
    )
    items = []
    for vid in videos:
        items.append({
            "video_id": vid.id,
            "file_name": vid.file_name,
            "file_size": vid.file_size,
            "processing_status": vid.processing_status,
            "frame_count": vid.frame_count,
            "qr_recognized": vid.qr_recognized,
            "qr_codes": json.loads(vid.qr_codes_json) if vid.qr_codes_json else [],
            "created_at": vid.captured_at.isoformat() if vid.captured_at else None,
        })
    return APIResponse(success=True, data={"total": len(items), "items": items})


@router.delete("/{video_id}", response_model=APIResponse)
async def delete_video(video_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """删除视频"""
    record = db.query(VideoData).filter(VideoData.id == video_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="视频不存在")

    # 删除文件
    if os.path.exists(record.file_path):
        os.remove(record.file_path)

    db.delete(record)
    db.commit()
    return APIResponse(success=True, message="视频已删除")
