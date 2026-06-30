#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS node for E720 UHF RFID reader.
Publishes JSON strings on /rfid/tags, e.g.:
{"epc":"30751FEB705C5904E3D50D70","rssi_dbm":-55,"pc":"3400","crc":"3A76","stamp":1710000000.123}
"""
import json
import threading
import time
from typing import Dict, List, Optional

import rospy
from std_msgs.msg import String

try:
    import serial
except ImportError as exc:  # pragma: no cover
    raise SystemExit("python3-serial is required: sudo apt install python3-serial") from exc

HEADER = 0xBB
END = 0x7E
TYPE_CMD = 0x00
TYPE_RESP = 0x01
TYPE_NOTIFY = 0x02
CMD_INFO = 0x03
CMD_SINGLE_INVENTORY = 0x22
CMD_MULTI_INVENTORY = 0x27
CMD_STOP_MULTI = 0x28
CMD_SET_POWER = 0xB6
CMD_GET_POWER = 0xB7
CMD_ERROR = 0xFF


def checksum(frame_type: int, command: int, payload: bytes) -> int:
    length = len(payload)
    return (frame_type + command + ((length >> 8) & 0xFF) + (length & 0xFF) + sum(payload)) & 0xFF


def make_frame(command: int, payload: bytes = b"") -> bytes:
    length = len(payload)
    body = bytes([TYPE_CMD, command, (length >> 8) & 0xFF, length & 0xFF]) + payload
    return bytes([HEADER]) + body + bytes([checksum(TYPE_CMD, command, payload), END])


def signed_byte(value: int) -> int:
    return value - 256 if value >= 128 else value


class E720Node:
    def __init__(self):
        self.port = rospy.get_param("~port", "/dev/rfid_e720")
        self.baud = int(rospy.get_param("~baud", 115200))
        self.power_dbm = int(rospy.get_param("~power_dbm", 20))
        self.inventory_count = int(rospy.get_param("~inventory_count", 65535))
        self.auto_start = bool(rospy.get_param("~auto_start", True))
        self.dedup_seconds = float(rospy.get_param("~dedup_seconds", 0.5))
        self.read_timeout = float(rospy.get_param("~read_timeout", 0.05))

        self.pub = rospy.Publisher("/rfid/tags", String, queue_size=50)
        self.raw_pub = rospy.Publisher("/rfid/raw_frames", String, queue_size=20)
        self.last_seen: Dict[str, float] = {}
        self.lock = threading.Lock()
        self.running = True

        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.read_timeout)
            rospy.logwarn("[e720_rfid] opened %s @ %d", self.port, self.baud)

            self.set_power(self.power_dbm)
            if self.auto_start:
                self.start_inventory(self.inventory_count)
        except serial.SerialException as exc:
            rospy.logerr("[e720_rfid] failed to open %s: %s", self.port, exc)
            raise

    def send(self, frame: bytes):
        with self.lock:
            self.ser.write(frame)
            self.ser.flush()
        rospy.logdebug("[e720_rfid] TX %s", frame.hex(" ").upper())

    def set_power(self, dbm: int):
        dbm = max(5, min(28, int(dbm)))
        value = dbm * 100
        self.send(make_frame(CMD_SET_POWER, bytes([(value >> 8) & 0xFF, value & 0xFF])))
        rospy.logwarn("[e720_rfid] set power to %d dBm", dbm)

    def single_inventory(self):
        self.send(make_frame(CMD_SINGLE_INVENTORY))

    def start_inventory(self, count: int):
        count = max(0, min(65535, int(count)))
        payload = bytes([0x22, (count >> 8) & 0xFF, count & 0xFF])
        self.send(make_frame(CMD_MULTI_INVENTORY, payload))
        rospy.logwarn("[e720_rfid] start inventory count=%d", count)

    def stop_inventory(self):
        self.send(make_frame(CMD_STOP_MULTI))
        rospy.logwarn("[e720_rfid] stop inventory")

    def read_frame(self) -> Optional[bytes]:
        # Sync to header.
        while not rospy.is_shutdown() and self.running:
            b = self.ser.read(1)
            if not b:
                return None
            if b[0] == HEADER:
                break

        head = self.ser.read(4)  # type, command, len_msb, len_lsb
        if len(head) != 4:
            return None
        frame_type, command, len_msb, len_lsb = head
        payload_len = (len_msb << 8) | len_lsb
        payload = self.ser.read(payload_len)
        tail = self.ser.read(2)  # checksum, end
        if len(payload) != payload_len or len(tail) != 2:
            return None
        frame = bytes([HEADER]) + head + payload + tail
        got_checksum, got_end = tail
        calc = checksum(frame_type, command, payload)
        if got_end != END:
            rospy.logwarn_throttle(1.0, "[e720_rfid] bad frame end: %s", frame.hex(" ").upper())
            return None
        if got_checksum != calc:
            rospy.logwarn_throttle(1.0, "[e720_rfid] bad checksum got=%02X calc=%02X frame=%s", got_checksum, calc, frame.hex(" ").upper())
            return None
        return frame

    def handle_frame(self, frame: bytes):
        frame_type = frame[1]
        command = frame[2]
        payload_len = (frame[3] << 8) | frame[4]
        payload = frame[5:5 + payload_len]
        self.raw_pub.publish(String(data=frame.hex(" ").upper()))

        if frame_type == TYPE_NOTIFY and command == CMD_SINGLE_INVENTORY and payload_len >= 5:
            rssi = signed_byte(payload[0])
            pc = payload[1:3].hex().upper()
            epc = payload[3:-2].hex().upper()
            crc = payload[-2:].hex().upper()
            now = time.time()
            last = self.last_seen.get(epc, 0.0)
            if now - last >= self.dedup_seconds:
                self.last_seen[epc] = now
                msg = {
                    "epc": epc,
                    "rssi_dbm": rssi,
                    "pc": pc,
                    "crc": crc,
                    "stamp": rospy.Time.now().to_sec(),
                }
                self.pub.publish(String(data=json.dumps(msg, ensure_ascii=False)))
                rospy.loginfo("[e720_rfid] EPC=%s RSSI=%d dBm", epc, rssi)
            return

        if frame_type == TYPE_RESP and command == CMD_ERROR and payload_len >= 1:
            if payload[0] != 0x15:
                rospy.logwarn_throttle(1.0, "[e720_rfid] reader error code=0x%02X", payload[0])
            return

        rospy.logdebug("[e720_rfid] RX %s", frame.hex(" ").upper())

    def spin(self):
        while not rospy.is_shutdown() and self.running:
            frame = self.read_frame()
            if frame:
                self.handle_frame(frame)

    def close(self):
        self.running = False
        try:
            self.stop_inventory()
            time.sleep(0.1)
        except Exception:
            pass
        try:
            self.ser.close()
        except Exception:
            pass


def main():
    rospy.init_node("e720_rfid")
    node = None
    try:
        node = E720Node()
        node.spin()
    except serial.SerialException as exc:
        rospy.logerr("[e720_rfid] serial error: %s", exc)
    finally:
        if node is not None:
            node.close()


if __name__ == "__main__":
    main()
