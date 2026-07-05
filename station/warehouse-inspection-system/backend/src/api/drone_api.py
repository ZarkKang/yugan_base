"""
无人机端 API — 统一路由

所有无人机面向基站的接口统一在此模块中定义，
路径注册在 /api/drones prefix 下（无 JWT 认证）。

与 doc/无人机端API大纲.md 对齐。
"""
import json
import logging
from datetime import datetime
from typing import Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from ..db.database import SessionLocal
from ..models.models import Drone, Task, TaskStatus, Waypoint, Shelf, InspectionReport, RFIDData
from ..schemas.schemas import (
    APIResponse,
    DroneHeartbeatRequest,
    TaskProgressRequest,
    TaskCompleteRequest,
    WaypointArriveRequest,
    DroneShelfSyncRequest,
    ShelfSyncResult,
    DroneRfidUploadRequest,
)
from ..services.device_verification import upsert_device_from_heartbeat

logger = logging.getLogger(__name__)

# 主路由：注册 prefix="/api/drones"
router = APIRouter(tags=["无人机端API"])

# 航点列表路由：注册 prefix="/api"（大纲要求 /api/tasks/{task_code}/waypoints）
waypoints_router = APIRouter(tags=["无人机端API"])


# ========== 辅助函数 ==========

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _drone_or_404(db: Session, drone_id: int) -> Drone:
    """按 drone_id(整数PK) 查找无人机，不存在则抛 404"""
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: id={drone_id}")
    return drone


# ========== 心跳与查询 ==========


@router.post("/heartbeat", response_model=APIResponse)
def drone_heartbeat(payload: DroneHeartbeatRequest, db: Session = Depends(_get_db)):
    """
    无人机心跳上报（drone_id 在 body 中，不在路径中）

    更新: status, battery_level, position, last_seen
    额外: 若携带 current_task + task_progress，同步更新 Task 进度
    """
    drone = db.query(Drone).filter(Drone.id == payload.drone_id).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: id={payload.drone_id}")

    # 更新基本状态
    # ★ 状态映射：无人机 running/completed → 基站 flying/idle
    _STATUS_MAP = {"running": "flying", "completed": "idle"}
    if payload.status is not None:
        drone.status = _STATUS_MAP.get(payload.status, payload.status)
    if payload.battery is not None:
        drone.battery_level = payload.battery
    if payload.position:
        drone.last_position_x = payload.position.get("x", drone.last_position_x)
        drone.last_position_y = payload.position.get("y", drone.last_position_y)
        drone.last_position_z = payload.position.get("z", drone.last_position_z)
    # ★ timestamp → last_seen 转换
    if payload.timestamp is not None:
        try:
            drone.last_seen = datetime.fromtimestamp(payload.timestamp)
        except (OSError, ValueError):
            drone.last_seen = datetime.utcnow()
    else:
        drone.last_seen = datetime.utcnow()
    db.commit()

    # 心跳到达自动维护 DroneDevice 记录
    try:
        upsert_device_from_heartbeat(db, drone)
    except Exception as e:
        logger.debug(f"心跳维护 DroneDevice 失败（不影响心跳接收）: {e}")

    # 若携带任务进度，同步更新
    if payload.current_task and payload.task_progress:
        task = db.query(Task).filter(Task.task_code == payload.current_task).first()
        if task:
            scanned = payload.task_progress.get("scanned")
            if scanned is not None:
                task.scanned_waypoints = scanned
            db.commit()

    return APIResponse(
        success=True,
        message="心跳已接收",
        data={
            "drone_status": drone.status,
            "server_time": datetime.utcnow().isoformat(),
        }
    )


@router.get("/lookup", response_model=APIResponse)
def lookup_drone_id(drone_code: str = Query(..., description="无人机编号(业务标识)"),
                    db: Session = Depends(_get_db)):
    """
    drone_code 反查 drone_id（整数 PK）

    无人机启动时调用此接口发现自身数据库 ID，
    后续所有 API 调用使用 drone_id 作为路径参数。
    """
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机未注册: {drone_code}")

    return APIResponse(success=True, message="查询成功", data={
        "drone_id": drone.id,
        "drone_code": drone.drone_code,
        "status": drone.status,
    })


