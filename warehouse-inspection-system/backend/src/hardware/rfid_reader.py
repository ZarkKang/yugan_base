"""
RFID读卡器模块 - E720系列超高频RFID一体化模块
通讯协议: 二进制帧格式 (Header=0xBB, End=0x7E)
默认波特率: 115200
"""
import struct
import time
import logging
import threading
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

from .serial import SerialComm, SerialConfig, list_available_ports

logger = logging.getLogger(__name__)

# ── E720 协议常量 ───────────────────────────────
FRAME_HEADER = 0xBB
FRAME_END = 0x7E

# Type 字段
TYPE_COMMAND = 0x00   # 上位机 -> 模块
TYPE_RESPONSE = 0x01  # 模块 -> 上位机 (响应)
TYPE_NOTIFY = 0x02    # 模块 -> 上位机 (通知，读到标签主动上报)

# Command 字段
CMD_GET_MODULE_INFO = 0x03
CMD_INVENTORY_ONCE = 0x22
CMD_INVENTORY_MULTI = 0x27
CMD_STOP_INVENTORY = 0x28
CMD_SET_REGION = 0x07
CMD_SET_POWER = 0xB6
CMD_GET_POWER = 0xB7

# 错误码
ERR_NO_TAG = 0x15


@dataclass
class RFIDTag:
    """RFID标签数据"""
    tag_id: str           # EPC标签ID (hex字符串)
    rssi: Optional[int] = None   # 信号强度 (dBm, 有符号数)
    pc: Optional[int] = None     # PC字
    read_time: float = 0.0       # 读取时间戳

    def __dict__(self) -> dict:
        return {
            "tag_id": self.tag_id,
            "rssi": self.rssi,
            "pc": self.pc,
            "read_time": self.read_time,
        }


@dataclass
class RFIDConfig:
    """RFID配置"""
    port: str = "auto"           # auto = 自动探测
    baudrate: int = 115200       # E720默认115200
    timeout: float = 2.0
    scan_interval: float = 0.5   # 扫描间隔(秒)
    auto_detect: bool = True     # 是否启动自动探测
    power_dbm: int = 26          # 发射功率 dBm (默认26)
    region: int = 1              # 工作地区: 1=中国2, 2=美标, 3=欧标, 4=中国1, 5=韩国


