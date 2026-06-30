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
    captured_at: Optional[datetime] = None
    description: Optional[str] = None


class VideoDataCreate(VideoDataBase):
    pass


class VideoDataUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None


class VideoDataResponse(VideoDataBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True