# ========== 任务管理 ==========


@router.get("/{drone_id}/tasks/available", response_model=APIResponse)
def get_available_tasks(drone_id: int, db: Session = Depends(_get_db)):
    """
    获取可执行任务列表

    返回状态为 CREATED 的任务（最多 5 条），按创建时间倒序。
    """
    _drone_or_404(db, drone_id)

    tasks = (
        db.query(Task)
        .filter(Task.status == TaskStatus.CREATED)
        .order_by(Task.created_at.desc())
        .limit(5)
        .all()
    )

    # 批量获取航点计数
    task_codes = [t.task_code for t in tasks]
    wp_counts = {}
    if task_codes:
        wp_rows = (
            db.query(Waypoint.task_id, sa_func.count(Waypoint.id))
            .filter(Waypoint.task_id.in_(task_codes))
            .group_by(Waypoint.task_id)
            .all()
        )
        wp_counts = {row[0]: row[1] for row in wp_rows}

    return APIResponse(success=True, data={
        "tasks": [
            {
                "task_code": t.task_code,
                "task_name": t.task_name,
                "task_type": t.task_type,
                "total_waypoints": wp_counts.get(t.task_code, 0),
                "altitude": t.altitude,
                "speed": t.speed,
                "target_shelves": json.loads(t.target_shelves) if t.target_shelves else [],
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ]
    })


@router.post("/{drone_id}/tasks/{task_code}/accept", response_model=APIResponse)
def accept_task(drone_id: int, task_code: str, db: Session = Depends(_get_db)):
    """
    无人机确认接收任务

    将任务状态从 CREATED/ASSIGNED 更新为 RUNNING，绑定无人机。
    """
    drone = _drone_or_404(db, drone_id)

    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    if task.status not in (TaskStatus.CREATED, TaskStatus.ASSIGNED):
        raise HTTPException(status_code=400, detail=f"任务状态 {task.status} 不可接收")

    task.drone_id = drone.id
    task.status = TaskStatus.RUNNING
    task.start_time = datetime.utcnow()

    # 同步更新无人机状态
    drone.status = "flying"
    db.commit()

    logger.info(f"任务 {task_code} 已分配给 {drone.drone_code}(id={drone_id})")
    return APIResponse(success=True, message="任务已接收，开始巡检", data={
        "task_code": task_code,
        "status": "running",
    })


@router.post("/{drone_id}/tasks/{task_code}/progress", response_model=APIResponse)
def update_task_progress(drone_id: int, task_code: str,
                         payload: TaskProgressRequest,
                         db: Session = Depends(_get_db)):
    """
    上报任务进度

    每完成一个航点后调用。校验任务归属。
    """
    _drone_or_404(db, drone_id)

    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    # 归属校验
    if task.drone_id != drone_id:
        raise HTTPException(status_code=403, detail="任务不属于此无人机")

    if payload.scanned is not None:
        task.scanned_waypoints = payload.scanned
    if payload.normal_count is not None:
        task.total_recognized = (task.total_recognized or 0) + payload.normal_count
    db.commit()

    return APIResponse(success=True, message="进度已更新", data={
        "task_code": task_code,
        "scanned": task.scanned_waypoints or 0,
    })


@router.post("/{drone_id}/tasks/{task_code}/complete", response_model=APIResponse)
def complete_task(drone_id: int, task_code: str,
                  payload: TaskCompleteRequest = None,
                  db: Session = Depends(_get_db)):
    """
    任务完成上报

    标记任务完成 + 自动生成盘点报告。
    """
    drone = _drone_or_404(db, drone_id)

    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    # 归属校验
    if task.drone_id != drone_id:
        raise HTTPException(status_code=403, detail="任务不属于此无人机")

    task.status = TaskStatus.FINISHED
    task.end_time = datetime.utcnow()

    # 同步更新无人机状态
    drone.status = "idle"
    db.commit()

    # 自动生成报告
    try:
        from .inspection import _generate_report_for_task
        _generate_report_for_task(task_code, db)
    except Exception as e:
        logger.warning(f"自动生成报告失败 (任务 {task_code}): {e}")

    return APIResponse(success=True, message="任务已完成", data={
        "task_code": task_code,
        "completed_at": task.end_time.isoformat() if task.end_time else None,
    })


# ========== 航点 ==========


@router.post("/{drone_id}/waypoints/{waypoint_id}/commands/arrive", response_model=APIResponse)
def waypoint_arrive(drone_id: int, waypoint_id: str,
                    payload: WaypointArriveRequest,
                    db: Session = Depends(_get_db)):
    """
    航点到达命令（NEW）

    无人机到达航点时调用，基站:
    1. 更新航点状态为 scanning
    2. 若有活跃 WS 视频流，在视频帧上标记航点位置
    3. 返回航点信息（含 expected_sku, scan_timeout）
    """
    drone = _drone_or_404(db, drone_id)

    # ★ 双重查询：先按 Waypoint.id 查，再按 shelf_code + task_code 查
    # 无人机端 waypoint_id 可能是货柜编号（如 "01-01"），而非 DB 主键（如 "wp_xxx"）
    waypoint = db.query(Waypoint).filter(Waypoint.id == waypoint_id).first()
    if not waypoint and payload.task_code:
        waypoint = db.query(Waypoint).filter(
            Waypoint.shelf_code == waypoint_id,
            Waypoint.task_id == payload.task_code,
        ).first()
    if not waypoint:
        raise HTTPException(status_code=404, detail=f"航点不存在: id或shelf_code={waypoint_id}")

    # 若提供 task_code，校验航点归属
    if payload.task_code and waypoint.task_id != payload.task_code:
        raise HTTPException(status_code=400, detail=f"航点 {waypoint_id} 不属于任务 {payload.task_code}")

    # ★ timestamp → scanned_at 自动转换
    if payload.timestamp and not payload.arrived_at:
        try:
            waypoint.scanned_at = datetime.fromtimestamp(payload.timestamp)
        except (OSError, ValueError):
            waypoint.scanned_at = datetime.utcnow()
    elif payload.arrived_at:
        waypoint.scanned_at = payload.arrived_at

    # ★ 若 payload 缺 position，从 Waypoint 表读取（用于 clip 位置校验）
    position = payload.position
    if not position and waypoint:
        position = {"x": waypoint.position_x or 0, "y": waypoint.position_y or 0, "z": waypoint.position_z or 0}

    # 更新航点状态
    waypoint.status = "scanning"
    if payload.waypoint_index is not None:
        waypoint.sort_order = payload.waypoint_index
    db.commit()

    # 尝试在活跃 WS 视频流中标记帧位置
    ws_marked = False
    clip_result = {"scheduled": False, "position_warning": None, "message": ""}
    try:
        from ..services.video_stream_aggregator import VideoStreamAggregator
        aggregator = VideoStreamAggregator.get_instance()
        ws_marked = aggregator.mark_waypoint_for_drone(
            drone_id=drone_id,
            waypoint_id=waypoint.id,  # 使用 DB 主键而非路径参数
            expected_sku=waypoint.expected_sku,
            position=position,
        )
        # 调度 clip 截取（使用修正后的 position）
        clip_result = aggregator.schedule_clip_capture(
            drone_id=drone_id,
            waypoint_id=waypoint.id,  # 使用 DB 主键而非路径参数
            expected_sku=waypoint.expected_sku,
            position=position,
        )
    except Exception as e:
        logger.debug(f"WS 帧标记/Clip 截取调度失败（不影响航点到达处理）: {e}")

    logger.info(
        f"无人机 {drone.drone_code}(id={drone_id}) 到达航点 {waypoint_id}, "
        f"ws_marked={ws_marked}, clip_scheduled={clip_result.get('scheduled')}"
    )

    return APIResponse(success=True, message="航点到达已确认", data={
        "waypoint_id": waypoint.id,
        "shelf_code": waypoint.shelf_code,
        "waypoint_status": "scanning",
        "expected_sku": waypoint.expected_sku,
        "scan_timeout": 30,
        "ws_frame_marked": ws_marked,
        "clip_scheduled": clip_result.get("scheduled", False),
        "clip_position_warning": clip_result.get("position_warning"),
        "clip_message": clip_result.get("message"),
    })


@waypoints_router.get("/tasks/{task_code}/waypoints", response_model=APIResponse)
def get_task_waypoints(task_code: str, db: Session = Depends(_get_db)):
    """
    获取任务航点列表（按 sort_order 升序）
    """
    task = db.query(Task).filter(Task.task_code == task_code).first()
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_code}")

    waypoints = (
        db.query(Waypoint)
        .filter(Waypoint.task_id == task_code)
        .order_by(Waypoint.sort_order.asc())
        .all()
    )

    return APIResponse(success=True, data={
        "waypoints": [
            {
                "id": wp.id,
                "shelf_code": wp.shelf_code,
                "position": {"x": wp.position_x, "y": wp.position_y, "z": wp.position_z},
                "camera_angle": wp.camera_angle,
                "expected_sku": wp.expected_sku,
                "sort_order": wp.sort_order,
            }
            for wp in waypoints
        ]
    })


