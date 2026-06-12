"""
API路由 - 无人机管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ..db.database import get_db
from ..schemas.schemas import (
    DroneCreate,
    DroneUpdate,
    DroneResponse,
    APIResponse
)
from ..models.models import Drone

router = APIRouter(prefix="/drones", tags=["无人机管理"])


@router.post("/", response_model=APIResponse)
def create_drone(drone: DroneCreate, db: Session = Depends(get_db)):
    """注册新无人机"""
    existing = db.query(Drone).filter(Drone.drone_code == drone.drone_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="无人机编号已存在")
    new_drone = Drone(**drone.model_dump())
    db.add(new_drone)
    db.commit()
    db.refresh(new_drone)
    return APIResponse(success=True, message="创建成功", data={"id": new_drone.id})


@router.get("/", response_model=List[DroneResponse])
def list_drones(
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取无人机列表"""
    query = db.query(Drone)
    if status:
        query = query.filter(Drone.status == status)
    return query.all()


@router.get("/{drone_id}", response_model=DroneResponse)
def get_drone(drone_id: int, db: Session = Depends(get_db)):
    """获取无人机详情"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    return drone


@router.patch("/{drone_id}", response_model=APIResponse)
def update_drone(
    drone_id: int,
    update: DroneUpdate,
    db: Session = Depends(get_db)
):
    """更新无人机信息"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(drone, key, value)
    drone.updated_at = datetime.utcnow()
    db.commit()
    return APIResponse(success=True, message="更新成功")


@router.delete("/{drone_id}", response_model=APIResponse)
def delete_drone(drone_id: int, db: Session = Depends(get_db)):
    """删除无人机"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    db.delete(drone)
    db.commit()
    return APIResponse(success=True, message="删除成功")


@router.get("/{drone_id}/position", response_model=APIResponse)
def get_drone_position(drone_id: int, db: Session = Depends(get_db)):
    """获取无人机当前位置"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    return APIResponse(success=True, message="操作成功", data={
        "x": drone.last_position_x or 0.0,
        "y": drone.last_position_y or 0.0,
        "z": drone.last_position_z or 0.0,
    })


@router.post("/{drone_code}/heartbeat", response_model=APIResponse)
def drone_heartbeat(drone_code: str, payload: dict, db: Session = Depends(get_db)):
    """无人机心跳上报"""
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    # 更新状态
    drone.status = payload.get("status", drone.status)
    drone.battery_level = payload.get("battery", drone.battery_level)
    pos = payload.get("position", {})
    if pos:
        drone.last_position_x = pos.get("x", drone.last_position_x)
        drone.last_position_y = pos.get("y", drone.last_position_y)
        drone.last_position_z = pos.get("z", drone.last_position_z)
    drone.last_seen = datetime.utcnow()
    db.commit()
    return APIResponse(success=True, message="心跳已接收")
