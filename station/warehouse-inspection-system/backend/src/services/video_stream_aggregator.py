"""
WebSocket 视频流聚合器
=====================
接收无人机通过 WebSocket 推送的 JPEG 帧，聚合为 MP4 视频文件，
会话结束时创建 VideoData 记录并触发 postprocess_video 后处理。

核心类:
  - ClipWriterContext: 航点视频截取上下文
  - DroneStreamSession: 单无人机会话，含帧缓冲 + writer 线程 + 航点标记 + clip 旁路写入
  - VideoStreamAggregator: 单例管理器，管理所有活跃会话

线程模型:
  - WS receive 循环 (async) → push_frame (sync, 线程安全 queue.put)
  - writer_thread (sync, 守护) → 从 frame_buffer 取帧 → cv2.VideoWriter 写入
  - close_session (sync) → join writer_thread → 创建 VideoData → 启动 postprocess 线程
  - clip 旁路: _feed_clips() 在 writer_thread 中同步写入 clip VideoWriter
"""
import math
import os
import cv2
import json
import time
import queue
import uuid
import logging
import threading
from dataclasses import dataclass, field
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
MAX_ACTIVE_CLIPS_PER_SESSION = 1  # 每个 session 最多同时活跃的 clip 数


@dataclass
class ClipWriterContext:
    """航点视频截取上下文 — 每个活跃 clip 持有一个独立 VideoWriter"""
    waypoint_id: str
    writer: cv2.VideoWriter
    output_path: str
    fps: int
    max_frames: int       # = capture_duration_seconds * fps
    frames_written: int = 0
    start_time: Optional[datetime] = None
    expected_sku: Optional[str] = None
    task_code: Optional[str] = None
    drone_id: int = 0
    drone_code: str = ""
    position: Optional[dict] = None
    position_warning: Optional[str] = None


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

        # 航点视频截取：活跃 clip writer（最多 MAX_ACTIVE_CLIPS_PER_SESSION 个）
        self._clip_writers: Dict[str, ClipWriterContext] = {}
        self._clip_lock = threading.Lock()

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

    # ── 航点视频截取 ──────────────────────────────────────────

    def start_clip_capture(
        self,
        waypoint_id: str,
        expected_sku: Optional[str] = None,
        duration_seconds: float = 10.0,
        position: Optional[dict] = None,
        position_warning: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """开始截取 clip — 创建独立 VideoWriter

        Args:
            waypoint_id: 航点 ID
            expected_sku: 预期 SKU
            duration_seconds: 截取时长（秒）
            position: 到达位置
            position_warning: 位置校验警告

        Returns:
            (success, message)
        """
        if self.stop_event.is_set():
            return False, "会话已关闭，无法截取"

        with self._clip_lock:
            if len(self._clip_writers) >= MAX_ACTIVE_CLIPS_PER_SESSION:
                return False, f"当前已有 {len(self._clip_writers)} 个活跃截取，达到上限"
            if waypoint_id in self._clip_writers:
                return False, f"航点 {waypoint_id} 已在截取中"

        # 输出路径: 与主流同目录，文件名含航点 ID
        clip_dir = os.path.dirname(self.output_path)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        clip_filename = f"clip_{waypoint_id}_{ts}.mp4"
        clip_path = os.path.join(clip_dir, clip_filename)

        # VideoWriter 将在首帧到达时创建（与主流同机制）
        # 但这里我们预创建一个占位 context，首帧时初始化 writer
        ctx = ClipWriterContext(
            waypoint_id=waypoint_id,
            writer=None,  # 首帧时创建
            output_path=clip_path,
            fps=self.fps,
            max_frames=int(duration_seconds * self.fps),
            start_time=datetime.utcnow(),
            expected_sku=expected_sku,
            task_code=self.task_code,
            drone_id=self.drone_id,
            drone_code=self.drone_code,
            position=position,
            position_warning=position_warning,
        )

        with self._clip_lock:
            self._clip_writers[waypoint_id] = ctx

        logger.info(
            "[WSVideo] Clip 截取已启动: session=%s waypoint=%s duration=%.1fs max_frames=%d",
            self.session_id, waypoint_id, duration_seconds, ctx.max_frames,
        )
        return True, f"截取已启动，时长 {duration_seconds}s"

    def _feed_clips(self, img: "np.ndarray") -> None:
        """将一帧同步喂给所有活跃 clip writer — 在 _writer_loop 中调用

        首帧时创建 VideoWriter（需要帧尺寸）。
        写满 max_frames 后自动 _finish_clip()。
        """
        finished_keys: List[str] = []

        with self._clip_lock:
            for wp_id, ctx in self._clip_writers.items():
                try:
                    # 首帧 → 创建 VideoWriter
                    if ctx.writer is None:
                        h, w = img.shape[:2]
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        ctx.writer = cv2.VideoWriter(ctx.output_path, fourcc, ctx.fps, (w, h))
                        if not ctx.writer.isOpened():
                            logger.error("[WSVideo] Clip VideoWriter 打开失败: %s", ctx.output_path)
                            finished_keys.append(wp_id)
                            continue
                        logger.info(
                            "[WSVideo] Clip VideoWriter 已创建: %s (%dx%d @%dfps)",
                            ctx.output_path, w, h, ctx.fps,
                        )

                    ctx.writer.write(img)
                    ctx.frames_written += 1

                    # 写满 → 标记完成
                    if ctx.frames_written >= ctx.max_frames:
                        finished_keys.append(wp_id)
                except Exception as e:
                    logger.error("[WSVideo] Clip 写帧异常: wp=%s err=%s", wp_id, e)
                    finished_keys.append(wp_id)

        # 在锁外处理完成的 clip（避免嵌套锁）
        for wp_id in finished_keys:
            self._finish_clip(wp_id)

    def _finish_clip(self, waypoint_id: str) -> None:
        """结束单个 clip: 关闭 writer → 创建 VideoData → 触发后处理"""
        with self._clip_lock:
            ctx = self._clip_writers.pop(waypoint_id, None)
        if ctx is None:
            return

        # 关闭 VideoWriter
        if ctx.writer is not None:
            try:
                ctx.writer.release()
            except Exception:
                pass

        # 无帧写入 → 删除空文件
        if ctx.frames_written == 0:
            logger.warning("[WSVideo] Clip 无帧写入: wp=%s", waypoint_id)
            try:
                if os.path.exists(ctx.output_path):
                    os.remove(ctx.output_path)
            except Exception:
                pass
            return

        logger.info(
            "[WSVideo] Clip 截取完成: wp=%s frames=%d path=%s",
            waypoint_id, ctx.frames_written, ctx.output_path,
        )

        # 创建 VideoData 记录 + 触发后处理
        try:
            file_size = os.path.getsize(ctx.output_path) if os.path.exists(ctx.output_path) else 0
            description_dict = {
                "clip_type": "waypoint_arrival",
                "expected_sku": ctx.expected_sku,
                "position": ctx.position,
                "position_warning": ctx.position_warning,
            }

            db = SessionLocal()
            try:
                video_rec = VideoData(
                    file_name=os.path.basename(ctx.output_path),
                    file_path=ctx.output_path,
                    file_size=file_size,
                    drone_id=ctx.drone_id,
                    task_code=ctx.task_code,
                    waypoint_id=ctx.waypoint_id,  # clip 绑定到具体航点
                    captured_at=ctx.start_time,
                    processing_status="extracting",
                    source="waypoint_clip",
                    stream_session_id=self.session_id,
                    frame_rate_actual=ctx.fps,
                    waypoint_markers=None,
                    description=json.dumps(description_dict, ensure_ascii=False),
                )
                db.add(video_rec)
                db.commit()
                db.refresh(video_rec)
                video_rec_id = video_rec.id
                logger.info(
                    "[WSVideo] Clip VideoData 已创建: id=%s wp=%s frames=%d",
                    video_rec_id, waypoint_id, ctx.frames_written,
                )
            except Exception as e:
                logger.error("[WSVideo] 创建 Clip VideoData 失败: %s", e, exc_info=True)
                return
            finally:
                db.close()

            # 启动后处理线程
            from ..services.video_postprocess import postprocess_video
            t = threading.Thread(
                target=postprocess_video,
                args=(ctx.output_path, video_rec_id),
                kwargs={
                    "task_code": ctx.task_code,
                    "waypoint_id": ctx.waypoint_id,
                    "expected_sku": ctx.expected_sku,
                    "drone_code": ctx.drone_code,
                    "source": "waypoint_clip",
                },
                daemon=True,
            )
            t.start()
            logger.info("[WSVideo] Clip 后处理线程已启动: video_id=%s wp=%s", video_rec_id, waypoint_id)
        except Exception as e:
            logger.error("[WSVideo] Clip 结束处理异常: wp=%s err=%s", waypoint_id, e, exc_info=True)

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

                # 旁路写入活跃 clip writer
                self._feed_clips(img)
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
                    # 旁路写入活跃 clip writer
                    self._feed_clips(img)
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
            for session in self._sessions:
                if session.drone_id == drone_id:
                    session.mark_waypoint(waypoint_id, expected_sku, position)
                    logger.info("[WSVideo] HTTP 触发帧标记: drone_id=%d wp=%s frame=%d",
                                drone_id, waypoint_id, session.frame_count)
                    return True
        return False

    def schedule_clip_capture(
        self,
        drone_id: int,
        waypoint_id: str,
        expected_sku: Optional[str] = None,
        position: Optional[dict] = None,
    ) -> dict:
        """航点到达时调度 clip 截取

        流程:
          1. 读取截取配置（从 DB 或默认值）
          2. 检查总开关 capture_enabled
          3. 位置校验（软验证：超差仅记录警告，不阻断截取）
          4. 查找活跃 WS 会话
          5. 若 capture_delay_seconds > 0，启动延迟定时器
          6. 调用 session.start_clip_capture()

        Returns:
            {"scheduled": bool, "position_warning": str|None, "message": str}
        """
        from ..services.clip_config import get_clip_config
        from ..models.models import Waypoint

        # 1. 读取配置
        db = SessionLocal()
        try:
            config = get_clip_config(db)
        finally:
            db.close()

        # 2. 检查总开关
        if not config.get("waypoint_clip_capture_enabled", True):
            return {"scheduled": False, "position_warning": None, "message": "截取功能已关闭"}

        duration = config.get("waypoint_clip_capture_duration_seconds", 10.0)
        delay = config.get("waypoint_clip_capture_delay_seconds", 0.0)
        tolerance = config.get("waypoint_clip_position_tolerance_meters", 0.2)

        # 3. 位置校验
        position_warning = None
        if position:
            db = SessionLocal()
            try:
                wp = db.query(Waypoint).filter(Waypoint.id == waypoint_id).first()
                if wp and (wp.position_x is not None or wp.position_y is not None or wp.position_z is not None):
                    wp_pos = {"x": wp.position_x or 0, "y": wp.position_y or 0, "z": wp.position_z or 0}
                    dist = math.sqrt(
                        (position.get("x", 0) - wp_pos["x"]) ** 2 +
                        (position.get("y", 0) - wp_pos["y"]) ** 2 +
                        (position.get("z", 0) - wp_pos["z"]) ** 2
                    )
                    if dist > tolerance:
                        position_warning = f"位置偏差 {dist:.2f}m 超过容差 {tolerance}m"
                        logger.warning("[WSVideo] %s (drone=%d wp=%s)", position_warning, drone_id, waypoint_id)
            finally:
                db.close()

        # 4. 查找活跃 WS 会话
        target_session: Optional[DroneStreamSession] = None
        with self._sessions_lock:
            for session in self._sessions:
                if session.drone_id == drone_id:
                    target_session = session
                    break

        if target_session is None:
            return {
                "scheduled": False,
                "position_warning": position_warning,
                "message": "无活跃 WS 视频流会话",
            }

        # 5-6. 启动截取（考虑延迟）
        def _do_capture(session: DroneStreamSession, wp_id: str, sku: Optional[str],
                        dur: float, pos: Optional[dict], warn: Optional[str]):
            if session.stop_event.is_set():
                logger.warning("[WSVideo] 延迟截取取消（会话已关闭）: wp=%s", wp_id)
                return
            ok, msg = session.start_clip_capture(
                waypoint_id=wp_id,
                expected_sku=sku,
                duration_seconds=dur,
                position=pos,
                position_warning=warn,
            )
            if not ok:
                logger.warning("[WSVideo] Clip 截取启动失败: wp=%s reason=%s", wp_id, msg)

        if delay > 0:
            timer = threading.Timer(
                delay,
                _do_capture,
                args=[target_session, waypoint_id, expected_sku, duration, position, position_warning],
            )
            timer.daemon = True
            timer.start()
            logger.info(
                "[WSVideo] Clip 截取已调度（延迟 %.1fs）: drone=%d wp=%s duration=%.1fs",
                delay, drone_id, waypoint_id, duration,
            )
        else:
            _do_capture(target_session, waypoint_id, expected_sku, duration, position, position_warning)

        return {
            "scheduled": True,
            "position_warning": position_warning,
            "message": f"截取已调度，时长 {duration}s" + (f"，延迟 {delay}s" if delay > 0 else ""),
        }

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