# ========== 货架同步 ==========


def _is_heartbeat_payload(payload: DroneShelfSyncRequest) -> bool:
    """检测是否为误路由到 shelves/sync 的心跳数据

    无人机当前配置 heartbeat_path 为 shelves/sync 路径，
    心跳数据特征：shelves 为空 + timestamp 存在。
    正常货架同步一定有 shelves 数据。
    """
    return payload.timestamp is not None and len(payload.shelves) == 0


def _handle_misrouted_heartbeat(drone_id: int, payload: DroneShelfSyncRequest, db: Session):
    """处理误路由到 shelves/sync 的心跳数据"""
    drone = _drone_or_404(db, drone_id)

    # 状态映射
    _STATUS_MAP = {"running": "flying", "completed": "idle"}

    if payload.timestamp:
        try:
            drone.last_seen = datetime.fromtimestamp(payload.timestamp)
        except (OSError, ValueError):
            drone.last_seen = datetime.utcnow()
    else:
        drone.last_seen = datetime.utcnow()

    logger.info(f"心跳数据(兼容路径 shelves/sync): drone={drone.drone_code} id={drone_id}")
    db.commit()

    return APIResponse(success=True, message="心跳已接收(兼容路径)", data={
        "drone_status": drone.status,
        "server_time": datetime.utcnow().isoformat(),
    })


