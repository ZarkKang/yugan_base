"""
RFID读卡器模块 — PRE系列超高频RFID一体化模块
协议版本: V2.2 (对齐 C# SDK RFID_Reader_Cmds + RFID_Reader_Com)
通讯协议: 二进制帧格式 (Header=0xBB, End=0x7E)
默认波特率: 115200 (模块默认), 也支持 9600
"""
import struct
import os
import time
import logging
import threading
from typing import Optional, List, Dict, Tuple, Callable
from dataclasses import dataclass, field

from .serial import SerialComm, SerialConfig, list_available_ports

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
#  PRE 模块协议常量 (对齐 C# ConstCode)
# ═══════════════════════════════════════════════════════════
FRAME_HEADER = 0xBB
FRAME_END    = 0x7E

# ── Type 字段 ─────────────────────────────────────────────
TYPE_COMMAND  = 0x00   # 上位机 → 模块
TYPE_ANSWER   = 0x01   # 模块 → 上位机 (响应)
TYPE_INFO     = 0x02   # 模块 → 上位机 (通知, 读到标签主动上报)

# ── Command 字段 ──────────────────────────────────────────
CMD_GET_MODULE_INFO      = 0x03   # 获取模块信息(硬件/软件/厂商)
CMD_INVENTORY            = 0x04   # 单次盘存 (读单个标签 PC+EPC)
CMD_SET_QUERY            = 0x05   # 设置 Query 参数
CMD_GET_QUERY            = 0x06   # 获取 Query 参数
CMD_SET_REGION           = 0x07   # 设置 RF 地区
CMD_READ_MULTI           = 0x08   # 多次盘存 (读多个标签 PC+EPC)
CMD_STOP_MULTI           = 0x09   # 停止多次盘存
CMD_SET_POWER            = 0x0A   # 设置发射功率
CMD_GET_POWER            = 0x0B   # 获取发射功率
CMD_READ_DATA            = 0x0C   # 读标签内存数据
CMD_WRITE_DATA           = 0x0D   # 写标签内存数据
CMD_LOCK_UNLOCK          = 0x0E   # 锁定/解锁标签内存
CMD_KILL                 = 0x0F   # 杀死标签
CMD_SET_RF_CHANNEL       = 0x10   # 设置 RF 信道
CMD_GET_RF_CHANNEL       = 0x11   # 获取 RF 信道
CMD_SET_FHSS             = 0x12   # 设置 FHSS 开/关
CMD_SET_CW               = 0x13   # 设置 CW 开/关
CMD_SET_MODEM_PARA       = 0x14   # 设置 Modem 参数
CMD_READ_MODEM_PARA      = 0x15   # 读取 Modem 参数
CMD_SET_SELECT_PARA      = 0x16   # 设置 ISO18000-6C Select 参数
CMD_GET_SELECT_PARA      = 0x17   # 获取 Select 参数
CMD_SET_INVENTORY_MODE   = 0x18   # 设置盘存模式
CMD_SCAN_JAMMER          = 0x19   # 扫描干扰
CMD_SCAN_RSSI            = 0x1A   # 扫描 RSSI
CMD_IO_CONTROL           = 0x1B   # IO 控制
CMD_SET_READER_ENV_MODE  = 0x1C   # 设置读卡器环境模式
CMD_INSERT_FHSS_CHANNEL  = 0x1D   # 插入 FHSS 信道
CMD_SLEEP_MODE           = 0x1E   # 设置休眠模式
CMD_SET_SLEEP_TIME       = 0x1F   # 设置空闲休眠时间
CMD_LOAD_NV_CONFIG       = 0x20   # 从 NV 加载配置
CMD_SAVE_NV_CONFIG       = 0x21   # 保存配置到 NV
CMD_RESTART              = 0x22   # 重启读卡器
CMD_NXP_CHANGE_CONFIG    = 0x23   # NXP G2X ChangeConfig
CMD_NXP_READPROTECT      = 0x24   # NXP G2X ReadProtect
CMD_NXP_CHANGE_EAS       = 0x25   # NXP G2X ChangeEAS
CMD_NXP_EAS_ALARM        = 0x26   # NXP G2X EAS Alarm
CMD_MONZA_QT_READ        = 0x27   # Monza QT Read
CMD_MONZA_QT_WRITE       = 0x28   # Monza QT Write
CMD_EXE_FAILED           = 0xFF   # 命令执行失败

# ── 错误码 ────────────────────────────────────────────────
FAIL_INVALID_PARA              = 0x01   # 参数无效
FAIL_INVENTORY_TAG_TIMEOUT     = 0x02   # 盘存超时 (无标签)
FAIL_INVALID_CMD               = 0x03   # 无效命令
FAIL_FHSS_FAIL                 = 0x04   # FHSS 失败
FAIL_ACCESS_PWD_ERROR          = 0x05   # 访问密码错误
FAIL_READ_MEMORY_NO_TAG        = 0x06   # 读内存无标签响应
FAIL_READ_ERROR_CODE_BASE      = 0x10   # 读操作错误码基址
FAIL_WRITE_MEMORY_NO_TAG       = 0x07   # 写内存无标签响应
FAIL_WRITE_ERROR_CODE_BASE     = 0x20   # 写操作错误码基址
FAIL_LOCK_NO_TAG               = 0x08   # 锁定无标签响应
FAIL_LOCK_ERROR_CODE_BASE      = 0x30   # 锁定操作错误码基址
FAIL_KILL_NO_TAG               = 0x09   # 杀死无标签响应
FAIL_KILL_ERROR_CODE_BASE      = 0x40   # 杀死操作错误码基址
FAIL_NXP_CHANGE_CONFIG_NO_TAG  = 0x0A
FAIL_NXP_READPROTECT_NO_TAG    = 0x0B
FAIL_NXP_RESET_READPROTECT_NO_TAG = 0x0C
FAIL_NXP_CHANGE_EAS_NO_TAG     = 0x0D
FAIL_NXP_CHANGE_EAS_NOT_SECURE = 0x0E
FAIL_NXP_EAS_ALARM_NO_TAG      = 0x0F
FAIL_MONZA_QT_NO_TAG           = 0x2E
FAIL_CUSTOM_CMD_BASE           = 0x50

