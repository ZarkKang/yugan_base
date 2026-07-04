"""
API路由 - 无人机管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from ..db.database import get_db
from ..schemas.schemas import (
    DroneCreate,
    DroneUpdate,
    DroneResponse,
    APIResponse
)
from ..models.models import Drone, User
from ..services.device_verification import upsert_device_from_heartbeat
from .auth import get_current_user

router = APIRouter(prefix="/drones", tags=["无人机管理"])

# 心跳超时阈值 (秒) — 超过此时间未心跳则视为离线
ONLINE_TIMEOUT_SECONDS = 30
# 无人机自动同步的状态三态 (其余 flying/maintenance/retired 不自动覆盖)
_AUTO_SYNC_STATES = {"idle", "online", "offline"}


@router.post("/", response_model=APIResponse)
def create_drone(drone: DroneCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取无人机列表

    自动检测在线状态：基于 last_seen 字段判断
    - last_seen 在 30 秒内 → online
    - last_seen 超过 30 秒或为空 → offline
    仅对 idle/online/offline 三态自动同步, 不覆盖 flying/maintenance/retired
    """
    query = db.query(Drone)
    if status:
        query = query.filter(Drone.status == status)
    drones = query.all()

    # 自动同步在线状态 (基于 last_seen)
    now = datetime.utcnow()
    threshold = timedelta(seconds=ONLINE_TIMEOUT_SECONDS)
    changed = False
    for d in drones:
        if d.status not in _AUTO_SYNC_STATES:
            continue  # flying/maintenance/retired 不自动覆盖
        if d.last_seen and (now - d.last_seen) < threshold:
            new_status = "online"
        else:
            new_status = "offline"
        if d.status != new_status:
            d.status = new_status
            changed = True
    if changed:
        db.commit()  # expire_on_commit=True 默认开启, 返回时自动刷新属性
    return drones


@router.get("/{drone_id}", response_model=DroneResponse)
def get_drone(drone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取无人机详情"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail="无人机不存在")
    return drone


@router.patch("/{drone_id}", response_model=APIResponse)
def update_drone(
    drone_id: int,
    update: DroneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
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
def delete_drone(drone_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
    # 心跳到达自动维护 DroneDevice 记录 (替代 /device/report 上报)
    try:
        upsert_device_from_heartbeat(db, drone)
    except Exception as e:
        # 设备表维护失败不影响心跳接收
        pass
    # 增强返回: 附带基站状态信息供无人机端被动获取
    return APIResponse(
        success=True,
        message="心跳已接收",
        data={
            "server_time": datetime.utcnow().isoformat(),
            "drone_registered": True,
            "base_status": "online",
        }
    )
