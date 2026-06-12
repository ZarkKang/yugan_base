from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.drone import Drone, DroneStatus
from ..models.sku import SKU
from ..schemas.drone import DroneCreate, DroneUpdate, DroneResponse

router = APIRouter(prefix="/api/drones", tags=["无人机管理"])


@router.post("/", response_model=DroneResponse)
def create_drone(drone: DroneCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    # 检查无人机编号是否已存在
    existing = db.query(Drone).filter(Drone.drone_code == drone.drone_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="无人机编号已存在")
    
    # 检查SKU是否存在
    if drone.sku_id:
        sku = db.query(SKU).filter(SKU.id == drone.sku_id).first()
        if not sku:
            raise HTTPException(status_code=400, detail="SKU不存在")
    
    db_drone = Drone(**drone.model_dump(), owner_id=current_user.id)
    db.add(db_drone)
    db.commit()
    db.refresh(db_drone)
    return db_drone


@router.get("/", response_model=List[DroneResponse])
def list_drones(
    skip: int = 0,
    limit: int = 100,
    status: Optional[DroneStatus] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(Drone).options(joinedload(Drone.sku))
    if status:
        query = query.filter(Drone.status == status)
    if is_active is not None:
        query = query.filter(Drone.is_active == is_active)
    return query.offset(skip).limit(limit).all()


@router.get("/{drone_id}", response_model=DroneResponse)
def get_drone(drone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    return drone


@router.put("/{drone_id}", response_model=DroneResponse)
def update_drone(drone_id: int, drone_update: DroneUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    
    update_data = drone_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(drone, key, value)
    
    db.commit()
    db.refresh(drone)
    return drone


@router.delete("/{drone_id}")
def delete_drone(drone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    db.delete(drone)
    db.commit()
    return {"message": "无人机已删除"}


@router.post("/{drone_code}/heartbeat")
def drone_heartbeat(
    drone_code: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """无人机心跳上报"""
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    # 更新状态和位置
    if payload.get("status"):
        try:
            drone.status = DroneStatus(payload["status"])
        except ValueError:
            pass
    pos = payload.get("position", {})
    if pos:
        drone.latitude = pos.get("latitude", pos.get("x", drone.latitude))
        drone.longitude = pos.get("longitude", pos.get("y", drone.longitude))
        drone.altitude = pos.get("altitude", pos.get("z", drone.altitude))
    db.commit()
    return {"message": "心跳已接收", "success": True}


@router.get("/{drone_code}/position")
def get_drone_position(
    drone_code: str,
    db: Session = Depends(get_db),
):
    """获取无人机当前位置"""
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    return {
        "success": True,
        "data": {
            "latitude": drone.latitude,
            "longitude": drone.longitude,
            "altitude": drone.altitude,
            "updated_at": drone.updated_at,
        }
    }
