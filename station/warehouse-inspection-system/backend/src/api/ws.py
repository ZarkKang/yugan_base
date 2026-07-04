"""
WebSocket 实时监控端点 + 事件广播器
================================
- EventBroadcaster: 单例 pub/sub，后台线程(synchronous) 可调用 publish() 推送事件
- /ws/monitor: WebSocket 端点，连接后实时接收事件流
- /api/v1/system/workers: 双 Worker 队列状态验证 (gateway + qr_engine)

事件类型 (event_type):
  - rfid_received      RFID 数据入队
  - qr_classified      QR 分类写入 InventoryItem
  - video_processed    视频抽帧识别完成
  - cross_validation   QR×RFID 交叉校验结果
  - queue_status       队列深度变化
  - task_progress      任务进度更新
"""
import asyncio
import json
import logging
import queue as _queue
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

logger = logging.getLogger(__name__)
router = APIRouter(tags=["实时监控"])


# ── EventBroadcaster 单例 ──────────────────────────────

class EventBroadcaster:
    """
    跨线程事件广播器:
    - 后台 sync 线程调用 publish() (线程安全)
    - async WebSocket 客户端通过 subscribe() 获取事件
    - 使用 asyncio.Queue 缓冲事件 (每个客户端独立队列)
    """
    _instance: "Optional[EventBroadcaster]" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._subscribers: list[asyncio.Queue] = []
        self._sub_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stats = {
            "total_published": 0,
            "by_type": {},
            "last_event_at": None,
        }

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """由 FastAPI startup 设置主事件循环"""
        self._loop = loop

    def publish(self, event_type: str, payload: dict):
        """从任意线程发布事件 (线程安全)"""
        try:
            self._stats["total_published"] += 1
            self._stats["by_type"][event_type] = self._stats["by_type"].get(event_type, 0) + 1
            self._stats["last_event_at"] = datetime.utcnow().isoformat()
        except Exception:
            pass

        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self._sub_lock:
            subs = list(self._subscribers)

        for q in subs:
            try:
                if self._loop and self._loop.is_running():
                    # 跨线程安全投递到 asyncio 队列
                    self._loop.call_soon_threadsafe(q.put_nowait, message)
                else:
                    q.put_nowait(message)
            except Exception:
                # 队列满或已关闭 → 忽略
                pass

    def subscribe(self) -> asyncio.Queue:
        """订阅事件 (maxsize=100, 满则丢弃旧事件)"""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        """取消订阅"""
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def get_stats(self) -> dict:
        """获取广播器统计"""
        with self._sub_lock:
            sub_count = len(self._subscribers)
        return {
            "subscribers": sub_count,
            "stats": dict(self._stats),
        }


def get_broadcaster() -> EventBroadcaster:
    """获取广播器单例"""
    return EventBroadcaster()


# ── WebSocket 端点 ─────────────────────────────────────

@router.websocket("/ws/monitor")
async def ws_monitor(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    实时监控 WebSocket 端点
    支持通过 ?token=<jwt> 鉴权 (与图片/视频下载一致)
    连接后立即推送一条 hello 事件 + 当前 worker 状态
    """
    # 鉴权: 校验 JWT token
    if token:
        try:
            from ..core.security import decode_access_token
            payload = decode_access_token(token)
            if payload is None:
                await websocket.close(code=4401, reason="无效的认证凭证")
                return
        except Exception as e:
            logger.warning(f"[WS] 鉴权异常: {e}")
            await websocket.close(code=4401, reason="鉴权失败")
            return
    # 注: 若无 token，允许匿名连接 (监控大屏场景，可后续收紧)

    await websocket.accept()
    broadcaster = get_broadcaster()
    q = broadcaster.subscribe()

    logger.info(f"[WS] 客户端已连接，订阅者数: {broadcaster.get_stats()['subscribers']}")

    # 推送 hello 事件
    await websocket.send_json({
        "type": "hello",
        "payload": {
            "message": "已连接到实时监控",
            "server_time": datetime.utcnow().isoformat(),
            "workers": _get_workers_status(),
        },
        "timestamp": datetime.utcnow().isoformat(),
    })

    try:
        while True:
            try:
                # 等待事件 (5s 超时 → 发心跳)
                message = await asyncio.wait_for(q.get(), timeout=5.0)
                await websocket.send_json(message)
            except asyncio.TimeoutError:
                # 心跳: 同时附带队列状态
                await websocket.send_json({
                    "type": "heartbeat",
                    "payload": {
                        "workers": _get_workers_status(),
                        "broadcast_stats": broadcaster.get_stats(),
                    },
                    "timestamp": datetime.utcnow().isoformat(),
                })
    except WebSocketDisconnect:
        logger.info("[WS] 客户端断开")
    except Exception as e:
        logger.error(f"[WS] 异常: {e}", exc_info=True)
    finally:
        broadcaster.unsubscribe(q)
        try:
            await websocket.close()
        except Exception:
            pass


# ── Worker 状态查询 ────────────────────────────────────

def get_workers_status() -> dict:
    """获取双 Worker 队列状态 (供 system.py 与 ws.py 共用)"""
    status = {
        "gateway_queue": {"size": -1, "maxsize": -1, "started": False},
        "qr_engine": {"size": -1, "maxsize": -1, "started": False, "workers": 0},
    }

    # gateway 队列
    try:
        from .gateway import _processing_queue, _processor_started
        status["gateway_queue"] = {
            "size": _processing_queue.qsize(),
            "maxsize": _processing_queue.maxsize,
            "started": _processor_started,
        }
    except Exception as e:
        logger.debug(f"[WS] 获取 gateway 队列状态失败: {e}")

    # qr_engine 队列
    try:
        from ..image.qr_worker import get_recognition_engine, _engine_instance
        if _engine_instance is not None:
            engine = get_recognition_engine()
            status["qr_engine"] = {
                "size": engine._queue.qsize(),
                "maxsize": engine._queue.maxsize,
                "started": True,
                "workers": len(engine._threads),
                "running": engine._running,
            }
        else:
            status["qr_engine"] = {"size": 0, "maxsize": 0, "started": False, "workers": 0}
    except Exception as e:
        logger.debug(f"[WS] 获取 qr_engine 状态失败: {e}")

    return status


# 兼容旧名 (ws_monitor 内部使用)
_get_workers_status = get_workers_status
