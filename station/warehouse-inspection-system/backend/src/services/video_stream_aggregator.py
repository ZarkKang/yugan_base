"""
WebSocket 视频流聚合器
=====================
接收无人机通过 WebSocket 推送的 JPEG 帧，聚合为 MP4 视频文件，
会话结束时创建 VideoData 记录并触发 postprocess_video 后处理。

核心类:
  - DroneStreamSession: 单无人机会话，含帧缓冲 + writer 线程 + 航点标记数组
  - VideoStreamAggregator: 单例管理器，管理所有活跃会话

线程模型:
  - WS receive 循环 (async) → push_frame (sync, 线程安全 queue.put)
  - writer_thread (sync, 守护) → 从 frame_buffer 取帧 → cv2.VideoWriter 写入
  - close_session (sync) → join writer_thread → 创建 VideoData → 启动 postprocess 线程
"""
import os
import cv2
import json
import time
import queue
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import numpy as np

from ..db.database import SessionLocal
from ..models.models import VideoData, Drone

logger = logging.getLogger(__name__)

# 存储根目录（与 gateway.py / videos.py 一致）
STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
VIDEOS_DIR = os.path.join(STORAGE_ROOT, "videos")

# 默认参数
DEFAULT_FPS = int(os.environ.get("WS_VIDEO_FPS", "15"))
WRITER_THREAD_JOIN_TIMEOUT = 10.0  # writer_thread join 超时（秒）
MAX_FRAME_BUFFER = 300  # 帧缓冲最大长度（防止内存溢出，约 20s @15fps）


class DroneStreamSession:
    """单无人机的视频流会话

    生命周期：
      start_session() 创建 → push_frame() 多次 → mark_waypoint() 可选 → close_session() 结束
    """

    def __init__(
        self,
        session_id: str,
        drone_code: str,
        drone_id: int,
        task_code: Optional[str],
        output_path: str,
        fps: int = DEFAULT_FPS,
    ):
        self.session_id = session_id
        self.drone_code = drone_code
        self.drone_id = drone_id
        self.task_code = task_code
        self.output_path = output_path
        self.fps = fps

        self.frame_buffer: "queue.Queue[bytes]" = queue.Queue(maxsize=MAX_FRAME_BUFFER)
        self.frame_count = 0
        self.start_time = datetime.utcnow()
        self.last_frame_at: Optional[float] = None

        # 航点标记数组：[{waypoint_id, frame_index, timestamp, expected_sku, position}, ...]
        self.waypoint_markers: List[dict] = []
        self._markers_lock = threading.Lock()

        # writer 线程控制
        self.stop_event = threading.Event()
        self.writer_thread = threading.Thread(
            target=self._writer_loop,
            name=f"ws-video-writer-{drone_code}",
            daemon=True,
        )
        self.writer_thread.start()
        logger.info(
            "[WSVideo] 会话已启动: session=%s drone=%s task=%s output=%s",
            session_id, drone_code, task_code, output_path,
        )

    def push_frame(self, jpeg_bytes: bytes) -> bool:
        """推入一帧 JPEG 数据（线程安全）

        Returns:
            True 成功入队；False 队列满（丢弃该帧）
        """
        try:
            self.frame_buffer.put_nowait(jpeg_bytes)
            self.last_frame_at = time.time()
            return True
        except queue.Full:
            logger.warning("[WSVideo] 帧缓冲已满，丢弃帧 (session=%s)", self.session_id)
            return False

    def mark_waypoint(
        self,
        waypoint_id: str,
        expected_sku: Optional[str] = None,
        position: Optional[dict] = None,
    ) -> None:
        """标记当前帧为航点到达位置（线程安全）

        不切分视频，仅在 waypoint_markers 数组追加一条记录，
        记录当前 frame_count（即下一帧的索引）作为该航点对应的视频帧位置。
        """
        marker = {
            "waypoint_id": waypoint_id,
            "frame_index": self.frame_count,  # 当前已写帧数 = 下一帧索引
            "timestamp": datetime.utcnow().isoformat(),
            "expected_sku": expected_sku,
            "position": position,
        }
        with self._markers_lock:
            self.waypoint_markers.append(marker)
        logger.info(
            "[WSVideo] 航点标记: session=%s waypoint=%s frame_index=%d",
            self.session_id, waypoint_id, marker["frame_index"],
        )

    def _writer_loop(self) -> None:
        """writer 线程主循环：从 frame_buffer 取帧 → cv2.VideoWriter 写入

        - 首帧到达时才创建 VideoWriter（需要知道帧尺寸）
        - 收到 stop_event 后排空剩余帧再退出
        - 任何异常仅记日志，不抛出（守护线程）
        """
        writer: Optional[cv2.VideoWriter] = None
        while True:
            try:
                frame_bytes = self.frame_buffer.get(timeout=1.0)
            except queue.Empty:
                if self.stop_event.is_set():
                    break
                continue

            try:
                img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    logger.warning("[WSVideo] JPEG 解码失败，跳过 (session=%s)", self.session_id)
                    continue

                # 首帧 → 创建 VideoWriter
                if writer is None:
                    h, w = img.shape[:2]
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (w, h))
                    if not writer.isOpened():
                        logger.error("[WSVideo] VideoWriter 打开失败: %s", self.output_path)
                        return
                    logger.info(
                        "[WSVideo] VideoWriter 已创建: %s (%dx%d @%dfps)",
                        self.output_path, w, h, self.fps,
                    )

                writer.write(img)
                self.frame_count += 1
            except Exception as e:
                logger.error("[WSVideo] 写帧异常: %s", e, exc_info=True)

        # 排空剩余帧
        while True:
            try:
                frame_bytes = self.frame_buffer.get_nowait()
            except queue.Empty:
                break
            try:
                img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
                if img is not None and writer is not None:
                    writer.write(img)
                    self.frame_count += 1
            except Exception:
                pass

        if writer is not None:
            writer.release()
        logger.info(
            "[WSVideo] writer 线程结束: session=%s total_frames=%d",
            self.session_id, self.frame_count,
        )