class RFIDReader:
    """E720 RFID读卡器管理器 - 支持自动探测、连续扫描、读取/写入"""

    # 常见波特率 (E720默认115200)
    COMMON_BAUDRATES = [115200, 9600, 38400, 19200, 57600]
    # 常见串口设备名称模式
    COMMON_PORT_PATTERNS = [
        '/dev/ttyUSB',   # Linux USB转串口
        '/dev/ttyACM',   # Linux Arduino/ACM
        '/dev/ttyS',     # WSL COM端口映射 (COM1=ttyS0, COM7=ttyS6)
        'COM',           # Windows
        '/dev/cu.',      # macOS
    ]

    def __init__(self, config: Optional[RFIDConfig] = None):
        self.config = config or RFIDConfig()
        self.serial: Optional[SerialComm] = None
        self._running = False
        self._scan_thread: Optional[threading.Thread] = None
        self._last_tags: Dict[str, RFIDTag] = {}
        self._lock = threading.Lock()
        self._connected = False
        self._auto_detected_port: Optional[str] = None
        self.on_tag_detected: Optional[callable] = None

    # ─ 帧构建工具 ──────────────────────────────
    @staticmethod
    def _build_frame(cmd: int, params: bytes = b'') -> bytes:
        """构建E720指令帧"""
        pl = len(params)
        # PL = 2字节 (MSB, LSB)
        pl_bytes = struct.pack('>H', pl)
        # 从Type到最后一个Parameter累加校验
        data = bytes([TYPE_COMMAND, cmd]) + pl_bytes + params
        checksum = sum(data) & 0xFF
        frame = bytes([FRAME_HEADER]) + data + bytes([checksum, FRAME_END])
        return frame

    @staticmethod
    def _calc_checksum(data: bytes) -> int:
        """计算校验和 (从Type到最后一个Parameter)"""
        return sum(data) & 0xFF

    # ── 接收解析 ────────────────────────────────
    def _read_frame(self, timeout: float = 2.0) -> Optional[bytes]:
        """从串口读取一个完整帧
        返回: 完整帧字节，None表示超时或无数据
        """
        start = time.time()
        buf = bytearray()

        while time.time() - start < timeout:
            chunk = self.serial.read(64)
            if chunk:
                buf.extend(chunk)

            # 查找帧头
            header_idx = buf.find(bytes([FRAME_HEADER]))
            if header_idx < 0:
                # 没有找到帧头，清空无效数据
                if len(buf) > 0:
                    buf.clear()
                time.sleep(0.01)
                continue

            # 截断到帧头
            if header_idx > 0:
                del buf[:header_idx]

            # 至少需要7字节 (Header+Type+Cmd+PL(2)+CS+End)
            if len(buf) < 7:
                time.sleep(0.01)
                continue

            # 解析长度
            pl = struct.unpack('>H', bytes(buf[3:5]))[0]
            frame_len = 1 + 1 + 1 + 2 + pl + 1 + 1  # Header + Type + Cmd + PL + Params + CS + End

            if len(buf) < frame_len:
                time.sleep(0.01)
                continue

            frame = bytes(buf[:frame_len])
            del buf[:frame_len]

            # 验证帧尾
            if frame[-1] != FRAME_END:
                logger.debug(f"[RFID] 帧尾不匹配: {frame[-1]:02X}")
                continue

            # 验证校验和
            expected_cs = self._calc_checksum(frame[1:-2])
            actual_cs = frame[-2]
            if expected_cs != actual_cs:
                logger.debug(f"[RFID] 校验和不匹配: expected={expected_cs:02X}, actual={actual_cs:02X}")
                continue

            return frame

        return None

    def _parse_response(self, frame: bytes) -> Tuple[int, int, bytes]:
        """解析响应帧
        返回: (Type, Command, Parameter)
        """
        frame_type = frame[1]
        cmd = frame[2]
        pl = struct.unpack('>H', bytes(frame[3:5]))[0]
        params = frame[5:5+pl]
        return frame_type, cmd, params

    # ─ 自动探测 ────────────────────────────────
    def auto_detect(self) -> Optional[str]:
        """自动探测E720 RFID读卡器"""
        logger.info("[RFID] 开始自动探测E720模块...")
        ports = list_available_ports()
        logger.info(f"[RFID] 可用串口: {ports}")

        for port in ports:
            if not any(port.startswith(p) for p in self.COMMON_PORT_PATTERNS):
                continue

            # WSL COM端口直接尝试 (不需要试多个波特率)
            if '/dev/ttyS' in port:
                if self._try_wsl_port(port):
                    self._auto_detected_port = port
                    logger.info(f"[RFID] 探测成功: {port} (WSL)")
                    return port
                continue

            for baud in self.COMMON_BAUDRATES:
                if self._try_port(port, baud):
                    self._auto_detected_port = port
                    logger.info(f"[RFID] 探测成功: {port} @ {baud} baud")
                    return port

        logger.warning("[RFID] 自动探测未找到E720 RFID读卡器")
        return None

    def _try_port(self, port: str, baudrate: int) -> bool:
        """尝试连接端口，发送模块信息查询指令验证"""
        try:
            # WSL COM端口: 直接使用文件描述符方式，绕过pyserial配置
            if '/dev/ttyS' in port:
                return self._try_wsl_port(port)

            cfg = SerialConfig(port=port, baudrate=baudrate, timeout=1.0)
            comm = SerialComm(cfg)
            if not comm.connect():
                return False

            # 发送获取模块信息指令
            cmd = self._build_frame(CMD_GET_MODULE_INFO, bytes([0x00]))
            comm.write(cmd)
            time.sleep(0.5)

            # 尝试读取响应
            for _ in range(10):
                frame = self._read_frame(timeout=0.3)
                if frame:
                    ftype, fcmd, params = self._parse_response(frame)
                    if ftype == TYPE_RESPONSE and fcmd == CMD_GET_MODULE_INFO:
                        logger.info(f"[RFID] 模块信息: {params.hex()}")
                        comm.disconnect()
                        return True

            comm.disconnect()
            return False
        except Exception as e:
            logger.debug(f"[RFID] 探测 {port}@{baudrate} 失败: {e}")
            return False

    def _try_wsl_port(self, port: str) -> bool:
        """WSL COM端口探测 - 直接使用文件描述符"""
        import os, select
        fd = None
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            logger.debug(f"[RFID] WSL打开 {port} fd={fd}")

            # 发送获取模块信息指令
            cmd = self._build_frame(CMD_GET_MODULE_INFO, bytes([0x00]))
            os.write(fd, cmd)
            time.sleep(0.5)

            # 读取响应
            buf = bytearray()
            for _ in range(20):
                try:
                    ready, _, _ = select.select([fd], [], [], 0.3)
                    if ready:
                        data = os.read(fd, 256)
                        if data:
                            buf.extend(data)
                    else:
                        # 没有数据，检查是否已经收到完整帧
                        if len(buf) >= 7:
                            frame = self._parse_frame_from_buf(buf)
                            if frame:
                                ftype, fcmd, params = self._parse_response(frame)
                                if ftype == TYPE_RESPONSE and fcmd == CMD_GET_MODULE_INFO:
                                    logger.info(f"[RFID] WSL探测成功 {port}: {params.hex()}")
                                    return True
                        continue
                except OSError:
                    break

            return False
        except OSError as e:
            logger.debug(f"[RFID] WSL探测 {port} 失败: {e}")
            return False
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _read_frame_from_buf(self, timeout: float = 2.0) -> Optional[bytes]:
        """从临时缓冲区读取帧"""
        buf = self._parse_frame_from_buf(self._ws_temp_buf)
        return buf

    @staticmethod
    def _parse_frame_from_buf(buf: bytearray) -> Optional[bytes]:
        """从缓冲区解析一个完整帧（静态方法）"""
        # 查找帧头
        header_idx = buf.find(bytes([FRAME_HEADER]))
        if header_idx < 0:
            buf.clear()
            return None

        # 截断到帧头
        if header_idx > 0:
            del buf[:header_idx]

        # 至少需要7字节
        if len(buf) < 7:
            return None

        # 解析长度
        pl = struct.unpack('>H', bytes(buf[3:5]))[0]
        frame_len = 1 + 1 + 1 + 2 + pl + 1 + 1

        if len(buf) < frame_len:
            return None

        frame = bytes(buf[:frame_len])
        del buf[:frame_len]

        # 验证帧尾
        if frame[-1] != FRAME_END:
            return None

        # 验证校验和
        expected_cs = RFIDReader._calc_checksum(frame[1:-2])
        actual_cs = frame[-2]
        if expected_cs != actual_cs:
            return None

        return frame

    # ── 连接/断开 ───────────────────────────────
    def connect(self, port: Optional[str] = None, baudrate: Optional[int] = None) -> bool:
        """连接E720 RFID读卡器"""
        if self._connected and self.serial and self.serial.is_connected:
            logger.info("[RFID] 已经连接")
            return True

        if (port is None or port == "auto") and self.config.auto_detect:
            port = self.auto_detect()
            if port is None:
                return False

        if port is None:
            logger.error("[RFID] 未指定端口，且自动探测失败")
            return False

        # WSL COM端口: 直接使用文件描述符方式
        if '/dev/ttyS' in port:
            return self._connect_wsl(port)

        baud = baudrate or self.config.baudrate
        cfg = SerialConfig(port=port, baudrate=baud, timeout=self.config.timeout)
        self.serial = SerialComm(cfg)

        if not self.serial.connect():
            logger.error(f"[RFID] 连接失败: {port}")
            self._connected = False
            return False

        self._connected = True
        self._auto_detected_port = port
        logger.info(f"[RFID] 已连接: {port} @ {baud} baud")
        return True

    def _connect_wsl(self, port: str) -> bool:
        """WSL COM端口连接 - 直接使用文件描述符"""
        import os, select, fcntl
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            # 创建一个包装类，兼容serial.py的接口
            class WslSerial:
                def __init__(self, fd, port):
                    self.fd = fd
                    self.port = port
                    self.is_open = True
                    self.is_connected = True
                def write(self, data: bytes) -> int:
                    return os.write(self.fd, data)
                def read(self, size: int = 1, timeout: float = 0.1) -> Optional[bytes]:
                    try:
                        ready, _, _ = select.select([self.fd], [], [], timeout)
                        if ready:
                            return os.read(self.fd, size)
                        return b''
                    except OSError:
                        return None
                def disconnect(self):
                    try:
                        os.close(self.fd)
                    except OSError:
                        pass
                    self.is_open = False
                    self.is_connected = False
            self.serial = WslSerial(fd, port)
            self._connected = True
            self._auto_detected_port = port
            logger.info(f"[RFID] WSL连接成功: {port} (fd={fd})")
            return True
        except OSError as e:
            logger.error(f"[RFID] WSL连接失败 {port}: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """断开连接"""
        self.stop_continuous_scan()
        if self.serial:
            self.serial.disconnect()
        self._connected = False
        self._last_tags.clear()
        logger.info("[RFID] RFID已断开")

    def is_connected(self) -> bool:
        """检查是否连接"""
        return self._connected and self.serial and self.serial.is_connected

    # ── 标签读取 ────────────────────────────────
    def read_single_tag(self, timeout: float = 2.0) -> Optional[RFIDTag]:
        """单次读取一个标签
        发送单次轮询指令 (0x22)，解析响应帧中的EPC和RSSI
        """
        if not self.is_connected():
            return None

        with self._lock:
            # 清空缓冲区
            self.serial.read(1000)
            # 发送单次轮询: BB 00 22 00 00 22 7E
            self.serial.write(self._build_frame(CMD_INVENTORY_ONCE))

            start = time.time()
            while time.time() - start < timeout:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue

                ftype, fcmd, params = self._parse_response(frame)

                # 类型0x02 = 通知帧 (读到标签)
                if ftype == TYPE_NOTIFY and fcmd == CMD_INVENTORY_ONCE:
                    tag = self._parse_inventory_response(params)
                    if tag:
                        with self._lock:
                            self._last_tags[tag.tag_id] = tag
                        return tag

                # 类型0x01 = 响应帧，检查是否有错误
                elif ftype == TYPE_RESPONSE:
                    if fcmd == 0xFF and len(params) >= 1:
                        err = params[0]
                        if err == ERR_NO_TAG:
                            logger.debug("[RFID] 无标签")
                        else:
                            logger.warning(f"[RFID] 错误码: 0x{err:02X}")

        return None

    def read_multiple_tags(self, timeout: float = 2.0, count: int = 100) -> List[RFIDTag]:
        """读取当前场内所有标签
        count: 轮询次数 (0=连续直到timeout)
        """
        tags: List[RFIDTag] = []
        if not self.is_connected():
            return tags

        with self._lock:
            self.serial.read(1000)
            # 发送多次轮询: BB 00 27 00 02 <count_MSB> <count_LSB> <CS> 7E
            count_bytes = struct.pack('>H', count)
            self.serial.write(self._build_frame(CMD_INVENTORY_MULTI, count_bytes))

            start = time.time()
            while time.time() - start < timeout:
                frame = self._read_frame(timeout=0.3)
                if frame is None:
                    time.sleep(0.05)
                    continue

                ftype, fcmd, params = self._parse_response(frame)

                if ftype == TYPE_NOTIFY and fcmd in (CMD_INVENTORY_ONCE, CMD_INVENTORY_MULTI):
                    tag = self._parse_inventory_response(params)
                    if tag and tag.tag_id not in [t.tag_id for t in tags]:
                        tags.append(tag)
                        with self._lock:
                            self._last_tags[tag.tag_id] = tag
                elif ftype == TYPE_RESPONSE:
                    # 轮询结束或错误
                    break

            # 停止轮询 (如果还在进行)
            self.serial.write(self._build_frame(CMD_STOP_INVENTORY))

        return tags

    def _parse_inventory_response(self, params: bytes) -> Optional[RFIDTag]:
        """解析盘存响应参数
        格式: [RSSI 1B] [PC 2B] [EPC 12B] [CRC 2B]
        """
        if len(params) < 17:  # 1+2+12+2 = 17
            return None

        rssi_byte = params[0]
        # RSSI是有符号数 (如 0xC9 = -55dBm)
        rssi = rssi_byte if rssi_byte < 128 else rssi_byte - 256

        pc = struct.unpack('>H', params[1:3])[0]
        epc = params[3:15]  # 12字节EPC

        tag_id = epc.hex().upper()
        return RFIDTag(
            tag_id=tag_id,
            rssi=rssi,
            pc=pc,
            read_time=time.time(),
        )

    # ── 标签写入 ────────────────────────────────
    def write_tag(self, data: bytes, tag_id: Optional[str] = None,
                  mem_bank: int = 3, start_addr: int = 0,
                  access_pwd: bytes = b'\x00\x00\x00\x00') -> bool:
        """写入数据到RFID标签 (0x49指令)
        mem_bank: 0=Reserved, 1=EPC, 2=TID, 3=User
        """
        if not self.is_connected():
            logger.error("[RFID] 未连接，无法写入")
            return False

        # 如果未指定标签ID，先读一个
        if tag_id is None:
            tag = self.read_single_tag(timeout=2.0)
            if tag is None:
                logger.error("[RFID] 未检测到标签，写入失败")
                return False
            tag_id = tag.tag_id

        # 数据长度 (Word数)
        word_len = len(data) // 2
        if len(data) % 2 != 0:
            data = data + b'\x00'  # 补齐
            word_len = len(data) // 2

        # 构建参数: AccessPwd(4B) + MemBank(1B) + SA(2B) + DL(2B) + Data
        params = access_pwd + bytes([mem_bank]) + struct.pack('>H', start_addr) + struct.pack('>H', word_len) + data
        cmd = self._build_frame(0x49, params)

        with self._lock:
            self.serial.write(cmd)
            start = time.time()
            while time.time() - start < 3.0:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue
                ftype, fcmd, fparams = self._parse_response(frame)
                if ftype == TYPE_RESPONSE and fcmd == 0x49:
                    if len(fparams) >= 1 and fparams[0] == 0x00:
                        logger.info(f"[RFID] 写入成功: {tag_id}")
                        return True
                    else:
                        logger.error(f"[RFID] 写入失败: error=0x{fparams[0]:02X}")
                        return False

            logger.error("[RFID] 写入超时")
            return False

    # ── 模块配置 ───────────────────────────────
    def set_power(self, power_dbm: int) -> bool:
        """设置发射功率 (dBm)"""
        if not self.is_connected():
            return False
        # 功率值 = dBm * 100 (如26dBm = 2600 = 0x0A28)
        power_val = power_dbm * 100
        params = struct.pack('>H', power_val)
        cmd = self._build_frame(CMD_SET_POWER, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_region(self, region: int) -> bool:
        """设置工作地区"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_REGION, bytes([region]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def get_module_info(self) -> Optional[str]:
        """获取模块信息"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_GET_MODULE_INFO, bytes([0x00])))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_RESPONSE and fcmd == CMD_GET_MODULE_INFO:
                    return params.hex()
        return None

    # ── 缓存与连续扫描 ──────────────────────────
    def get_last_tags(self) -> List[RFIDTag]:
        """获取最近扫描到的所有标签"""
        with self._lock:
            return list(self._last_tags.values())

    def clear_last_tags(self):
        """清空标签缓存"""
        with self._lock:
            self._last_tags.clear()

    def start_continuous_scan(self):
        """启动连续扫描后台线程"""
        if self._running:
            logger.warning("[RFID] 连续扫描已经在运行")
            return
        if not self.is_connected():
            if not self.connect():
                logger.error("[RFID] 连接失败，无法启动扫描")
                return
        self._running = True
        self._scan_thread = threading.Thread(
            target=self._scan_loop,
            name="rfid-scan",
            daemon=True,
        )
        self._scan_thread.start()
        logger.info("[RFID] 连续扫描已启动")

    def stop_continuous_scan(self):
        """停止连续扫描"""
        self._running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=2.0)
            self._scan_thread = None
        # 发送停止指令
        if self.serial and self.serial.is_open:
            try:
                self.serial.write(self._build_frame(CMD_STOP_INVENTORY))
            except Exception:
                pass
        logger.info("[RFID] 连续扫描已停止")

    def _scan_loop(self):
        """后台扫描循环 - 使用通知帧被动接收"""
        # 先发送一次多次轮询指令
        if self.is_connected():
            count_bytes = struct.pack('>H', 0)  # 0=无限连续
            self.serial.write(self._build_frame(CMD_INVENTORY_MULTI, count_bytes))

        while self._running:
            if not self.is_connected():
                time.sleep(1.0)
                continue

            frame = self._read_frame(timeout=self.config.scan_interval)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_NOTIFY and fcmd in (CMD_INVENTORY_ONCE, CMD_INVENTORY_MULTI):
                    tag = self._parse_inventory_response(params)
                    if tag:
                        with self._lock:
                            is_new = tag.tag_id not in self._last_tags
                            self._last_tags[tag.tag_id] = tag
                        if is_new and self.on_tag_detected:
                            try:
                                self.on_tag_detected(tag)
                            except Exception as e:
                                logger.error(f"[RFID] 回调异常: {e}")

    def get_connection_info(self) -> dict:
        """获取连接信息"""
        return {
            "connected": self.is_connected(),
            "port": self._auto_detected_port or (self.config.port if self.config.port != "auto" else None),
            "baudrate": self.config.baudrate,
            "last_tags_count": len(self._last_tags),
            "scanning": self._running,
            "protocol": "E720 (binary)",
        }


# ── 全局单例 ──────────────────────────────────────
_reader_instance: Optional[RFIDReader] = None
_instance_lock = threading.Lock()


def get_rfid_reader(config: Optional[RFIDConfig] = None) -> RFIDReader:
    """获取全局RFID阅读器单例"""
    global _reader_instance
    with _instance_lock:
        if _reader_instance is None:
            _reader_instance = RFIDReader(config)
        return _reader_instance
