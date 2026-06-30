from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SKUBase(BaseModel):
    sku_code: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    unit: str = "个"


class SKUCreate(SKUBase):
    pass


class SKUUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    is_active: Optional[bool] = None


class SKUResponse(SKUBase):
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
