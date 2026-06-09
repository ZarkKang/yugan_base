from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from ..models.drone import DroneStatus


class DroneBase(BaseModel):
    drone_code: str
    name: str
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    status: DroneStatus = DroneStatus.IDLE
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    max_speed: Optional[float] = None
    max_altitude: Optional[float] = None
    flight_duration: Optional[int] = None
    description: Optional[str] = None
    sku_id: Optional[int] = None


class DroneCreate(DroneBase):
    pass


class DroneUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    status: Optional[DroneStatus] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    max_speed: Optional[float] = None
    max_altitude: Optional[float] = None
    flight_duration: Optional[int] = None
    description: Optional[str] = None
    sku_id: Optional[int] = None
    is_active: Optional[bool] = None


class DroneResponse(DroneBase):
    id: int
    owner_id: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
