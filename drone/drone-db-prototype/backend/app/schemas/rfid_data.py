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
    detected_at: Optional[datetime] = None
    description: Optional[str] = None


class RFIDDataCreate(RFIDDataBase):
    pass


class RFIDDataUpdate(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    description: Optional[str] = None
    is_valid: Optional[bool] = None


class RFIDDataResponse(RFIDDataBase):
    id: int
    is_valid: bool
    created_at: datetime

    class Config:
        from_attributes = True
