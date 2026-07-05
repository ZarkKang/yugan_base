from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class RFIDDataBase(BaseModel):
    rfid_tag: str
    tag_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    signal_strength: Optional[float] = None
    drone_id: Optional[int] = None
    # 巡检关联字段
    task_code: Optional[str] = None
    waypoint_id: Optional[str] = None
    detected_at: Optional[datetime] = None
    description: Optional[str] = None
    is_valid: Optional[bool] = True


class RFIDDataCreate(RFIDDataBase):
    pass


class RFIDDataUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None
    is_valid: Optional[bool] = None
    task_code: Optional[str] = None
    waypoint_id: Optional[str] = None


class RFIDDataResponse(RFIDDataBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
