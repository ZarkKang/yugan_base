#!/usr/bin/env python3
"""
无人机端轻量 HTTP 服务端 (方案B)
==============================
为地面基站验证向导提供后向兼容的 HTTP 服务端点。
监听 192.168.1.201:8080，响应设备身份查询请求。

使用方式:
    python3 drone_http_server.py --port 8080

可集成到 uav_ground_bridge launch 文件中作为独立节点运行。
注意: 此脚本仅用于响应基站的主动验证请求，不影响现有数据上报功能。
"""

import argparse
import json
import os
import platform
import signal
import subprocess
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# ── 设备信息采集 ────────────────────────────────────

def collect_device_info():
    """采集完整的设备信息"""
    info = {
        "model": "NVIDIA Jetson NX",
        "manufacturer": "NVIDIA",
        "firmware_version": platform.platform(),
        "protocols": ["HTTP"],
        "ros_version": os.environ.get("ROS_DISTRO", "noetic"),
        "os_version": platform.platform(),
        "cpu_info": platform.processor(),
        "memory_mb": None,
        "hostname": platform.node(),
        "timestamp": datetime.utcnow().isoformat(),
    }

    # 获取 Jetson 型号
    try:
        with open("/proc/device-tree/model", "r") as f:
            info["model"] = f.read().strip("\x00").strip()
    except FileNotFoundError:
        pass

    # 获取系统版本
    try:
        result = subprocess.run(
            ["lsb_release", "-ds"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            info["firmware_version"] = result.stdout.strip().strip('"')
    except Exception:
        pass

    # 获取内存
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    info["memory_mb"] = int(line.split(":")[1].strip().split()[0]) // 1024
                    break
    except Exception:
        pass

    return info


# ── HTTP 请求处理器 ─────────────────────────────────

class DroneHTTPHandler(BaseHTTPRequestHandler):
    """处理基站验证请求"""

    device_info = collect_device_info()

    def log_message(self, format, *args):
        print(f"[DroneServer] {self.client_address[0]} - {format % args}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def do_GET(self):
        """处理 GET 请求"""
        if self.path in ("/", "/health"):
            self._send_json({
                "status": "ok",
                "service": "uav_drone_http_server",
                "timestamp": datetime.utcnow().isoformat(),
            })

        elif self.path in ("/api/device/info", "/api/info", "/info",
                           "/api/v1/device/info", "/status", "/api/status"):
            self._send_json(self.device_info)

        else:
            self._send_json({"error": "not found", "path": self.path}, status=404)

    def do_POST(self):
        """处理 POST 请求"""
        if self.path in ("/api/device/info", "/api/info"):
            self._send_json(self.device_info)
        else:
            self._send_json({"error": "not found", "path": self.path}, status=404)

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


# ── 主入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="无人机端 HTTP 服务端")
    parser.add_argument("--port", type=int, default=8080, help="监听端口 (默认: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DroneHTTPHandler)

    def shutdown_handler(signum, frame):
        print(f"\n[DroneServer] 收到信号 {signum}, 正在关闭...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print(f"[DroneServer] 无人机 HTTP 服务端已启动")
    print(f"[DroneServer] 监听地址: http://{args.host}:{args.port}")
    print(f"[DroneServer] 设备型号: {DroneHTTPHandler.device_info['model']}")
    print(f"[DroneServer] 可用端点:")
    print(f"  GET  /health              → 健康检查")
    print(f"  GET  /api/device/info     → 设备信息")
    print(f"  GET  /api/info            → 设备信息")
    print(f"  GET  /status              → 设备状态")
    print(f"[DroneServer] 按 Ctrl+C 停止")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[DroneServer] 已停止")


if __name__ == "__main__":
    main()