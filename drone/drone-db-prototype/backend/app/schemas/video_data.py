from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class VideoDataBase(BaseModel):
    file_name: str
    file_path: str
    file_size: Optional[int] = None
    duration: Optional[float] = None
    resolution: Optional[str] = None
    frame_rate: Optional[float] = None
    codec: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    drone_id: Optional[int] = None
    # 巡检关联字段
    task_code: Optional[str] = None
    waypoint_id: Optional[str] = None
    captured_at: Optional[datetime] = None
    # 抽帧/识别状态
    frame_extracted: Optional[bool] = False
    frame_count: Optional[int] = 0
    qr_recognized: Optional[bool] = False
    qr_codes_json: Optional[str] = None
    processing_status: Optional[str] = "pending"
    processing_error: Optional[str] = None
    # 元数据
    description: Optional[str] = None


class VideoDataCreate(VideoDataBase):
    pass


class VideoDataUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None
    task_code: Optional[str] = None
    waypoint_id: Optional[str] = None
    processing_status: Optional[str] = None
    processing_error: Optional[str] = None


class VideoDataResponse(VideoDataBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
