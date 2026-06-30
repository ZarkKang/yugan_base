"""
自动化任务调度器 — 定时视频采集、RFID读取、JSON文件回传至基站
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable

from ..db.database import SessionLocal
from ..models.models import AutomatedTask, DroneDevice, CommunicationLog

logger = logging.getLogger(__name__)

BASE_STORAGE_PATH = os.environ.get("DRONE_STORAGE_PATH", "storage/drone_data")
os.makedirs(BASE_STORAGE_PATH, exist_ok=True)


class AutomatedTaskScheduler:
    """自动化任务调度器 — 单例模式"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._task_callbacks: Dict[int, Callable] = {}
        logger.info("[Scheduler] 自动化任务调度器已初始化")

    def start(self):
        """启动调度器"""
        if self._running:
            logger.warning("[Scheduler] 调度器已在运行")
            return

        self._running = True
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            name="automated-task-scheduler",
            daemon=True,
        )
        self._scheduler_thread.start()
        logger.info("[Scheduler] 调度器已启动")

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("[Scheduler] 调度器已停止")

    def _scheduler_loop(self):
        """调度器主循环 — 每秒检查一次待执行任务"""
        while self._running:
            try:
                self._check_and_execute_tasks()
            except Exception as e:
                logger.error(f"[Scheduler] 调度循环异常: {e}", exc_info=True)
            time.sleep(1)

    def _check_and_execute_tasks(self):
        """检查并执行到期的任务"""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            # 查找启用且下次执行时间已到的任务
            tasks = db.query(AutomatedTask).filter(
                AutomatedTask.enabled == True,
                AutomatedTask.next_run_at <= now,
            ).all()

            for task in tasks:
                try:
                    self._execute_task(task, db)
                except Exception as e:
                    logger.error(f"[Scheduler] 任务 {task.id} 执行失败: {e}", exc_info=True)
                    task.last_run_status = "failed"
                    task.next_run_at = _calculate_next_run(task)
                    db.commit()
        finally:
            db.close()

    def _execute_task(self, task: AutomatedTask, db):
        """执行单个自动化任务"""
        logger.info(f"[Scheduler] 开始执行任务: {task.task_name} (ID={task.id}, type={task.task_type})")

        device = db.query(DroneDevice).filter(DroneDevice.id == task.device_id).first()
        if not device:
            logger.error(f"[Scheduler] 任务 {task.id} 关联的设备 {task.device_id} 不存在")
            task.last_run_status = "failed"
            task.next_run_at = _calculate_next_run(task)
            return

        if device.status != "online":
            logger.warning(f"[Scheduler] 设备 {device.id} 离线，跳过任务 {task.id}")
            task.last_run_status = "failed"
            task.next_run_at = _calculate_next_run(task)
            return

        success = True
        results = {}

        if task.task_type in ("video_capture", "both"):
            video_result = _execute_video_capture(task, device, db)
            results["video_capture"] = video_result
            if not video_result.get("success"):
                success = False

        if task.task_type in ("rfid_read", "both"):
            rfid_result = _execute_rfid_read(task, device, db)
            results["rfid_read"] = rfid_result
            if not rfid_result.get("success"):
                success = False

        # 生成综合JSON文件并回传至基站
        if results:
            json_result = _save_and_transfer_json(task, device, results, db)
            results["json_transfer"] = json_result
            if not json_result.get("success"):
                success = False

        # 更新任务状态
        task.last_run_at = datetime.utcnow()
        task.last_run_status = "success" if success else "failed"
        task.run_count = (task.run_count or 0) + 1
        task.next_run_at = _calculate_next_run(task)
        db.commit()

        logger.info(f"[Scheduler] 任务 {task.id} 完成: {'成功' if success else '部分失败'}")


def _execute_video_capture(task: AutomatedTask, device: DroneDevice, db) -> Dict[str, Any]:
    """执行视频采集"""
    logger.info(f"[Scheduler] 视频采集: 设备={device.id}, 时长={task.video_duration}s, 分辨率={task.video_resolution}")

    # 尝试通过HTTP请求触发视频采集
    start_time = datetime.utcnow()
    try:
        from urllib.request import urlopen, Request
        url = f"http://{device.ip_address}:{device.port}/api/video/capture"
        payload = json.dumps({
            "duration": task.video_duration,
            "resolution": task.video_resolution,
        }).encode("utf-8")
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=task.video_duration + 10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        _log_task_communication(db, device.id, "video", "视频采集完成", True)
        return {"success": True, "message": "视频采集完成", "result": result}
    except Exception as e:
        _log_task_communication(db, device.id, "video", f"视频采集失败: {e}", False, str(e))
        return {"success": False, "message": f"视频采集失败: {e}"}