class VideoStreamAggregator:
    """视频流聚合器单例

    管理所有活跃的 DroneStreamSession，提供 start/push/mark/close/shutdown 接口。
    在 FastAPI lifespan 中通过 get_instance() 获取单例，shutdown 时调用 shutdown_all()。
    """

    _instance: "Optional[VideoStreamAggregator]" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._sessions: List[DroneStreamSession] = []
        self._sessions_lock = threading.Lock()
        self._total_frames_received = 0

    @classmethod
    def get_instance(cls) -> "VideoStreamAggregator":
        return cls()

    def start_session(
        self,
        drone_code: str,
        drone_id: int,
        task_code: Optional[str] = None,
        fps: int = DEFAULT_FPS,
    ) -> DroneStreamSession:
        """创建新的视频流会话

        分配输出路径: storage/videos/{task_code|no_task}/{drone_code}/ws_{session_id}.mp4
        """
        session_id = uuid.uuid4().hex[:12]
        task_dir = task_code or "no_task"
        dir_path = os.path.join(VIDEOS_DIR, task_dir, drone_code)
        os.makedirs(dir_path, exist_ok=True)
        output_path = os.path.join(dir_path, f"ws_{session_id}.mp4")

        session = DroneStreamSession(
            session_id=session_id,
            drone_code=drone_code,
            drone_id=drone_id,
            task_code=task_code,
            output_path=output_path,
            fps=fps,
        )
        with self._sessions_lock:
            self._sessions.append(session)
        return session

    def push_frame(self, session: DroneStreamSession, jpeg_bytes: bytes) -> bool:
        """推入一帧（更新全局计数器）"""
        ok = session.push_frame(jpeg_bytes)
        if ok:
            with self._sessions_lock:
                self._total_frames_received += 1
        return ok

    def mark_waypoint(
        self,
        session: DroneStreamSession,
        waypoint_id: str,
        expected_sku: Optional[str] = None,
        position: Optional[dict] = None,
    ) -> None:
        """标记航点帧位置"""
        session.mark_waypoint(waypoint_id, expected_sku, position)

    def close_session(self, session: DroneStreamSession) -> Tuple[str, Optional[int]]:
        """关闭会话：停止 writer 线程 → 创建 VideoData → 触发后处理

        Returns:
            (output_path, video_rec_id) — 若无帧写入，video_rec_id 为 None
        """
        # 1. 通知 writer 线程停止并等待
        session.stop_event.set()
        session.writer_thread.join(timeout=WRITER_THREAD_JOIN_TIMEOUT)
        if session.writer_thread.is_alive():
            logger.warning(
                "[WSVideo] writer 线程 join 超时，强制继续 (session=%s)",
                session.session_id,
            )

        # 2. 从会话列表移除
        with self._sessions_lock:
            if session in self._sessions:
                self._sessions.remove(session)

        # 3. 无帧写入 → 不创建 VideoData，删除空文件
        if session.frame_count == 0:
            logger.warning(
                "[WSVideo] 会话无帧写入，跳过 VideoData 创建 (session=%s)",
                session.session_id,
            )
            try:
                if os.path.exists(session.output_path):
                    os.remove(session.output_path)
            except Exception:
                pass
            return session.output_path, None

        # 4. 创建 VideoData 记录
        video_rec_id: Optional[int] = None
        db = SessionLocal()
        try:
            file_size = os.path.getsize(session.output_path) if os.path.exists(session.output_path) else 0
            video_rec = VideoData(
                file_name=os.path.basename(session.output_path),
                file_path=session.output_path,
                file_size=file_size,
                drone_id=session.drone_id,
                task_code=session.task_code,
                waypoint_id=None,  # WS 流覆盖多个航点，不绑定单一 waypoint_id
                captured_at=session.start_time,
                processing_status="extracting",
                source="ws_stream",
                stream_session_id=session.session_id,
                frame_rate_actual=session.fps,
                waypoint_markers=json.dumps(session.waypoint_markers, ensure_ascii=False) if session.waypoint_markers else None,
            )
            db.add(video_rec)
            db.commit()
            db.refresh(video_rec)
            video_rec_id = video_rec.id
            logger.info(
                "[WSVideo] VideoData 已创建: id=%s frames=%d markers=%d session=%s",
                video_rec_id, session.frame_count, len(session.waypoint_markers), session.session_id,
            )
        except Exception as e:
            logger.error("[WSVideo] 创建 VideoData 失败: %s", e, exc_info=True)
            return session.output_path, None
        finally:
            db.close()

        # 5. 启动后处理线程（不阻塞当前调用）
        try:
            from ..services.video_postprocess import postprocess_video
            t = threading.Thread(
                target=postprocess_video,
                args=(session.output_path, video_rec_id),
                kwargs={
                    "task_code": session.task_code,
                    "waypoint_id": None,
                    "expected_sku": None,
                    "drone_code": session.drone_code,
                    "source": "ws_stream",
                },
                daemon=True,
            )
            t.start()
            logger.info("[WSVideo] 后处理线程已启动: video_id=%s", video_rec_id)
        except Exception as e:
            logger.error("[WSVideo] 启动后处理线程失败: %s", e, exc_info=True)

        return session.output_path, video_rec_id

    def shutdown_all(self) -> None:
        """FastAPI shutdown 时调用：强制关闭所有未关闭的会话"""
        with self._sessions_lock:
            sessions = list(self._sessions)
        if not sessions:
            return
        logger.warning("[WSVideo] 强制关闭 %d 个未关闭会话", len(sessions))
        for session in sessions:
            try:
                self.close_session(session)
            except Exception as e:
                logger.error("[WSVideo] 关闭会话异常: %s", e, exc_info=True)

    def mark_waypoint_for_drone(self, drone_id: int, waypoint_id: str,
                                expected_sku: str = None,
                                position: dict = None) -> bool:
        """
        按 drone_id 查找活跃 WS 会话并标记航点帧（供 HTTP API 调用）。

        当无人机通过 HTTP POST /api/drones/{drone_id}/waypoints/{wp_id}/commands/arrive
        通知航点到达时，若同时有活跃的 WS 视频流，在此会话中标记帧位置。

        Returns:
            True 表示找到活跃会话并标记成功
            False 表示无活跃会话（不影响业务，视频后处理时会补）
        """
        with self._sessions_lock:
            for session in self._sessions.values():
                if session.drone_id == drone_id:
                    session.mark_waypoint(waypoint_id, expected_sku, position)
                    logger.info("[WSVideo] HTTP 触发帧标记: drone_id=%d wp=%s frame=%d",
                                drone_id, waypoint_id, session.frame_count)
                    return True
        return False

    # ── 状态查询（供 ws.get_workers_status 使用）──────────────

    def active_session_count(self) -> int:
        with self._sessions_lock:
            return len(self._sessions)

    def total_frames_received(self) -> int:
        with self._sessions_lock:
            return self._total_frames_received

    def get_status(self) -> dict:
        return {
            "active_sessions": self.active_session_count(),
            "total_frames_received": self.total_frames_received(),
            "started": True,
        }
