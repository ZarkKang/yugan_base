#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import math
import os
import threading
import time
from collections import OrderedDict

import requests
import rospy
import yaml
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from std_msgs.msg import String


class UAVGroundBridge:
    def __init__(self):
        self.ground_url = rospy.get_param("~ground_url", "http://192.168.1.100:8001").rstrip("/")
        self.drone_code = rospy.get_param("~drone_code", "DRONE001")
        self.rfid_topic = rospy.get_param("~rfid_topic", "/rfid/tags")
        self.odom_topic = rospy.get_param("~odom_topic", "/Odometry")
        self.odom_type = rospy.get_param("~odom_type", "auto")
        self.battery_topic = rospy.get_param("~battery_topic", "/mavros/battery")
        self.waypoints_file = rospy.get_param("~waypoints_file", "")
        self.heartbeat_interval = float(rospy.get_param("~heartbeat_interval", 5.0))
        self.arrival_radius = float(rospy.get_param("~arrival_radius", 0.3))
        self.arrival_hold_time = float(rospy.get_param("~arrival_hold_time", 2.0))
        self.rfid_window = float(rospy.get_param("~rfid_window", 5.0))
        self.enable_waypoint_monitor = bool(rospy.get_param("~enable_waypoint_monitor", True))
        self.video_stream = rospy.get_param("~video_stream", "udp://@:5600")

        self.position = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.has_position = False
        self.battery_percent = -1
        self.status = "idle"

        self.lock = threading.Lock()
        self.recent_tags = OrderedDict()

        self.task_code = "TASK001"
        self.waypoints = []
        self.current_wp_index = 0
        self.arrival_start_time = None
        self.scan_start_time = None
        self.scan_tags = OrderedDict()

        package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.log_dir = os.path.join(package_root, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.failed_log = os.path.join(self.log_dir, "uav_ground_bridge_failed.jsonl")

        self.load_waypoints()
        self.setup_subscribers()

        self.heartbeat_timer = rospy.Timer(rospy.Duration(self.heartbeat_interval), self.heartbeat_cb)
        self.state_timer = rospy.Timer(rospy.Duration(0.2), self.state_cb)

        rospy.logwarn("[uav_ground_bridge] started ground_url=%s drone_code=%s", self.ground_url, self.drone_code)
        rospy.logwarn("[uav_ground_bridge] rfid_topic=%s odom_topic=%s odom_type=%s", self.rfid_topic, self.odom_topic, self.odom_type)
        rospy.logwarn("[uav_ground_bridge] loaded %d waypoints", len(self.waypoints))

    def setup_subscribers(self):
        rospy.Subscriber(self.rfid_topic, String, self.rfid_cb, queue_size=50)

        normalized_type = str(self.odom_type).strip()
        if normalized_type == "auto":
            normalized_type = "geometry_msgs/PoseStamped" if "local_position/pose" in self.odom_topic else "nav_msgs/Odometry"

        if normalized_type in ("geometry_msgs/PoseStamped", "PoseStamped"):
            rospy.Subscriber(self.odom_topic, PoseStamped, self.pose_cb, queue_size=10)
        else:
            rospy.Subscriber(self.odom_topic, Odometry, self.odom_cb, queue_size=10)

        rospy.Subscriber(self.battery_topic, BatteryState, self.battery_cb, queue_size=10)

    def load_waypoints(self):
        if not self.waypoints_file or not os.path.exists(self.waypoints_file):
            rospy.logwarn("[uav_ground_bridge] waypoint file not found: %s", self.waypoints_file)
            self.waypoints = []
            return

        with open(self.waypoints_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.task_code = data.get("task_code", "TASK001")
        self.waypoints = data.get("waypoints", []) or []

    def rfid_cb(self, msg):
        try:
            data = json.loads(msg.data)
            epc = data.get("epc")
            if not epc:
                return

            now = time.time()
            item = {
                "epc": epc,
                "rssi_dbm": data.get("rssi_dbm"),
                "pc": data.get("pc"),
                "crc": data.get("crc"),
                "stamp": data.get("stamp", now),
                "received_at": now,
            }

            with self.lock:
                self.recent_tags[epc] = item
                self.scan_tags[epc] = item
                self.cleanup_tags_locked(now)

        except Exception as exc:
            rospy.logwarn_throttle(2.0, "[uav_ground_bridge] bad RFID message: %s", exc)

    def cleanup_tags_locked(self, now):
        old_keys = []
        for epc, item in self.recent_tags.items():
            if now - float(item.get("received_at", now)) > self.rfid_window:
                old_keys.append(epc)
        for key in old_keys:
            self.recent_tags.pop(key, None)

    def odom_cb(self, msg):
        with self.lock:
            self.position = {
                "x": float(msg.pose.pose.position.x),
                "y": float(msg.pose.pose.position.y),
                "z": float(msg.pose.pose.position.z),
            }
            self.has_position = True

    def pose_cb(self, msg):
        with self.lock:
            self.position = {
                "x": float(msg.pose.position.x),
                "y": float(msg.pose.position.y),
                "z": float(msg.pose.position.z),
            }
            self.has_position = True

    def battery_cb(self, msg):
        try:
            pct = msg.percentage
            if pct is not None and pct >= 0:
                self.battery_percent = int(max(0, min(100, pct * 100)))
        except Exception:
            pass

    def heartbeat_cb(self, _event):
        with self.lock:
            body = {
                "drone_code": self.drone_code,
                "status": self.status,
                "battery": self.battery_percent,
                "position": dict(self.position),
                "timestamp": time.time(),
            }
        self.post_json_async(
            "%s/api/v1/drones/%s/heartbeat" % (self.ground_url, self.drone_code),
            body,
            kind="heartbeat",
        )

    def state_cb(self, _event):
        if not self.enable_waypoint_monitor or not self.waypoints:
            return

        with self.lock:
            if self.current_wp_index >= len(self.waypoints):
                self.status = "completed"
                return

            now = time.time()
            pos = dict(self.position)
            wp = self.waypoints[self.current_wp_index]
            dist = self.distance(pos, wp)

            if self.status in ["idle", "running", "approaching"]:
                self.status = "approaching"
                if dist <= self.arrival_radius:
                    if self.arrival_start_time is None:
                        self.arrival_start_time = now
                    elif now - self.arrival_start_time >= self.arrival_hold_time:
                        self.status = "scanning"
                        self.scan_start_time = now
                        self.scan_tags = OrderedDict()
                        rospy.logwarn("[uav_ground_bridge] arrived waypoint id=%s, start scanning", wp.get("id"))
                else:
                    self.arrival_start_time = None

            elif self.status == "scanning":
                dwell_time = float(wp.get("dwell_time", self.rfid_window))
                if self.scan_start_time is not None and now - self.scan_start_time >= dwell_time:
                    tags = list(self.scan_tags.values())
                    self.status = "uploading"
                    self.upload_waypoint_result(wp, pos, tags)
                    self.current_wp_index += 1
                    self.arrival_start_time = None
                    self.scan_start_time = None
                    self.scan_tags = OrderedDict()
                    self.status = "running" if self.current_wp_index < len(self.waypoints) else "completed"

    def distance(self, pos, wp):
        dx = float(pos.get("x", 0.0)) - float(wp.get("x", 0.0))
        dy = float(pos.get("y", 0.0)) - float(wp.get("y", 0.0))
        dz = float(pos.get("z", 0.0)) - float(wp.get("z", 0.0))
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def upload_waypoint_result(self, wp, pos, tags):
        compact_tags = []
        for tag in tags:
            compact_tags.append({
                "epc": tag.get("epc"),
                "rssi_dbm": tag.get("rssi_dbm"),
                "stamp": tag.get("stamp"),
            })

        body = {
            "drone_code": self.drone_code,
            "data_type": "rfid",
            "payload": json.dumps(compact_tags, ensure_ascii=False),
            "position_x": pos.get("x", 0.0),
            "position_y": pos.get("y", 0.0),
            "position_z": pos.get("z", 0.0),
            "metadata": {
                "task_code": self.task_code,
                "waypoint_id": wp.get("id"),
                "event": "waypoint_completed",
                "video_stream": self.video_stream,
                "battery": self.battery_percent,
                "timestamp": time.time(),
            },
        }

        rospy.logwarn("[uav_ground_bridge] upload waypoint id=%s tags=%d", wp.get("id"), len(compact_tags))
        self.post_json_async(
            "%s/api/v1/gateway/receive" % self.ground_url,
            body,
            kind="waypoint_result",
        )

    def post_json_async(self, url, body, kind):
        thread = threading.Thread(target=self.post_json, args=(url, body, kind))
        thread.daemon = True
        thread.start()

    def post_json(self, url, body, kind):
        try:
            response = requests.post(url, json=body, timeout=1.5)
            if response.status_code >= 300:
                raise RuntimeError("HTTP %s: %s" % (response.status_code, response.text[:300]))
            rospy.loginfo("[uav_ground_bridge] posted %s ok", kind)
        except Exception as exc:
            rospy.logwarn_throttle(2.0, "[uav_ground_bridge] post %s failed: %s", kind, exc)
            self.write_failed(kind, url, body, str(exc))

    def write_failed(self, kind, url, body, error):
        record = {
            "kind": kind,
            "url": url,
            "body": body,
            "error": error,
            "time": time.time(),
        }
        try:
            with open(self.failed_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass


def main():
    rospy.init_node("uav_ground_bridge")
    UAVGroundBridge()
    rospy.spin()


if __name__ == "__main__":
    main()