@router.post("/{drone_id}/shelves/sync", response_model=ShelfSyncResult)
def sync_shelves_from_drone(drone_id: int, payload: DroneShelfSyncRequest,
                            db: Session = Depends(_get_db)):
    """
    无人机推送货架数据同步

    同步逻辑:
    - yaml有 + DB无(或已归档) → 新增
    - yaml有 + DB活跃 → 更新
    - DB活跃但yaml无 → 归档(软删除)
    """
    # ★ 心跳数据检测：若 body 含心跳特征字段且 shelves 为空，走心跳逻辑
    # 防止无人机误用心跳数据调用货架同步，导致所有货架被归档
    if _is_heartbeat_payload(payload):
        return _handle_misrouted_heartbeat(drone_id, payload, db)

    _drone_or_404(db, drone_id)

    now = datetime.utcnow()

    # 获取所有活跃货架
    active_shelves = db.query(Shelf).filter(Shelf.archived_at.is_(None)).all()
    active_codes = {s.shelf_code: s for s in active_shelves}

    yaml_codes = set()
    added = 0
    updated = 0
    added_codes = []
    updated_codes = []

    for item in payload.shelves:
        code = item.shelf_id
        yaml_codes.add(code)
        pos = item.position or {}

        existing = active_codes.get(code)
        if existing:
            # 更新
            existing.shelf_name = item.shelf_name or existing.shelf_name
            existing.position_x = float(pos.get("x", 0.0)) if pos else existing.position_x
            existing.position_y = float(pos.get("y", 0.0)) if pos else existing.position_y
            existing.position_z = float(pos.get("z", 0.0)) if pos else existing.position_z
            existing.yaw_rad = item.yaw_rad if item.yaw_rad is not None else existing.yaw_rad
            existing.arrival_radius_m = item.arrival_radius_m if item.arrival_radius_m is not None else existing.arrival_radius_m
            existing.dwell_time_s = item.dwell_time_s if item.dwell_time_s is not None else existing.dwell_time_s
            # 扩展字段
            if item.zone is not None:
                existing.zone = item.zone
            if item.rows is not None and item.rows > 1:
                existing.rows = item.rows
            if item.columns is not None and item.columns > 1:
                existing.columns = item.columns
            if item.levels is not None and item.levels > 1:
                existing.levels = item.levels
            existing.last_synced_at = now
            updated += 1
            updated_codes.append(code)
        else:
            # 新增
            new_shelf = Shelf(
                shelf_code=code,
                shelf_name=item.shelf_name or code,
                zone=item.zone,
                position_x=float(pos.get("x", 0.0)) if pos else None,
                position_y=float(pos.get("y", 0.0)) if pos else None,
                position_z=float(pos.get("z", 0.0)) if pos else None,
                yaw_rad=item.yaw_rad,
                arrival_radius_m=item.arrival_radius_m,
                dwell_time_s=item.dwell_time_s,
                rows=item.rows or 1,
                columns=item.columns or 1,
                levels=item.levels or 1,
                status="normal",
                last_synced_at=now,
            )
            db.add(new_shelf)
            added += 1
            added_codes.append(code)

    # 归档
    archived = 0
    archived_codes = []
    for code, shelf in active_codes.items():
        if code not in yaml_codes:
            shelf.status = "archived"
            shelf.archived_at = now
            archived += 1
            archived_codes.append(code)

    db.commit()

    logger.info(
        "货架同步(drone_id=%d): 新增%d(%s) 更新%d(%s) 归档%d(%s)",
        drone_id, added, added_codes, updated, updated_codes, archived, archived_codes
    )

    return ShelfSyncResult(
        added=added,
        updated=updated,
        archived=archived,
        total=len(payload.shelves),
        details={
            "added_codes": added_codes,
            "updated_codes": updated_codes,
            "archived_codes": archived_codes,
            "synced_at": now.isoformat(),
        }
    )


