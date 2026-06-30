from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.video_data import VideoData
from ..schemas.video_data import VideoDataCreate, VideoDataUpdate, VideoDataResponse

router = APIRouter(prefix="/api/videos", tags=["视频数据"])


@router.post("/", response_model=VideoDataResponse)
async def upload_video(
    file: UploadFile = File(...),
    drone_id: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    altitude: Optional[float] = None,
    description: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    # 保存文件
    import os
    import uuid
    from ..core.config import settings
    
    upload_dir = os.path.join(settings.UPLOAD_DIR, "videos")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".mp4"
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
        file_size = len(content)
    
    # 创建数据库记录
    video_data = VideoData(
        file_name=file.filename or unique_filename,
        file_path=file_path,
        file_size=file_size,
        drone_id=drone_id,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        description=description
    )
    db.add(video_data)
    db.commit()
    db.refresh(video_data)
    return video_data


@router.get("/", response_model=List[VideoDataResponse])
def list_videos(
    skip: int = 0,
    limit: int = 100,
    drone_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(VideoData)
    if drone_id:
        query = query.filter(VideoData.drone_id == drone_id)
    return query.order_by(VideoData.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{video_id}", response_model=VideoDataResponse)
def get_video(video_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    video = db.query(VideoData).filter(VideoData.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    return video


@router.delete("/{video_id}")
def delete_video(video_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    video = db.query(VideoData).filter(VideoData.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在")
    
    # 删除文件
    import os
    if os.path.exists(video.file_path):
        os.remove(video.file_path)
    
    db.delete(video)
    db.commit()
    return {"message": "视频已删除"}