def _execute_rfid_read(task: AutomatedTask, device: DroneDevice, db) -> Dict[str, Any]:
    """执行RFID读取"""
    logger.info(f"[Scheduler] RFID读取: 设备={device.id}, 时长={task.rfid_read_duration}s")

    try:
        from urllib.request import urlopen, Request
        url = f"http://{device.ip_address}:{device.port}/api/rfid/read"
        payload = json.dumps({
            "duration": task.rfid_read_duration,
        }).encode("utf-8")
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=task.rfid_read_duration + 10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        tags = result.get("tags", result.get("rfid_tags", []))
        _log_task_communication(db, device.id, "rfid_json", f"RFID读取完成: {len(tags)} 个标签", True)
        return {
            "success": True,
            "message": f"RFID读取完成: {len(tags)} 个标签",
            "tag_count": len(tags),
            "tags": tags,
        }
    except Exception as e:
        _log_task_communication(db, device.id, "rfid_json", f"RFID读取失败: {e}", False, str(e))
        return {"success": False, "message": f"RFID读取失败: {e}"}


def _save_and_transfer_json(
    task: AutomatedTask,
    device: DroneDevice,
    results: Dict[str, Any],
    db,
) -> Dict[str, Any]:
    """生成JSON文件并保存到基站存储路径"""
    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = task.json_filename_pattern.format(
            device_id=device.id,
            task_id=task.id,
            timestamp=timestamp,
        )
        # 确保目标路径存在
        target_dir = os.path.join(BASE_STORAGE_PATH, task.target_storage_path.strip("/"))
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, filename)

        json_data = {
            "task_id": task.id,
            "task_name": task.task_name,
            "task_type": task.task_type,
            "device_id": device.id,
            "device_name": device.device_name,
            "device_ip": device.ip_address,
            "executed_at": datetime.utcnow().isoformat(),
            "results": results,
            "metadata": {
                "video_duration": task.video_duration if task.task_type in ("video_capture", "both") else None,
                "video_resolution": task.video_resolution if task.task_type in ("video_capture", "both") else None,
                "rfid_read_duration": task.rfid_read_duration if task.task_type in ("rfid_read", "both") else None,
            },
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        file_size = os.path.getsize(filepath)
        _log_task_communication(db, device.id, "json_file", f"JSON已保存: {filename} ({file_size} bytes)", True)

        logger.info(f"[Scheduler] JSON数据已回传至基站: {filepath} ({file_size} bytes)")
        return {
            "success": True,
            "message": "JSON文件已回传至基站",
            "file_path": filepath,
            "file_size": file_size,
            "target_ip": "192.168.1.200",
        }
    except Exception as e:
        _log_task_communication(db, device.id, "json_file", f"JSON保存失败: {e}", False, str(e))
        return {"success": False, "message": f"JSON保存失败: {e}"}


def create_task(
    device_id: int,
    task_name: str,
    task_type: str,
    schedule_type: str,
    schedule_value: str,
    target_storage_path: str,
    video_duration: int = 30,
    video_resolution: str = "1920x1080",
    rfid_read_duration: int = 10,
    json_filename_pattern: str = "drone_{device_id}_{timestamp}.json",
    enabled: bool = True,
    target_shelves: Optional[str] = None,
) -> Dict[str, Any]:
    """创建自动化任务

    Args:
        target_shelves: 目标货架编号JSON列表字符串, 如 '["SHELF-001","SHELF-002"]'
    """
    db = SessionLocal()
    try:
        device = db.query(DroneDevice).filter(DroneDevice.id == device_id).first()
        if not device:
            return {"success": False, "message": f"设备ID {device_id} 不存在"}

        task = AutomatedTask(
            device_id=device_id,
            task_name=task_name,
            task_type=task_type,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            target_storage_path=target_storage_path,
            target_shelves=target_shelves,
            video_duration=video_duration,
            video_resolution=video_resolution,
            rfid_read_duration=rfid_read_duration,
            json_filename_pattern=json_filename_pattern,
            enabled=enabled,
            next_run_at=_calculate_next_run_by_schedule(schedule_type, schedule_value),
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        logger.info(f"[Scheduler] 任务已创建: {task_name} (ID={task.id})")
        return {
            "success": True,
            "message": "自动化任务创建成功",
            "task_id": task.id,
            "task": _task_to_dict(task),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[Scheduler] 创建任务失败: {e}")
        return {"success": False, "message": f"创建失败: {str(e)}"}
    finally:
        db.close()


def list_tasks(device_id: Optional[int] = None) -> Dict[str, Any]:
    """获取任务列表"""
    db = SessionLocal()
    try:
        query = db.query(AutomatedTask)
        if device_id:
            query = query.filter(AutomatedTask.device_id == device_id)
        tasks = query.order_by(AutomatedTask.created_at.desc()).all()
        return {
            "success": True,
            "total": len(tasks),
            "tasks": [_task_to_dict(t) for t in tasks],
        }
    finally:
        db.close()


def update_task(task_id: int, **kwargs) -> Dict[str, Any]:
    """更新任务配置"""
    db = SessionLocal()
    try:
        task = db.query(AutomatedTask).filter(AutomatedTask.id == task_id).first()
        if not task:
            return {"success": False, "message": f"任务ID {task_id} 不存在"}

        updatable = [
            "task_name", "task_type", "schedule_type", "schedule_value",
            "target_storage_path", "target_shelves", "video_duration", "video_resolution",
            "rfid_read_duration", "json_filename_pattern", "enabled",
        ]
        changed = []
        for key in updatable:
            if key in kwargs and kwargs[key] is not None:
                setattr(task, key, kwargs[key])
                changed.append(key)

        if "schedule_type" in changed or "schedule_value" in changed:
            task.next_run_at = _calculate_next_run_by_schedule(
                task.schedule_type, task.schedule_value
            )

        db.commit()
        db.refresh(task)
        return {
            "success": True,
            "message": f"任务已更新 ({', '.join(changed)})",
            "task": _task_to_dict(task),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def delete_task(task_id: int) -> Dict[str, Any]:
    """删除任务"""
    db = SessionLocal()
    try:
        task = db.query(AutomatedTask).filter(AutomatedTask.id == task_id).first()
        if not task:
            return {"success": False, "message": f"任务ID {task_id} 不存在"}
        db.delete(task)
        db.commit()
        return {"success": True, "message": "任务已删除"}
    finally:
        db.close()


def run_task_manually(task_id: int) -> Dict[str, Any]:
    """手动立即执行任务"""
    db = SessionLocal()
    try:
        task = db.query(AutomatedTask).filter(AutomatedTask.id == task_id).first()
        if not task:
            return {"success": False, "message": f"任务ID {task_id} 不存在"}

        device = db.query(DroneDevice).filter(DroneDevice.id == task.device_id).first()
        if not device:
            return {"success": False, "message": "关联设备不存在"}

        scheduler = AutomatedTaskScheduler()
        scheduler._execute_task(task, db)

        return {
            "success": True,
            "message": "任务已执行",
            "task": _task_to_dict(task),
        }
    finally:
        db.close()


def _calculate_next_run(task: AutomatedTask) -> Optional[datetime]:
    """根据任务配置计算下次执行时间"""
    return _calculate_next_run_by_schedule(task.schedule_type, task.schedule_value)


def _parse_target_shelves(raw: Optional[str]) -> List[str]:
    """解析 target_shelves JSON 字符串为列表，容错处理"""
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            return [str(s) for s in parsed]
        if isinstance(parsed, str):
            return [parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _calculate_next_run_by_schedule(schedule_type: str, schedule_value: str) -> Optional[datetime]:
    """根据调度类型和值计算下次执行时间"""
    now = datetime.utcnow()
    try:
        if schedule_type == "interval":
            seconds = int(schedule_value)
            return now + timedelta(seconds=seconds)
        elif schedule_type == "once":
            return datetime.fromisoformat(schedule_value)
        elif schedule_type == "cron":
            # 简单cron解析: 支持 "*/N" 分钟间隔
            if schedule_value.startswith("*/"):
                minutes = int(schedule_value[2:])
                return now + timedelta(minutes=minutes)
            return None
        else:
            return None
    except Exception:
        return None


def _task_to_dict(task: AutomatedTask) -> Dict[str, Any]:
    return {
        "id": task.id,
        "device_id": task.device_id,
        "task_name": task.task_name,
        "task_type": task.task_type,
        "schedule_type": task.schedule_type,
        "schedule_value": task.schedule_value,
        "target_storage_path": task.target_storage_path,
        "target_shelves": _parse_target_shelves(task.target_shelves),
        "video_duration": task.video_duration,
        "video_resolution": task.video_resolution,
        "rfid_read_duration": task.rfid_read_duration,
        "json_filename_pattern": task.json_filename_pattern,
        "enabled": task.enabled,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "last_run_status": task.last_run_status,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "run_count": task.run_count,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def _log_task_communication(
    db,
    device_id: int,
    data_type: str,
    summary: str,
    success: bool,
    error_msg: Optional[str] = None,
):
    """记录任务通信日志"""
    try:
        log = CommunicationLog(
            device_id=device_id,
            log_type="data",
            direction="receive",
            data_type=data_type,
            payload_summary=summary[:500],
            status="success" if success else "failed",
            error_message=error_msg,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"[Scheduler] 记录日志失败: {e}")


# 全局调度器实例
def get_scheduler() -> AutomatedTaskScheduler:
    return AutomatedTaskScheduler()