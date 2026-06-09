"""
硬件通信模块 - 以太网通信
"""
import socket
import threading
from typing import Optional, Callable
from dataclasses import dataclass
import logging
import asyncio

logger = logging.getLogger(__name__)


@dataclass
class EthernetConfig:
    host: str = "192.168.1.100"
    port: int = 8080
    timeout: float = 30.0
    buffer_size: int = 4096


class EthernetComm:
    """以太网通信类"""

    def __init__(self, config: Optional[EthernetConfig] = None):
        self.config = config or EthernetConfig()
        self.sock: Optional[socket.socket] = None
        self._connected = False
        self._receive_thread: Optional[threading.Thread] = None
        self._running = False
        self._callback: Optional[Callable[[bytes], None]] = None

    def connect(self) -> bool:
        """建立TCP连接"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.config.timeout)
            self.sock.connect((self.config.host, self.config.port))
            self._connected = True
            self._running = True
            logger.info(f"以太网连接已建立 {self.config.host}:{self.config.port}")
            return True
        except socket.error as e:
            logger.error(f"以太网连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开连接"""
        self._running = False
        if self._receive_thread:
            self._receive_thread.join(timeout=2.0)
        if self.sock:
            try:
                self.sock.close()
            except socket.error:
                pass
        self._connected = False
        logger.info("以太网连接已关闭")

    def send(self, data: bytes) -> Optional[int]:
        """发送数据"""
        if self.sock and self._connected:
            try:
                return self.sock.send(data)
            except socket.error as e:
                logger.error(f"发送失败: {e}")
                return None
        return None

    def receive(self, size: Optional[int] = None) -> Optional[bytes]:
        """接收数据"""
        if self.sock and self._connected:
            try:
                size = size or self.config.buffer_size
                return self.sock.recv(size)
            except socket.timeout:
                return None
            except socket.error as e:
                logger.error(f"接收失败: {e}")
                return None
        return None

    def start_receive_loop(self, callback: Callable[[bytes], None]) -> None:
        """启动接收循环"""
        self._callback = callback
        self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._receive_thread.start()

    def _receive_loop(self) -> None:
        """内部接收循环"""
        while self._running and self._connected:
            try:
                data = self.receive()
                if data and self._callback:
                    self._callback(data)
            except Exception as e:
                logger.error(f"接收循环异常: {e}")
                break

    @property
    def is_connected(self) -> bool:
        return self._connected


class AsyncEthernetComm:
    """异步以太网通信类"""

    def __init__(self, config: Optional[EthernetConfig] = None):
        self.config = config or EthernetConfig()
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    async def connect(self) -> bool:
        """建立异步TCP连接"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.config.host, self.config.port
            )
            self._connected = True
            logger.info(f"异步以太网连接已建立 {self.config.host}:{self.config.port}")
            return True
        except socket.error as e:
            logger.error(f"异步以太网连接失败: {e}")
            return False

    async def send(self, data: bytes) -> Optional[int]:
        """异步发送数据"""
        if self.writer and self._connected:
            try:
                self.writer.write(data)
                await self.writer.drain()
                return len(data)
            except socket.error as e:
                logger.error(f"异步发送失败: {e}")
                return None
        return None

    async def receive(self, size: int = 4096) -> Optional[bytes]:
        """异步接收数据"""
        if self.reader and self._connected:
            try:
                return await self.reader.read(size)
            except socket.error as e:
                logger.error(f"异步接收失败: {e}")
                return None
        return None

    async def disconnect(self) -> None:
        """断开连接"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self._connected = False
        logger.info("异步以太网连接已关闭")

    @property
    def is_connected(self) -> bool:
        return self._connected