# ── 地区码 ────────────────────────────────────────────────
REGION_CHN2 = 0x01   # 中国2 (920-925MHz)
REGION_US   = 0x02   # 美标
REGION_EUR  = 0x03   # 欧标
REGION_CHN1 = 0x04   # 中国1 (840-845MHz)
REGION_KOREA = 0x06  # 韩国

# ── 通用开关 ──────────────────────────────────────────────
SET_ON  = 0x01
SET_OFF = 0x00

# ── 模块信息类型 ──────────────────────────────────────────
MODULE_HARDWARE_VERSION   = 0x00
MODULE_SOFTWARE_VERSION   = 0x01
MODULE_MANUFACTURE_INFO   = 0x02

# ── 盘存模式 ──────────────────────────────────────────────
INVENTORY_MODE0 = 0x00  # 每条命令前发 Select
INVENTORY_MODE1 = 0x01  # 不发 Select
INVENTORY_MODE2 = 0x02  # 除盘存外其他命令前发 Select

# ── 错误描述映射 ──────────────────────────────────────────
FAIL_MESSAGES = {
    FAIL_INVALID_PARA:              "参数无效",
    FAIL_INVENTORY_TAG_TIMEOUT:     "盘存超时(无标签)",
    FAIL_INVALID_CMD:               "无效命令",
    FAIL_FHSS_FAIL:                 "FHSS失败",
    FAIL_ACCESS_PWD_ERROR:          "访问密码错误",
    FAIL_READ_MEMORY_NO_TAG:        "读内存无标签响应",
    FAIL_WRITE_MEMORY_NO_TAG:       "写内存无标签响应",
    FAIL_LOCK_NO_TAG:               "锁定无标签响应",
    FAIL_KILL_NO_TAG:               "杀死无标签响应",
    FAIL_MONZA_QT_NO_TAG:           "QT命令无标签响应",
}


@dataclass
class RFIDTag:
    """RFID标签数据"""
    tag_id: str                      # EPC标签ID (hex字符串, 大写)
    rssi: Optional[int] = None       # 信号强度 (dBm, 有符号数)
    pc: Optional[int] = None         # PC字 (2字节)
    crc: Optional[int] = None        # CRC16
    read_time: float = 0.0           # 读取时间戳

    def __dict__(self) -> dict:
        return {
            "tag_id": self.tag_id,
            "rssi": self.rssi,
            "pc": self.pc,
            "crc": self.crc,
            "read_time": self.read_time,
        }


@dataclass
class RFIDConfig:
    """RFID配置"""
    port: str = "auto"
    baudrate: int = 115200
    timeout: float = 2.0
    scan_interval: float = 0.5
    auto_detect: bool = True
    power_dbm: int = 26
    region: int = REGION_CHN2


