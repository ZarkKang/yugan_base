#!/usr/bin/env python3
"""
无人机端设备信息上报脚本
======================
在无人机 NX 启动时运行，向地面基站上报设备身份信息。
基站存储后，验证向导可通过 passive 模式查询，无需直接连接无人机。

使用方式:
    python3 report_device_info.py --ground-url http://192.168.1.100:8001 --drone-code DRONE001

可集成到 uav_ground_bridge 的 launch 文件中作为启动节点。
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ── 设备信息采集 ────────────────────────────────────

def get_device_model():
    """获取设备型号"""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read().strip("\x00").strip()
    except FileNotFoundError:
        pass
    # 尝试读取 Jetson 信息
    try:
        result = subprocess.run(
            ["cat", "/etc/nv_tegra_release"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return f"NVIDIA Jetson ({result.stdout.strip()[:50]})"
    except Exception:
        pass
    return "NVIDIA Jetson NX"


def get_firmware_version():
    """获取固件/系统版本"""
    try:
        result = subprocess.run(
            ["lsb_release", "-ds"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip().strip('"')
    except Exception:
        pass
    return platform.platform()


def get_ros_version():
    """获取 ROS 版本"""
    try:
        result = subprocess.run(
            ["rosversion", "-d"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get("ROS_DISTRO", "unknown")


def get_cpu_info():
    """获取 CPU 信息"""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line or "Processor" in line:
                    return line.split(":")[1].strip()
    except Exception:
        pass
    return platform.processor()


def get_memory_mb():
    """获取内存大小 (MB)"""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    return int(line.split(":")[1].strip().split()[0]) // 1024
    except Exception:
        pass
    return None


def get_ip_address():
    """获取 eth1 网卡 IP 地址"""
    try:
        import socket
        import fcntl
        import struct
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ip = socket.inet_ntoa(
            fcntl.ioctl(
                sock.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack("256s", b"eth1")
            )[20:24]
        )
        return ip
    except Exception:
        pass
    return "192.168.1.201"


# ── 上报逻辑 ────────────────────────────────────────

def report_device_info(
    ground_url: str,
    drone_code: str,
    ip_address: str,
    device_model: str = None,
    manufacturer: str = "NVIDIA",
    firmware_version: str = None,
    supported_protocols: str = "HTTP",
    port: int = 8080,
    ros_version: str = None,
    os_version: str = None,
    cpu_info: str = None,
    memory_mb: int = None,
    retry_count: int = 3,
    retry_delay: float = 2.0,
):
    """向地面基站上报设备信息"""
    url = f"{ground_url}/api/warehouse/drone-integration/device/report"

    # 自动采集未提供的参数
    if device_model is None:
        device_model = get_device_model()
    if firmware_version is None:
        firmware_version = get_firmware_version()
    if ros_version is None:
        ros_version = get_ros_version()
    if os_version is None:
        os_version = platform.platform()
    if cpu_info is None:
        cpu_info = get_cpu_info()
    if memory_mb is None:
        memory_mb = get_memory_mb()

    params = {
        "drone_code": drone_code,
        "ip_address": ip_address,
        "device_model": device_model,
        "manufacturer": manufacturer,
        "firmware_version": firmware_version,
        "supported_protocols": supported_protocols,
        "port": port,
        "ros_version": ros_version,
        "os_version": os_version,
        "cpu_info": cpu_info,
        "memory_mb": memory_mb,
    }

    # 构建查询字符串
    query_parts = []
    for key, value in params.items():
        if value is not None:
            query_parts.append(f"{key}={value}")
    query_string = "&".join(query_parts)
    full_url = f"{url}?{query_string}"

    print(f"[DeviceReport] 上报设备信息到: {full_url}")
    print(f"[DeviceReport] 设备型号: {device_model}")
    print(f"[DeviceReport] 固件版本: {firmware_version}")
    print(f"[DeviceReport] ROS 版本: {ros_version}")

    for attempt in range(1, retry_count + 1):
        try:
            req = Request(full_url, method="POST")
            req.add_header("Content-Type", "application/json")
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if resp.status == 200 and data.get("success"):
                    print(f"[DeviceReport] 上报成功 (attempt {attempt})")
                    print(f"[DeviceReport] 响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
                    return True
                else:
                    print(f"[DeviceReport] 上报失败: {data.get('message', 'unknown error')}")
        except (URLError, HTTPError) as e:
            print(f"[DeviceReport] 上报异常 (attempt {attempt}/{retry_count}): {e}")
        except Exception as e:
            print(f"[DeviceReport] 未知错误: {e}")

        if attempt < retry_count:
            print(f"[DeviceReport] {retry_delay}s 后重试...")
            time.sleep(retry_delay)

    print("[DeviceReport] 上报最终失败，请检查基站是否运行")
    return False


# ── 主入口 ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="无人机设备信息上报")
    parser.add_argument("--ground-url", default="http://192.168.1.100:8001", help="地面基站URL")
    parser.add_argument("--drone-code", default="DRONE001", help="无人机编号")
    parser.add_argument("--ip-address", default=None, help="设备IP (默认自动检测eth1)")
    parser.add_argument("--device-model", default=None, help="设备型号 (默认自动检测)")
    parser.add_argument("--manufacturer", default="NVIDIA", help="制造商")
    parser.add_argument("--firmware-version", default=None, help="固件版本 (默认自动检测)")
    parser.add_argument("--supported-protocols", default="HTTP", help="支持的协议，逗号分隔")
    parser.add_argument("--port", type=int, default=8080, help="HTTP服务端口")
    parser.add_argument("--retry-count", type=int, default=3, help="重试次数")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="重试间隔(秒)")

    args = parser.parse_args()

    ip_address = args.ip_address or get_ip_address()

    success = report_device_info(
        ground_url=args.ground_url,
        drone_code=args.drone_code,
        ip_address=ip_address,
        device_model=args.device_model,
        manufacturer=args.manufacturer,
        firmware_version=args.firmware_version,
        supported_protocols=args.supported_protocols,
        port=args.port,
        retry_count=args.retry_count,
        retry_delay=args.retry_delay,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()