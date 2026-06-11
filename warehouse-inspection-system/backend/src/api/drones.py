"""
API路由 - 无人机管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..db.database import get_db
from ..schemas.schemas import (
    DroneCreate,
    DroneUpdate,
    DroneResponse,
    APIResponse
)

router = APIRouter(prefix="/drones", tags=["无人机管理"])


@router.post("/", response_model=APIResponse)
def create_drone(drone: DroneCreate, db: Session = Depends(get_db)):
    """注册新无人机"""
    from ..models.models import Drone
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
    from ..models.models import Drone
    query = db.query(Drone)
    if status:
        query = query.filter(Drone.status == status)
    return query.all()


@router.get("/{drone_id}", response_model=DroneResponse)
def get_drone(drone_id: int, db: Session = Depends(get_db)):
    """获取无人机详情"""
    # TODO: 实现查询逻辑
    raise HTTPException(status_code=404, detail="无人机不存在")


@router.patch("/{drone_id}", response_model=APIResponse)
def update_drone(
    drone_id: int,
    update: DroneUpdate,
    db: Session = Depends(get_db)
):
    """更新无人机信息"""
    # TODO: 实现更新逻辑
    return APIResponse(success=True, message="更新成功")


@router.delete("/{drone_id}", response_model=APIResponse)
def delete_drone(drone_id: int, db: Session = Depends(get_db)):
    """删除无人机"""
    # TODO: 实现删除逻辑
    return APIResponse(success=True, message="删除成功")


@router.get("/{drone_id}/position", response_model=APIResponse)
def get_drone_position(drone_id: int, db: Session = Depends(get_db)):
    """获取无人机当前位置"""
    # TODO: 实现位置查询逻辑
    return APIResponse(success=True, message="操作成功", data={
        "x": 0.0,
        "y": 0.0,
        "z": 0.0
    })


@router.post("/{drone_code}/heartbeat", response_model=APIResponse)
def drone_heartbeat(drone_code: str, payload: dict, db: Session = Depends(get_db)):
    """无人机心跳上报"""
    return APIResponse(success=True, message="心跳已接收")
