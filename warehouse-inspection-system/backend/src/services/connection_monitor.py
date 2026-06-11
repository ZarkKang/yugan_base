"""
连接监控服务 - 实时检测各模块连接状态
  • 图传模块(192.168.1.200) - ping + HTTP探测
  • RFID模块 - 串口检测
  • 基站自身服务 - 端口8080/8000探测
  • 数据库 - PostgreSQL连接检查
  • Redis - 缓存服务检查
"""
import asyncio
import socket
import threading
import time
import logging
from datetime import datetime
from typing import Dict, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConnectionStatus:
    """单个连接状态"""
    name: str                # 模块名称
    connected: bool = False  # 是否在线
    last_check_time: Optional[datetime] = None
    response_time_ms: Optional[float] = None  # 响应延迟
    error_message: Optional[str] = None
    details: dict = field(default_factory=dict)


class ConnectionMonitor:
    """连接状态监控服务"""

    # 需要监控的模块配置
    TARGETS = {
        "video_transmitter": {
            "name": "图传模块",
            "host": "192.168.1.200",
            "port": 80,
            "type": "tcp_http",
            "timeout": 3.0,
            "http_path": "/",
        },
        "backend_api": {
            "name": "后端API",
            "host": "127.0.0.1",
            "port": 8000,
            "type": "tcp",
            "timeout": 2.0,
        },
        "api_gateway": {
            "name": "API网关",
            "host": "127.0.0.1",
            "port": 8080,
            "type": "tcp",
            "timeout": 2.0,
        },
    }

    def __init__(self, check_interval: float = 10.0):
        self._interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._statuses: Dict[str, ConnectionStatus] = {}
        self._lock = threading.Lock()

        # 初始化状态
        for key, cfg in self.TARGETS.items():
            self._statuses[key] = ConnectionStatus(name=cfg["name"])
        self._statuses["rfid"] = ConnectionStatus(name="RFID模块")
        self._statuses["database"] = ConnectionStatus(name="数据库(PostgreSQL)")
        self._statuses["redis"] = ConnectionStatus(name="缓存(Redis)")

        # 回调
        self.on_status_changed: Optional[Callable[[str, ConnectionStatus], None]] = None

    def start(self):
        """启动后台监控线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="conn-monitor",
            daemon=True
        )
        self._thread.start()
        logger.info("[连接监控] 已启动 (间隔 %.0fs)", self._interval)

    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        logger.info("[连接监控] 已停止")

    def _monitor_loop(self):
        while self._running:
            for key, cfg in self.TARGETS.items():
                self._check_target(key, cfg)

            # 检查RFID
            self._check_rfid()
            # 检查数据库
            self._check_database()
            # 检查Redis
            self._check_redis()

            time.sleep(self._interval)

    def _check_target(self, key: str, cfg: dict):
        """检查通用TCP/HTTP目标"""
        host = cfg["host"]
        port = cfg["port"]
        timeout = cfg.get("timeout", 3.0)
        target_type = cfg.get("type", "tcp")
        old_status = self._statuses[key].connected

        start = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex((host, port))
            elapsed_ms = (time.time() - start) * 1000
            sock.close()

            if result == 0:
                # TCP通，若类型为HTTP再探测一层
                http_ok = True
                if target_type == "tcp_http":
                    http_ok = self._http_ping(host, port, cfg.get("http_path", "/"), timeout)

                with self._lock:
                    self._statuses[key] = ConnectionStatus(
                        name=cfg["name"],
                        connected=http_ok,
                        last_check_time=datetime.utcnow(),
                        response_time_ms=round(elapsed_ms, 1),
                        details={"host": host, "port": port, "http_ok": http_ok}
                    )
            else:
                with self._lock:
                    self._statuses[key] = ConnectionStatus(
                        name=cfg["name"],
                        connected=False,
                        last_check_time=datetime.utcnow(),
                        error_message=f"TCP连接失败 (err={result})",
                        details={"host": host, "port": port}
                    )
        except Exception as e:
            with self._lock:
                self._statuses[key] = ConnectionStatus(
                    name=cfg["name"],
                    connected=False,
                    last_check_time=datetime.utcnow(),
                    error_message=str(e),
                    details={"host": host, "port": port}
                )

        new_status = self._statuses[key].connected
        if old_status != new_status and self.on_status_changed:
            try:
                self.on_status_changed(key, self._statuses[key])
            except Exception as e:
                logger.error(f"[连接监控] 回调异常: {e}")

    def _http_ping(self, host: str, port: int, path: str, timeout: float) -> bool:
        """发送简单的HTTP GET请求探测"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            req = f"GET {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n"
            sock.sendall(req.encode())
            data = sock.recv(1024)
            sock.close()
            return b"HTTP/" in data
        except Exception:
            return False

    def _check_rfid(self):
        """检查RFID模块连接状态"""
        old_status = self._statuses["rfid"].connected
        try:
            from ..hardware.rfid_reader import get_rfid_reader
            reader = get_rfid_reader()
            connected = reader.is_connected()
            info = reader.get_connection_info()

            with self._lock:
                self._statuses["rfid"] = ConnectionStatus(
                    name="RFID模块",
                    connected=connected,
                    last_check_time=datetime.utcnow(),
                    details=info
                )
        except Exception as e:
            with self._lock:
                self._statuses["rfid"] = ConnectionStatus(
                    name="RFID模块",
                    connected=False,
                    last_check_time=datetime.utcnow(),
                    error_message=str(e)
                )

        new_status = self._statuses["rfid"].connected
        if old_status != new_status and self.on_status_changed:
            try:
                self.on_status_changed("rfid", self._statuses["rfid"])
            except Exception:
                pass

    def _check_database(self):
        """检查数据库连接"""
        old_status = self._statuses["database"].connected
        try:
            from ..db.database import SessionLocal
            from sqlalchemy import text as sqla_text
            start = time.time()
            db = SessionLocal()
            db.execute(sqla_text("SELECT 1"))
            elapsed_ms = (time.time() - start) * 1000
            db.close()

            with self._lock:
                self._statuses["database"] = ConnectionStatus(
                    name="数据库(PostgreSQL)",
                    connected=True,
                    last_check_time=datetime.utcnow(),
                    response_time_ms=round(elapsed_ms, 1)
                )
        except Exception as e:
            with self._lock:
                self._statuses["database"] = ConnectionStatus(
                    name="数据库(PostgreSQL)",
                    connected=False,
                    last_check_time=datetime.utcnow(),
                    error_message=str(e)
                )

        new_status = self._statuses["database"].connected
        if old_status != new_status and self.on_status_changed:
            try:
                self.on_status_changed("database", self._statuses["database"])
            except Exception:
                pass

    def _check_redis(self):
        """检查Redis连接"""
        old_status = self._statuses["redis"].connected
        try:
            from ..db.redis import get_redis
            r = get_redis()
            start = time.time()
            if r.client is not None:
                r.client.ping()
            elapsed_ms = (time.time() - start) * 1000

            with self._lock:
                self._statuses["redis"] = ConnectionStatus(
                    name="缓存(Redis)",
                    connected=True,
                    last_check_time=datetime.utcnow(),
                    response_time_ms=round(elapsed_ms, 1)
                )
        except Exception as e:
            with self._lock:
                self._statuses["redis"] = ConnectionStatus(
                    name="缓存(Redis)",
                    connected=False,
                    last_check_time=datetime.utcnow(),
                    error_message=str(e)
                )

        new_status = self._statuses["redis"].connected
        if old_status != new_status and self.on_status_changed:
            try:
                self.on_status_changed("redis", self._statuses["redis"])
            except Exception:
                pass

    def get_all_status(self) -> dict:
        """获取所有连接状态"""
        with self._lock:
            result = {}
            for key, status in self._statuses.items():
                result[key] = {
                    "name": status.name,
                    "connected": status.connected,
                    "last_check_time": status.last_check_time.isoformat() if status.last_check_time else None,
                    "response_time_ms": status.response_time_ms,
                    "error_message": status.error_message,
                    "details": status.details,
                }
            return result

    def get_status(self, key: str) -> Optional[ConnectionStatus]:
        """获取单个连接状态"""
        with self._lock:
            return self._statuses.get(key)

    def is_ready(self) -> bool:
        """检查系统是否就绪 (所有核心模块在线)"""
        statuses = self.get_all_status()
        core = ["backend_api", "database"]
        return all(statuses.get(k, {}).get("connected", False) for k in core)

    def check_video_transmitter(self) -> ConnectionStatus:
        """手动检查图传模块 """
        self._check_target("video_transmitter", self.TARGETS["video_transmitter"])
        return self._statuses.get("video_transmitter", ConnectionStatus(name="图传模块"))


# 全局单例
_monitor_instance: Optional[ConnectionMonitor] = None
_monitor_lock = threading.Lock()


def get_connection_monitor() -> ConnectionMonitor:
    """获取全局连接监控单例"""
    global _monitor_instance
    global _monitor_lock
    with _monitor_lock:
        if _monitor_instance is None:
            _monitor_instance = ConnectionMonitor(check_interval=10.0)
            _monitor_instance.start()
        return _monitor_instance