# ========== RFID 上传 ==========


@router.post("/{drone_id}/rfid/upload", response_model=APIResponse)
def upload_rfid_data(drone_id: int, payload: DroneRfidUploadRequest,
                     db: Session = Depends(_get_db)):
    """
    无人机 RFID 扫描结果上传

    最后一个航点完成时统一上传所有 RFID 数据。
    payload.payload 为 List[dict]，支持多种字段名灵活解析。
    """
    drone = _drone_or_404(db, drone_id)

    # 推断 task_code：优先用 payload，否则从当前运行任务获取
    task_code = payload.task_code
    if not task_code:
        running_task = db.query(Task).filter(
            Task.drone_id == drone_id,
            Task.status == TaskStatus.RUNNING,
        ).first()
        if running_task:
            task_code = running_task.task_code

    detected_at = (
        datetime.fromtimestamp(payload.timestamp) if payload.timestamp
        else datetime.utcnow()
    )

    saved_count = 0
    for item in payload.payload:
        try:
            rec = RFIDData(
                rfid_tag=item.get("rfid_tag") or item.get("epc") or item.get("tag_id", ""),
                tag_type=item.get("tag_type"),
                signal_strength=item.get("signal_strength"),
                latitude=item.get("latitude"),
                longitude=item.get("longitude"),
                altitude=item.get("altitude"),
                drone_id=drone_id,
                task_code=task_code,
                detected_at=detected_at,
            )
            db.add(rec)
            saved_count += 1
        except Exception as e:
            logger.warning(f"RFID 记录写入失败: {e}")

    db.commit()
    logger.info(f"RFID 上传完成: drone={drone.drone_code} task={task_code} count={saved_count}")

    return APIResponse(success=True, message=f"RFID 数据已接收，共 {saved_count} 条", data={
        "drone_id": drone_id,
        "task_code": task_code,
        "saved_count": saved_count,
    })
