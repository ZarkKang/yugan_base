"""
WebSocket 视频流端点
====================
无人机通过此端点实时推送 JPEG 帧流，基站聚合为视频文件并触发后处理。

端点: ws://host:8001/ws/video/{drone_id}

消息协议:
  - binary 帧: JPEG 图像数据（无人机摄像头帧）
  - text 帧:   JSON 控制消息
    {
      "type": "stream_start",     // 开始推流（可关联 task_code）
      "task_code": "TASK001",
      "drone_code": "DRONE001"
    }
    {
      "type": "waypoint_enter",   // 到达航点，标记当前帧位置
      "waypoint_id": "W015",
      "expected_sku": "SKU123",   // 可选
      "position": {"x": 1.5, "y": 2.0, "z": 3.0}  // 可选
    }
    {
      "type": "waypoint_leave",   // 离开航点（可选，仅记录）
      "waypoint_id": "W015"
    }
    {
      "type": "stream_stop"       // 主动停止推流
    }
    {
      "type": "heartbeat"         // 心跳，服务端回 heartbeat_ack
    }
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from ..db.database import SessionLocal
from ..models.models import Drone, Task
from ..services.video_stream_aggregator import VideoStreamAggregator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["视频流 WebSocket"])


@router.websocket("/ws/video/{drone_id}")
async def ws_video_stream(
    websocket: WebSocket,
    drone_id: int,
    task_code: Optional[str] = Query(None, description="任务编号（可选，也可通过 stream_start 消息关联"),
):
    """无人机视频流 WebSocket 端点

    接受 binary (JPEG 帧) + text (JSON 控制) 双模消息，
    会话结束时聚合为视频文件并触发 postprocess_video 后处理。
    """
    # 1. 校验 drone_id 存在性
    db: Session = SessionLocal()
    try:
        drone = db.query(Drone).filter(Drone.id == drone_id).first()
        if not drone:
            await websocket.accept()
            await websocket.close(code=4404, reason=f"无人机不存在: id={drone_id}")
            return
        drone_code = drone.drone_code

        # 若 query 传了 task_code，校验任务存在性
        if task_code:
            task = db.query(Task).filter(Task.task_code == task_code).first()
            if not task:
                await websocket.accept()
                await websocket.close(code=4404, reason=f"任务不存在: {task_code}")
                return
    finally:
        db.close()

    # 2. 接受连接并启动会话
    await websocket.accept()
    aggregator = VideoStreamAggregator.get_instance()
    session = aggregator.start_session(
        drone_code=drone_code,
        drone_id=drone_id,
        task_code=task_code,
    )

    # 推送连接确认
    await websocket.send_json({
        "type": "stream_ready",
        "payload": {
            "session_id": session.session_id,
            "drone_code": drone_code,
            "drone_id": drone_id,
            "task_code": task_code,
            "message": "已连接，可开始推流",
        },
    })

    logger.info(
        "[WSVideo] 连接已建立: drone=%s(id=%d) task=%s session=%s",
        drone_code, drone_id, task_code, session.session_id,
    )

    # 3. 主循环：接收 binary / text 消息
    try:
        while True:
            msg = await websocket.receive()

            if msg["type"] == "websocket.disconnect":
                logger.info("[WSVideo] 客户端断开: drone=%s", drone_code)
                break

            # binary 帧 → 推入帧缓冲
            if "bytes" in msg and msg["bytes"] is not None:
                aggregator.push_frame(session, msg["bytes"])
                continue

            # text 帧 → 解析 JSON 控制消息
            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError as e:
                    logger.warning("[WSVideo] JSON 解析失败: %s (text=%r)", e, msg["text"][:200])
                    continue

                msg_type = data.get("type")
                if msg_type == "stream_start":
                    # 关联 task_code（若 query 已传则忽略，以 query 为准）
                    if not session.task_code and data.get("task_code"):
                        session.task_code = data.get("task_code")
                        logger.info(
                            "[WSVideo] 关联任务: session=%s task=%s",
                            session.session_id, session.task_code,
                        )
                    await websocket.send_json({
                        "type": "stream_start_ack",
                        "payload": {"task_code": session.task_code},
                    })

                elif msg_type == "waypoint_enter":
                    waypoint_id = data.get("waypoint_id")
                    if not waypoint_id:
                        logger.warning("[WSVideo] waypoint_enter 缺少 waypoint_id")
                        continue
                    aggregator.mark_waypoint(
                        session,
                        waypoint_id=waypoint_id,
                        expected_sku=data.get("expected_sku"),
                        position=data.get("position"),
                    )
                    # 调度 clip 截取
                    clip_result = {"scheduled": False, "position_warning": None}
                    try:
                        clip_result = aggregator.schedule_clip_capture(
                            drone_id=session.drone_id,
                            waypoint_id=waypoint_id,
                            expected_sku=data.get("expected_sku"),
                            position=data.get("position"),
                        )
                    except Exception as e:
                        logger.warning("[WSVideo] Clip 截取调度失败: %s", e)
                    await websocket.send_json({
                        "type": "waypoint_marked",
                        "payload": {
                            "waypoint_id": waypoint_id,
                            "frame_index": session.frame_count,
                            "clip_scheduled": clip_result.get("scheduled", False),
                            "clip_position_warning": clip_result.get("position_warning"),
                        },
                    })

                elif msg_type == "waypoint_leave":
                    # 仅记录日志，不做其他处理
                    logger.info(
                        "[WSVideo] waypoint_leave: session=%s waypoint=%s",
                        session.session_id, data.get("waypoint_id"),
                    )

                elif msg_type == "stream_stop":
                    logger.info("[WSVideo] 客户端主动停止: drone=%s", drone_code)
                    break

                elif msg_type == "heartbeat":
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "payload": {
                            "frame_count": session.frame_count,
                            "session_id": session.session_id,
                        },
                    })

                else:
                    logger.warning("[WSVideo] 未知消息类型: %s", msg_type)

    except WebSocketDisconnect:
        logger.info("[WSVideo] WebSocket 断开: drone=%s", drone_code)
    except Exception as e:
        logger.error("[WSVideo] 异常: %s", e, exc_info=True)
    finally:
        # 4. 关闭会话（在独立线程中执行，避免阻塞事件循环）
        if session is not None:
            try:
                _, video_rec_id = await asyncio.to_thread(
                    aggregator.close_session, session
                )
                # 推送会话结束通知（若连接仍可用）
                try:
                    await websocket.send_json({
                        "type": "stream_closed",
                        "payload": {
                            "video_id": video_rec_id,
                            "frame_count": session.frame_count,
                            "markers": len(session.waypoint_markers),
                        },
                    })
                except Exception:
                    pass  # 连接已关闭，忽略
            except Exception as e:
                logger.error("[WSVideo] 关闭会话失败: %s", e, exc_info=True)
            try:
                await websocket.close()
            except Exception:
                pass