class RFIDReader:
    """
    PRE系列 UHF RFID读卡器管理器

    协议: 二进制帧 BB [Type] [Cmd] [PL_MSB] [PL_LSB] [Params...] [CS] 7E
    """

    COMMON_BAUDRATES = [115200, 9600, 38400, 19200, 57600]
    COMMON_PORT_PATTERNS = [
        '/dev/ttyUSB', '/dev/ttyACM', '/dev/ttyS', 'COM', '/dev/cu.',
    ]

    # 扫描历史记录上限（内存循环覆盖）
    SCAN_HISTORY_MAX = 1000

    def __init__(self, config: Optional[RFIDConfig] = None):
        self.config = config or RFIDConfig()
        self.serial: Optional[SerialComm] = None
        self._running = False
        self._scan_thread: Optional[threading.Thread] = None
        self._last_tags: Dict[str, RFIDTag] = {}
        self._lock = threading.Lock()
        self._connected = False
        self._auto_detected_port: Optional[str] = None
        self.on_tag_detected: Optional[Callable[[RFIDTag], None]] = None
        # 扫描事件历史（按时间顺序追加，超出上限丢弃最早）
        self._scan_history: List[Dict] = []
        # 统计计数
        self._stats = {"auto": 0, "single": 0, "manual": 0, "unique_tags": 0}

    # ═══════════════════════════════════════════════════════
    #  帧构建 / 解析 (对齐 C# Commands.BuildFrame)
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _build_frame(cmd: int, params: bytes = b'') -> bytes:
        """构建 PRE 指令帧: BB + Type(0x00) + Cmd + PL(2) + Params + CS + 7E"""
        pl = len(params)
        pl_bytes = struct.pack('>H', pl)
        data = bytes([TYPE_COMMAND, cmd]) + pl_bytes + params
        checksum = sum(data) & 0xFF
        return bytes([FRAME_HEADER]) + data + bytes([checksum, FRAME_END])

    @staticmethod
    def _calc_checksum(data: bytes) -> int:
        """校验和: 从 Type 到最后一个 Parameter 累加取 LSB"""
        return sum(data) & 0xFF

    # ═══════════════════════════════════════════════════════
    #  扫描历史记录（用于看板实时展示）
    # ═══════════════════════════════════════════════════════

    def _append_scan_history(self, tag: "RFIDTag", mode: str):
        """将单次扫描事件追加到历史记录（线程安全）

        mode: auto(连续扫描) / single(单次盘存) / manual(手动触发)
        """
        event = {
            "tag_id": tag.tag_id,
            "rssi": tag.rssi,
            "pc": tag.pc,
            "crc": tag.crc,
            "read_time": tag.read_time,
            "mode": mode,
        }
        with self._lock:
            self._scan_history.append(event)
            if len(self._scan_history) > self.SCAN_HISTORY_MAX:
                # 丢弃最早的一半，避免频繁切片
                cut = len(self._scan_history) - self.SCAN_HISTORY_MAX
                del self._scan_history[:cut]
            self._stats[mode] = self._stats.get(mode, 0) + 1
            self._stats["unique_tags"] = len(self._last_tags)

    def get_scan_history(self, limit: int = 100, since: float = 0.0) -> List[Dict]:
        """获取扫描事件历史（最新在前）

        limit: 最多返回条数
        since: 仅返回 read_time > since 的事件（用于增量轮询）
        """
        with self._lock:
            items = [e for e in self._scan_history if e["read_time"] > since]
        items.sort(key=lambda x: x["read_time"], reverse=True)
        return items[:limit]

    def clear_scan_history(self):
        """清空扫描历史（不清空 _last_tags）"""
        with self._lock:
            self._scan_history.clear()
            self._stats = {"auto": 0, "single": 0, "manual": 0, "unique_tags": len(self._last_tags)}

    def get_scan_stats(self) -> Dict:
        """获取扫描统计"""
        with self._lock:
            latest = self._scan_history[-1]["read_time"] if self._scan_history else None
            return {
                "total_events": len(self._scan_history),
                "unique_tags": len(self._last_tags),
                "auto_count": self._stats.get("auto", 0),
                "single_count": self._stats.get("single", 0),
                "manual_count": self._stats.get("manual", 0),
                "latest_event_time": latest,
                "scanning": self._running,
                "connected": self.is_connected(),
            }

    # ═══════════════════════════════════════════════════════
    #  接收解析
    # ═══════════════════════════════════════════════════════

    def _read_frame(self, timeout: float = 2.0) -> Optional[bytes]:
        """从串口读取一个完整帧"""
        start = time.time()
        buf = bytearray()

        while time.time() - start < timeout:
            chunk = self.serial.read(64)
            if chunk:
                buf.extend(chunk)

            header_idx = buf.find(bytes([FRAME_HEADER]))
            if header_idx < 0:
                if len(buf) > 0:
                    buf.clear()
                time.sleep(0.01)
                continue

            if header_idx > 0:
                del buf[:header_idx]

            if len(buf) < 7:
                time.sleep(0.01)
                continue

            pl = struct.unpack('>H', bytes(buf[3:5]))[0]
            frame_len = 7 + pl  # 1(Header) + 1(Type) + 1(Cmd) + 2(PL) + pl(Params) + 1(CS) + 1(End)

            if len(buf) < frame_len:
                time.sleep(0.01)
                continue

            frame = bytes(buf[:frame_len])
            del buf[:frame_len]

            if frame[-1] != FRAME_END:
                logger.debug(f"[RFID] 帧尾不匹配: {frame[-1]:02X}")
                continue

            expected_cs = self._calc_checksum(frame[1:-2])
            actual_cs = frame[-2]
            if expected_cs != actual_cs:
                logger.debug(f"[RFID] 校验和不匹配: expect={expected_cs:02X}, actual={actual_cs:02X}")
                continue

            return frame

        return None

    def _parse_response(self, frame: bytes) -> Tuple[int, int, bytes]:
        """解析响应帧 → (Type, Command, Parameter)"""
        frame_type = frame[1]
        cmd = frame[2]
        pl = struct.unpack('>H', bytes(frame[3:5]))[0]
        params = frame[5:5 + pl]
        return frame_type, cmd, params

    # ═══════════════════════════════════════════════════════
    #  自动探测
    # ═══════════════════════════════════════════════════════

    def auto_detect(self) -> Optional[str]:
        """自动探测 PRE RFID读卡器"""
        # Docker 容器模式: 优先使用 RFID_SERIAL_PORT 环境变量
        env_port = os.environ.get("RFID_SERIAL_PORT", "")
        if env_port and env_port != "/dev/null":
            for baud in self.COMMON_BAUDRATES:
                if self._try_port(env_port, baud):
                    self._auto_detected_port = env_port
                    logger.info(f"[RFID] 探测成功(Docker): {env_port} @ {baud}")
                    return env_port
            logger.warning(f"[RFID] 环境变量指定端口 {env_port} 探测失败")
            return None

        logger.info("[RFID] 开始自动探测PRE模块...")
        ports = list_available_ports()
        logger.info(f"[RFID] 可用串口: {ports}")

        for port in ports:
            if not any(port.startswith(p) for p in self.COMMON_PORT_PATTERNS):
                continue

            if '/dev/ttyS' in port:
                if self._try_wsl_port(port):
                    self._auto_detected_port = port
                    logger.info(f"[RFID] 探测成功: {port} (WSL)")
                    return port
                continue

            for baud in self.COMMON_BAUDRATES:
                if self._try_port(port, baud):
                    self._auto_detected_port = port
                    logger.info(f"[RFID] 探测成功: {port} @ {baud}")
                    return port

        logger.warning("[RFID] 自动探测未找到PRE RFID读卡器")
        return None

    def _try_port(self, port: str, baudrate: int) -> bool:
        """尝试连接端口并发送获取模块信息指令"""
        try:
            if '/dev/ttyS' in port:
                return self._try_wsl_port(port)

            cfg = SerialConfig(port=port, baudrate=baudrate, timeout=1.0)
            comm = SerialComm(cfg)
            if not comm.connect():
                return False

            cmd = self._build_frame(CMD_GET_MODULE_INFO, bytes([MODULE_HARDWARE_VERSION]))
            comm.write(cmd)
            time.sleep(0.5)

            saved = self.serial
            self.serial = comm
            try:
                for _ in range(10):
                    frame = self._read_frame(timeout=0.3)
                    if frame:
                        ftype, fcmd, params = self._parse_response(frame)
                        if ftype == TYPE_ANSWER and fcmd == CMD_GET_MODULE_INFO:
                            logger.info(f"[RFID] 模块信息: {params.hex()}")
                            return True
            finally:
                self.serial = saved
                comm.disconnect()

            return False
        except Exception as e:
            logger.debug(f"[RFID] 探测 {port}@{baudrate} 失败: {e}")
            return False

    def _try_wsl_port(self, port: str) -> bool:
        """WSL COM端口探测 — 直接文件描述符"""
        import os, select
        fd = None
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            logger.debug(f"[RFID] WSL打开 {port} fd={fd}")

            cmd = self._build_frame(CMD_GET_MODULE_INFO, bytes([MODULE_HARDWARE_VERSION]))
            os.write(fd, cmd)
            time.sleep(0.5)

            buf = bytearray()
            for _ in range(20):
                try:
                    ready, _, _ = select.select([fd], [], [], 0.3)
                    if ready:
                        data = os.read(fd, 256)
                        if data:
                            buf.extend(data)
                    else:
                        if len(buf) >= 7:
                            frame = self._parse_frame_from_buf(buf)
                            if frame:
                                ftype, fcmd, params = self._parse_response(frame)
                                if ftype == TYPE_ANSWER and fcmd == CMD_GET_MODULE_INFO:
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

    @staticmethod
    def _parse_frame_from_buf(buf: bytearray) -> Optional[bytes]:
        """从缓冲区解析完整帧 (静态方法)"""
        header_idx = buf.find(bytes([FRAME_HEADER]))
        if header_idx < 0:
            buf.clear()
            return None

        if header_idx > 0:
            del buf[:header_idx]

        if len(buf) < 7:
            return None

        pl = struct.unpack('>H', bytes(buf[3:5]))[0]
        frame_len = 7 + pl

        if len(buf) < frame_len:
            return None

        frame = bytes(buf[:frame_len])
        del buf[:frame_len]

        if frame[-1] != FRAME_END:
            return None

        expected_cs = RFIDReader._calc_checksum(frame[1:-2])
        if expected_cs != frame[-2]:
            return None

        return frame

    # ═══════════════════════════════════════════════════════
    #  连接 / 断开
    # ═══════════════════════════════════════════════════════

    def connect(self, port: Optional[str] = None, baudrate: Optional[int] = None) -> bool:
        """连接 PRE RFID读卡器"""
        if self._connected and self.serial and self.serial.is_connected():
            logger.info("[RFID] 已经连接")
            return True

        if (port is None or port == "auto") and self.config.auto_detect:
            port = self.auto_detect()
            if port is None:
                return False

        if port is None:
            logger.error("[RFID] 未指定端口且自动探测失败")
            return False

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
        logger.info(f"[RFID] 已连接: {port} @ {baud}")
        return True

    def _connect_wsl(self, port: str) -> bool:
        """WSL COM端口连接"""
        import os, select
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)

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
        return self._connected and self.serial and self.serial.is_connected

    # ═══════════════════════════════════════════════════════
    #  标签读取
    # ═══════════════════════════════════════════════════════

    def read_single_tag(self, timeout: float = 2.0) -> Optional[RFIDTag]:
        """单次盘存 — 发送 CMD_INVENTORY(0x04), 解析 TYPE_INFO 通知帧"""
        if not self.is_connected():
            return None

        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_INVENTORY))

            start = time.time()
            while time.time() - start < timeout:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue

                ftype, fcmd, params = self._parse_response(frame)

                # TYPE_INFO + CMD_INVENTORY = 读到标签通知
                if ftype == TYPE_INFO and fcmd == CMD_INVENTORY:
                    tag = self._parse_inventory_response(params)
                    if tag:
                        with self._lock:
                            self._last_tags[tag.tag_id] = tag
                        self._append_scan_history(tag, mode="single")
                        return tag

                # TYPE_ANSWER + CMD_EXE_FAILED = 错误
                elif ftype == TYPE_ANSWER and fcmd == CMD_EXE_FAILED:
                    if len(params) >= 1:
                        err = params[0]
                        if err == FAIL_INVENTORY_TAG_TIMEOUT:
                            logger.debug("[RFID] 单次盘存: 无标签")
                        else:
                            msg = FAIL_MESSAGES.get(err, f"0x{err:02X}")
                            logger.warning(f"[RFID] 错误: {msg}")
                    return None

        return None

    def read_multiple_tags(self, timeout: float = 3.0, loop_count: int = 100) -> List[RFIDTag]:
        """多次盘存 — CMD_READ_MULTI(0x08)"""
        tags: List[RFIDTag] = []
        if not self.is_connected():
            return tags

        with self._lock:
            self.serial.read(1000)
            count_bytes = struct.pack('>H', loop_count)
            self.serial.write(self._build_frame(CMD_READ_MULTI, count_bytes))

            start = time.time()
            while time.time() - start < timeout:
                frame = self._read_frame(timeout=0.3)
                if frame is None:
                    time.sleep(0.05)
                    continue

                ftype, fcmd, params = self._parse_response(frame)

                if ftype == TYPE_INFO and fcmd == CMD_INVENTORY:
                    tag = self._parse_inventory_response(params)
                    if tag and tag.tag_id not in [t.tag_id for t in tags]:
                        tags.append(tag)
                        with self._lock:
                            self._last_tags[tag.tag_id] = tag

                elif ftype == TYPE_ANSWER:
                    break

            self.serial.write(self._build_frame(CMD_STOP_MULTI))

        return tags

    def _parse_inventory_response(self, params: bytes) -> Optional[RFIDTag]:
        """解析盘存通知帧参数

        PRE 模块通知帧格式 (TYPE_INFO + CMD_INVENTORY):
          [RSSI 1B] [PC 2B] [EPC N字节] [CRC 2B]

        EPC 长度由 PC 字段动态决定: ((PC / 8) + 1) * 2 字节 (包含 PC 自身的 2 字节)
        实际 EPC 字节数 = ((PC / 8) + 1) * 2 - 2
        """
        if len(params) < 5:  # 至少 RSSI(1) + PC(2) + CRC(2) = 5
            return None

        rssi_byte = params[0]
        rssi = rssi_byte if rssi_byte < 128 else rssi_byte - 256

        pc = struct.unpack('>H', params[1:3])[0]

        # EPC+PC 总长度 (字节): ((PC_byte0 / 8) + 1) * 2
        # 注意: PC 是 2 字节, 公式中使用的是 PC 的**值**, 但 C# 代码用的是 packetRx[6] (PC的第一个字节)
        # packetRx[6] = params[0] in PC bytes context
        # PCEPCLength = ((Convert.ToInt32(packetRx[6], 16)) / 8 + 1) * 2
        pc_byte0 = params[1]  # PC 第一个字节 (高字节)
        pc_epc_total_len = ((pc_byte0 // 8) + 1) * 2   # PC(2) + EPC(N) 总字节数
        epc_len = pc_epc_total_len - 2                   # EPC 实际字节数

        if epc_len <= 0:
            return None

        if len(params) < 3 + epc_len + 2:  # RSSI(1) + PC(2) + EPC(N) + CRC(2)
            return None

        epc_bytes = params[3:3 + epc_len]
        crc = struct.unpack('>H', params[3 + epc_len:3 + epc_len + 2])[0]

        tag_id = epc_bytes.hex().upper()

        return RFIDTag(
            tag_id=tag_id,
            rssi=rssi,
            pc=pc,
            crc=crc,
            read_time=time.time(),
        )

    # ═══════════════════════════════════════════════════════
    #  标签写入 (CMD_WRITE_DATA = 0x0D)
    # ═══════════════════════════════════════════════════════

    def write_tag(self, data: bytes, tag_id: Optional[str] = None,
                  mem_bank: int = 3, start_addr: int = 0,
                  access_pwd: bytes = b'\x00\x00\x00\x00') -> bool:
        """写入标签内存 (CMD_WRITE_DATA)

        mem_bank: 0=Reserved, 1=EPC, 2=TID, 3=User
        """
        if not self.is_connected():
            logger.error("[RFID] 未连接，无法写入")
            return False

        if tag_id is None:
            tag = self.read_single_tag(timeout=2.0)
            if tag is None:
                logger.error("[RFID] 未检测到标签，写入失败")
                return False
            tag_id = tag.tag_id

        word_len = len(data) // 2
        if len(data) % 2 != 0:
            data = data + b'\x00'
            word_len = len(data) // 2

        params = access_pwd + bytes([mem_bank]) + struct.pack('>H', start_addr) + struct.pack('>H', word_len) + data
        cmd = self._build_frame(CMD_WRITE_DATA, params)

        with self._lock:
            self.serial.write(cmd)
            start = time.time()
            while time.time() - start < 3.0:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue
                ftype, fcmd, fparams = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_WRITE_DATA:
                    if len(fparams) >= 1 and fparams[0] == 0x00:
                        logger.info(f"[RFID] 写入成功: {tag_id}")
                        return True
                    else:
                        err = fparams[0] if len(fparams) >= 1 else 0xFF
                        logger.error(f"[RFID] 写入失败: error=0x{err:02X}")
                        return False

            logger.error("[RFID] 写入超时")
            return False

    # ═══════════════════════════════════════════════════════
    #  读标签内存 (CMD_READ_DATA = 0x0C)
    # ═══════════════════════════════════════════════════════

    def read_tag_data(self, mem_bank: int = 3, start_addr: int = 0,
                      word_count: int = 4, access_pwd: bytes = b'\x00\x00\x00\x00') -> Optional[bytes]:
        """读取标签内存数据"""
        if not self.is_connected():
            return None

        params = access_pwd + bytes([mem_bank]) + struct.pack('>H', start_addr) + struct.pack('>H', word_count)
        cmd = self._build_frame(CMD_READ_DATA, params)

        with self._lock:
            self.serial.write(cmd)
            start = time.time()
            while time.time() - start < 3.0:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue
                ftype, fcmd, fparams = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_READ_DATA:
                    return fparams

            logger.error("[RFID] 读标签数据超时")
            return None

    # ═══════════════════════════════════════════════════════
    #  锁定/解锁 (CMD_LOCK_UNLOCK = 0x0E)
    # ═══════════════════════════════════════════════════════

    def lock_tag(self, lock_opt: int = 1, mem_space: int = 2,
                  access_pwd: bytes = b'\x00\x00\x00\x00') -> bool:
        """锁定/解锁标签内存

        lock_opt: 0=unlock, 1=lock, 2=perma_unlock, 3=perma_lock
        mem_space: 0=KillPwd, 1=AccessPwd, 2=EPC, 3=TID, 4=User
        锁定载荷结构: 3 bytes, 高 4 bits 保留
        """
        if not self.is_connected():
            return False

        # 构建 20-bit 锁定载荷
        payload = 0
        # memSpace 占 3 bits, lockOpt 占 2 bits
        # memSpace 从 bit 10 开始 (byte1 的低 2 bits + byte2 的高 3 bits)
        payload |= (mem_space & 0x07) << 10
        payload |= (lock_opt & 0x03) << 8

        payload_bytes = struct.pack('>I', payload)[1:]  # 取低 3 字节

        params = access_pwd + payload_bytes
        cmd = self._build_frame(CMD_LOCK_UNLOCK, params)

        with self._lock:
            self.serial.write(cmd)
            start = time.time()
            while time.time() - start < 3.0:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue
                ftype, fcmd, fparams = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_LOCK_UNLOCK:
                    if len(fparams) >= 1 and fparams[0] == 0x00:
                        logger.info("[RFID] 锁定操作成功")
                        return True
                    else:
                        err = fparams[0] if len(fparams) >= 1 else 0xFF
                        logger.error(f"[RFID] 锁定失败: error=0x{err:02X}")
                        return False

            logger.error("[RFID] 锁定操作超时")
            return False

    # ═══════════════════════════════════════════════════════
    #  杀死标签 (CMD_KILL = 0x0F)
    # ═══════════════════════════════════════════════════════

    def kill_tag(self, kill_pwd: bytes = b'\x00\x00\x00\x00', rfu: int = 0) -> bool:
        """杀死标签"""
        if not self.is_connected():
            return False

        params = kill_pwd + bytes([rfu])
        cmd = self._build_frame(CMD_KILL, params)

        with self._lock:
            self.serial.write(cmd)
            start = time.time()
            while time.time() - start < 3.0:
                frame = self._read_frame(timeout=0.5)
                if frame is None:
                    continue
                ftype, fcmd, fparams = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_KILL:
                    if len(fparams) >= 1 and fparams[0] == 0x00:
                        logger.info("[RFID] 标签已杀死")
                        return True
                    else:
                        err = fparams[0] if len(fparams) >= 1 else 0xFF
                        logger.error(f"[RFID] 杀死标签失败: error=0x{err:02X}")
                        return False

            logger.error("[RFID] 杀死标签超时")
            return False

    # ═══════════════════════════════════════════════════════
    #  模块配置
    # ═══════════════════════════════════════════════════════

    def set_power(self, power_dbm: int) -> bool:
        """设置发射功率 (CMD_SET_POWER=0x0A), power_dbm*100"""
        if not self.is_connected():
            return False
        power_val = power_dbm * 100
        params = struct.pack('>H', power_val)
        cmd = self._build_frame(CMD_SET_POWER, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def get_power(self) -> Optional[int]:
        """获取当前功率 (CMD_GET_POWER=0x0B), 返回 dBm"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_GET_POWER))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_GET_POWER and len(params) >= 2:
                    val = struct.unpack('>H', params[:2])[0]
                    return val // 100
        return None

    def set_region(self, region: int) -> bool:
        """设置工作地区 (CMD_SET_REGION=0x07)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_REGION, bytes([region]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_fhss(self, on: bool) -> bool:
        """设置 FHSS 开/关 (CMD_SET_FHSS=0x12)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_FHSS, bytes([SET_ON if on else SET_OFF]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_cw(self, on: bool) -> bool:
        """设置 CW 载波开/关 (CMD_SET_CW=0x13)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_CW, bytes([SET_ON if on else SET_OFF]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_query_params(self, dr: int = 0, m: int = 0, trext: int = 1,
                          sel: int = 0, session: int = 0, target: int = 0,
                          q: int = 4) -> bool:
        """设置 Query 参数 (CMD_SET_QUERY=0x05)

        dr: DR=8(0), DR=64/3(1)
        m: M=1(0), M=2(1), M=4(2), M=8(3)
        trext: no pilot(0), use pilot(1)
        sel: ALL(0/1), ~SL(2), SL(3)
        session: S0(0), S1(1), S2(2), S3(3)
        target: A(0), B(1)
        q: 0-15
        """
        if not self.is_connected():
            return False
        query_byte = (dr & 0x01) | ((m & 0x03) << 1) | ((trext & 0x01) << 3) | \
                     ((sel & 0x03) << 4) | ((session & 0x03) << 6)
        params = bytes([query_byte, target & 0x01, q & 0x0F])
        cmd = self._build_frame(CMD_SET_QUERY, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_select_params(self, target: int = 4, action: int = 0,
                           mem_bank: int = 1, pointer: int = 0x20,
                           mask_len: int = 0, mask: bytes = b'',
                           truncated: int = 0) -> bool:
        """设置 Select 参数 (CMD_SET_SELECT_PARA=0x16)

        target: S0(0), S1(1), S2(2), S3(3), SL(4)
        action: ref ISO18000-6C
        mem_bank: RFU(0), EPC(1), TID(2), USR(3)
        pointer: 32-bit start addr
        mask_len: mask 长度 (bits)
        """
        if not self.is_connected():
            return False
        target_action = ((target & 0x07) << 3) | (action & 0x07)
        params = bytes([target_action, mem_bank & 0x03]) + \
                 struct.pack('>I', pointer) + \
                 bytes([mask_len & 0xFF]) + mask + \
                 bytes([truncated & 0x01])
        cmd = self._build_frame(CMD_SET_SELECT_PARA, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_inventory_mode(self, mode: int) -> bool:
        """设置盘存模式 (CMD_SET_INVENTORY_MODE=0x18)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_INVENTORY_MODE, bytes([mode]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_modem_params(self, mixer_gain: int = 3, if_gain: int = 6,
                          signal_threshold: int = 120) -> bool:
        """设置 Modem 参数 (CMD_SET_MODEM_PARA=0x14)"""
        if not self.is_connected():
            return False
        params = bytes([mixer_gain & 0x07, if_gain & 0x07]) + struct.pack('>H', signal_threshold)
        cmd = self._build_frame(CMD_SET_MODEM_PARA, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_reader_env_mode(self, mode: int) -> bool:
        """设置环境模式: 0=高灵敏, 1=密集读卡器 (CMD_SET_READER_ENV_MODE=0x1C)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_READER_ENV_MODE, bytes([mode & 0x01]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def save_config_to_nv(self, enable: bool = True) -> bool:
        """保存配置到 NV Memory (CMD_SAVE_NV_CONFIG=0x21)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SAVE_NV_CONFIG, bytes([0x01 if enable else 0x00]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def load_config_from_nv(self) -> bool:
        """从 NV Memory 加载配置 (CMD_LOAD_NV_CONFIG=0x20)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_LOAD_NV_CONFIG)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def module_sleep(self) -> bool:
        """设置模块休眠 (CMD_SLEEP_MODE=0x1E)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SLEEP_MODE)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def set_sleep_time(self, minutes: int) -> bool:
        """设置空闲休眠时间 (CMD_SET_SLEEP_TIME=0x1F)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_SLEEP_TIME, bytes([minutes & 0xFF]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def scanner_restart(self) -> bool:
        """重启读卡器 (CMD_RESTART=0x22)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_RESTART)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def io_control(self, opt_type: int, io_port: int, mode_or_level: int) -> bool:
        """IO 控制 (CMD_IO_CONTROL=0x1B)

        opt_type: 0=set direction, 1=set level, 2=read level
        io_port: IO1-IO4 (1-4)
        mode_or_level: for opt=0: 0=input, 1=output; for opt=1: 0=low, 1=high
        """
        if not self.is_connected():
            return False
        params = bytes([opt_type & 0xFF, io_port & 0xFF, mode_or_level & 0xFF])
        cmd = self._build_frame(CMD_IO_CONTROL, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def get_module_info(self) -> Optional[str]:
        """获取模块信息"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_GET_MODULE_INFO, bytes([MODULE_HARDWARE_VERSION])))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_GET_MODULE_INFO:
                    return params.hex()
        return None

    # ═══════════════════════════════════════════════════════
    #  RF 信道 (CMD_SET_RF_CHANNEL=0x10, CMD_GET_RF_CHANNEL=0x11)
    # ═══════════════════════════════════════════════════════

    def set_rf_channel(self, channel: int) -> bool:
        """设置RF信道"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SET_RF_CHANNEL, bytes([channel & 0xFF]))
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def get_rf_channel(self) -> Optional[int]:
        """获取当前RF信道"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_GET_RF_CHANNEL))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_GET_RF_CHANNEL and len(params) >= 1:
                    return params[0]
        return None

    # ═══════════════════════════════════════════════════════
    #  Modem 参数 (CMD_READ_MODEM_PARA=0x15)
    # ═══════════════════════════════════════════════════════

    def get_modem_params(self) -> Optional[dict]:
        """读取Modem参数"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_READ_MODEM_PARA))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_READ_MODEM_PARA and len(params) >= 4:
                    return {
                        "mixer_gain": params[0],
                        "if_gain": params[1],
                        "signal_threshold": struct.unpack('>H', params[2:4])[0],
                    }
        return None

    # ═══════════════════════════════════════════════════════
    #  Select 参数 (CMD_GET_SELECT_PARA=0x17)
    # ═══════════════════════════════════════════════════════

    def get_select_params(self) -> Optional[dict]:
        """获取Select参数"""
        if not self.is_connected():
            return None
        with self._lock:
            self.serial.read(1000)
            self.serial.write(self._build_frame(CMD_GET_SELECT_PARA))
            frame = self._read_frame(timeout=2.0)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_ANSWER and fcmd == CMD_GET_SELECT_PARA:
                    target_action = params[0] if len(params) > 0 else 0
                    return {
                        "target": (target_action >> 3) & 0x07,
                        "action": target_action & 0x07,
                        "mem_bank": params[1] if len(params) > 1 else 0,
                        "pointer": struct.unpack('>I', params[2:6])[0] if len(params) >= 6 else 0,
                        "mask_len": params[6] if len(params) > 6 else 0,
                    }
        return None

    # ═══════════════════════════════════════════════════════
    #  干扰扫描 / RSSI (CMD_SCAN_JAMMER=0x19, CMD_SCAN_RSSI=0x1A)
    # ═══════════════════════════════════════════════════════

    def scan_jammer(self) -> bool:
        """扫描干扰"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SCAN_JAMMER)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def scan_rssi(self) -> bool:
        """扫描RSSI"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_SCAN_RSSI)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    # ═══════════════════════════════════════════════════════
    #  NXP G2X 特殊指令
    # ═══════════════════════════════════════════════════════

    def nxp_change_config(self, access_pwd: str, config_data: int) -> bool:
        """NXP G2X ChangeConfig (CMD_NXP_CHANGE_CONFIG=0x23)"""
        if not self.is_connected():
            return False
        pwd = bytes.fromhex(access_pwd) if len(access_pwd) == 8 else b'\x00\x00\x00\x00'
        params = pwd + struct.pack('>H', config_data & 0xFFFF)
        cmd = self._build_frame(CMD_NXP_CHANGE_CONFIG, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def nxp_read_protect(self, access_pwd: str, is_reset: bool = False) -> bool:
        """NXP G2X ReadProtect/ResetReadProtect (CMD_NXP_READPROTECT=0x24)"""
        if not self.is_connected():
            return False
        pwd = bytes.fromhex(access_pwd) if len(access_pwd) == 8 else b'\x00\x00\x00\x00'
        params = pwd + bytes([0x01 if is_reset else 0x00])
        cmd = self._build_frame(CMD_NXP_READPROTECT, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def nxp_change_eas(self, access_pwd: str, is_set: bool = True) -> bool:
        """NXP G2X ChangeEAS (CMD_NXP_CHANGE_EAS=0x25)"""
        if not self.is_connected():
            return False
        pwd = bytes.fromhex(access_pwd) if len(access_pwd) == 8 else b'\x00\x00\x00\x00'
        params = pwd + bytes([0x01 if is_set else 0x00])
        cmd = self._build_frame(CMD_NXP_CHANGE_EAS, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    def nxp_eas_alarm(self) -> bool:
        """NXP G2X EAS Alarm (CMD_NXP_EAS_ALARM=0x26)"""
        if not self.is_connected():
            return False
        cmd = self._build_frame(CMD_NXP_EAS_ALARM)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    # ═══════════════════════════════════════════════════════
    #  Monza QT (CMD_MONZA_QT_READ=0x27, CMD_MONZA_QT_WRITE=0x28)
    # ═══════════════════════════════════════════════════════

    def monza_qt(self, access_pwd: str, is_write: bool = False,
                  qt_sr: bool = False, qt_mem: bool = False,
                  is_persistence: bool = True) -> bool:
        """Monza QT Read/Write"""
        if not self.is_connected():
            return False
        pwd = bytes.fromhex(access_pwd) if len(access_pwd) == 8 else b'\x00\x00\x00\x00'
        ctrl = 0
        if qt_sr:
            ctrl |= 0x80
        if qt_mem:
            ctrl |= 0x40
        if is_persistence:
            ctrl |= 0x20
        params = pwd + bytes([ctrl])
        cmd_code = CMD_MONZA_QT_WRITE if is_write else CMD_MONZA_QT_READ
        cmd = self._build_frame(cmd_code, params)
        self.serial.write(cmd)
        time.sleep(0.3)
        return True

    # ═══════════════════════════════════════════════════════
    #  缓存与连续扫描
    # ═══════════════════════════════════════════════════════

    def get_last_tags(self) -> List[RFIDTag]:
        with self._lock:
            return list(self._last_tags.values())

    def clear_last_tags(self):
        with self._lock:
            self._last_tags.clear()

    def start_continuous_scan(self):
        """启动连续扫描后台线程"""
        if self._running:
            logger.warning("[RFID] 连续扫描已在运行")
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
        if self.serial and self.serial.is_connected:
            try:
                self.serial.write(self._build_frame(CMD_STOP_MULTI))
            except Exception:
                pass
        logger.info("[RFID] 连续扫描已停止")

    def _scan_loop(self):
        """后台扫描循环 — 发送多次盘存(loop=0=无限), 持续接收通知帧"""
        if self.is_connected():
            count_bytes = struct.pack('>H', 0)
            self.serial.write(self._build_frame(CMD_READ_MULTI, count_bytes))

        while self._running:
            if not self.is_connected():
                time.sleep(1.0)
                continue

            frame = self._read_frame(timeout=self.config.scan_interval)
            if frame:
                ftype, fcmd, params = self._parse_response(frame)
                if ftype == TYPE_INFO and fcmd == CMD_INVENTORY:
                    tag = self._parse_inventory_response(params)
                    if tag:
                        with self._lock:
                            is_new = tag.tag_id not in self._last_tags
                            self._last_tags[tag.tag_id] = tag
                        # 记录到扫描历史（每次读取都记，不区分是否为新标签）
                        self._append_scan_history(tag, mode="auto")
                        if is_new and self.on_tag_detected:
                            try:
                                self.on_tag_detected(tag)
                            except Exception as e:
                                logger.error(f"[RFID] 回调异常: {e}")

    def get_connection_info(self) -> dict:
        return {
            "connected": self.is_connected(),
            "port": self._auto_detected_port or (self.config.port if self.config.port != "auto" else None),
            "baudrate": self.config.baudrate,
            "last_tags_count": len(self._last_tags),
            "scanning": self._running,
            "protocol": "PRE-E720 (binary, V2.2)",
        }


# ═══════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════
_reader_instance: Optional[RFIDReader] = None
_instance_lock = threading.Lock()


def get_rfid_reader(config: Optional[RFIDConfig] = None) -> RFIDReader:
    """获取全局 RFID 读卡器单例"""
    global _reader_instance
    with _instance_lock:
        if _reader_instance is None:
            _reader_instance = RFIDReader(config)
        return _reader_instance