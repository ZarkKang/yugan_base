from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ImageDataBase(BaseModel):
    file_name: str
    file_path: str
    file_size: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    drone_id: Optional[int] = None
    captured_at: Optional[datetime] = None
    description: Optional[str] = None


class ImageDataCreate(ImageDataBase):
    pass


class ImageDataUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None


class ImageDataResponse(ImageDataBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
