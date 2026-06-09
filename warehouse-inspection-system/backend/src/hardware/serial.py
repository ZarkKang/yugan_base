"""
硬件通信模块 - 串口通信
"""
import serial
import serial.tools.list_ports
from typing import Optional, List
from dataclasses import dataclass
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class SerialConfig:
    port: str = "/dev/ttyUSB0"
    baudrate: int = 9600
    bytesize: int = serial.EIGHTBITS
    parity: str = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE
    timeout: Optional[float] = None


class SerialComm:
    """串口通信类"""

    def __init__(self, config: Optional[SerialConfig] = None):
        self.config = config or SerialConfig()
        self.ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False

    def connect(self) -> bool:
        """打开串口连接"""
        try:
            self.ser = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                bytesize=self.config.bytesize,
                parity=self.config.parity,
                stopbits=self.config.stopbits,
                timeout=self.config.timeout
            )
            self._connected = True
            logger.info(f"串口 {self.config.port} 已连接")
            return True
        except serial.SerialException as e:
            logger.error(f"串口连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """关闭串口连接"""
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
                self._connected = False
                logger.info(f"串口 {self.config.port} 已关闭")

    def read(self, size: int = 1) -> Optional[bytes]:
        """读取数据"""
        with self._lock:
            if self.ser and self.ser.is_open:
                try:
                    return self.ser.read(size)
                except serial.SerialException as e:
                    logger.error(f"串口读取失败: {e}")
                    return None
            return None

    def write(self, data: bytes) -> Optional[int]:
        """写入数据"""
        with self._lock:
            if self.ser and self.ser.is_open:
                try:
                    return self.ser.write(data)
                except serial.SerialException as e:
                    logger.error(f"串口写入失败: {e}")
                    return None
            return None

    def read_line(self) -> Optional[str]:
        """读取一行数据"""
        with self._lock:
            if self.ser and self.ser.is_open:
                try:
                    return self.ser.readline().decode('utf-8', errors='ignore').strip()
                except serial.SerialException as e:
                    logger.error(f"串口读取失败: {e}")
                    return None
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected and self.ser is not None and self.ser.is_open


def list_available_ports() -> List[str]:
    """列出所有可用串口"""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]
