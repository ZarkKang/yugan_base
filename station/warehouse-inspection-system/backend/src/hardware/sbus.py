"""
硬件通信模块 - SBUS协议
"""
from typing import Optional, Dict, List
from dataclasses import dataclass
import struct
import logging

logger = logging.getLogger(__name__)


@dataclass
class SBUSChannel:
    """SBUS通道数据"""
    channel: int
    value: int  # 范围: 172-1811


@dataclass
class SBUSFrame:
    """SBUS数据帧"""
    channels: List[int]  # 16个通道，范围172-1811
    digital_channel_1: bool = False  # Ch17
    digital_channel_2: bool = False  # Ch18
    frame_lost: bool = False
    failsafe: bool = False


class SBUSDecoder:
    """SBUS协议解码器"""

    SBUS_FRAME_LENGTH = 25
    SBUS_HEADER = 0x0F
    SBUS_FOOTER = 0x00

    def __init__(self):
        self._buffer = bytearray()

    def decode(self, data: bytes) -> Optional[SBUSFrame]:
        """
        解码SBUS数据帧

        Args:
            data: 原始字节数据

        Returns:
            SBUSFrame对象或None
        """
        self._buffer.extend(data)

        while len(self._buffer) >= self.SBUS_FRAME_LENGTH:
            # 查找帧头
            header_index = -1
            for i in range(len(self._buffer) - self.SBUS_FRAME_LENGTH + 1):
                if self._buffer[i] == self.SBUS_HEADER:
                    header_index = i
                    break

            if header_index == -1:
                # 没有找到帧头，保留最后几个字节
                self._buffer = self._buffer[-2:]
                return None

            if header_index > 0:
                # 丢弃帧头前的数据
                self._buffer = self._buffer[header_index:]

            if len(self._buffer) < self.SBUS_FRAME_LENGTH:
                return None

            frame_data = bytes(self._buffer[:self.SBUS_FRAME_LENGTH])
            self._buffer = self._buffer[self.SBUS_FRAME_LENGTH:]

            return self._parse_frame(frame_data)

        return None

    def _parse_frame(self, frame: bytes) -> Optional[SBUSFrame]:
        """解析单帧SBUS数据"""
        if frame[0] != self.SBUS_HEADER or frame[-1] != self.SBUS_FOOTER:
            return None

        try:
            # SBUS协议采用小端序存储16位通道值
            channels = []
            for i in range(16):
                # 每个通道占11位
                byte_index = 1 + i * 11 // 8
                bit_offset = (i * 11) % 8

                low_byte = frame[byte_index]
                high_byte = frame[byte_index + 1] if byte_index + 1 < 24 else 0

                value = ((high_byte << 8) | low_byte) >> bit_offset & 0x7FF
                channels.append(value)

            # 数字通道和状态标志
            flags = frame[23]
            digital_channel_1 = bool(flags & (1 << 0))
            digital_channel_2 = bool(flags & (1 << 1))
            frame_lost = bool(flags & (1 << 2))
            failsafe = bool(flags & (1 << 3))

            return SBUSFrame(
                channels=channels,
                digital_channel_1=digital_channel_1,
                digital_channel_2=digital_channel_2,
                frame_lost=frame_lost,
                failsafe=failsafe
            )
        except Exception as e:
            logger.error(f"SBUS帧解析错误: {e}")
            return None


class SBUSEncoder:
    """SBUS协议编码器"""

    def encode(self, frame: SBUSFrame) -> bytes:
        """
        编码SBUS数据帧

        Args:
            frame: SBUSFrame对象

        Returns:
            编码后的字节数据
        """
        data = bytearray(self.SBUS_FRAME_LENGTH)
        data[0] = self.SBUS_HEADER

        # 编码16个通道
        for i in range(16):
            value = max(172, min(1811, frame.channels[i]))
            byte_index = 1 + i * 11 // 8
            bit_offset = (i * 11) % 8

            # 清除原值
            if byte_index < 24:
                data[byte_index] &= ~(0x7FF >> bit_offset)
                data[byte_index] |= (value & 0x7FF) << bit_offset
            if byte_index + 1 < 24:
                data[byte_index + 1] &= ~(0x7FF << (8 - bit_offset))

        # 编码标志位
        flags = 0
        if frame.digital_channel_1:
            flags |= 1 << 0
        if frame.digital_channel_2:
            flags |= 1 << 1
        if frame.frame_lost:
            flags |= 1 << 2
        if frame.failsafe:
            flags |= 1 << 3
        data[23] = flags

        # 帧尾
        data[24] = self.SBUS_FOOTER

        return bytes(data)


class SBUSProcessor:
    """SBUS数据处理器"""

    def __init__(self):
        self.decoder = SBUSDecoder()
        self.encoder = SBUSEncoder()

    def process_incoming(self, data: bytes) -> Optional[SBUSFrame]:
        """处理传入的SBUS数据"""
        return self.decoder.decode(data)

    def create_frame(self, channels: List[int],
                     digital_ch1: bool = False,
                     digital_ch2: bool = False) -> SBUSFrame:
        """创建SBUS帧"""
        if len(channels) != 16:
            raise ValueError("SBUS需要16个通道")
        return SBUSFrame(
            channels=channels,
            digital_channel_1=digital_ch1,
            digital_channel_2=digital_ch2
        )

    def frame_to_bytes(self, frame: SBUSFrame) -> bytes:
        """将SBUS帧转换为字节"""
        return self.encoder.encode(frame)
