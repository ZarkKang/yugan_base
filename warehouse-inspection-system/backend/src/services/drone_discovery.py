"""
无人机设备发现服务 — 扫描192.168.1.x网段，识别无人机图传设备
"""
import json
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from ..core.network import scan_subnet, scan_ports, ping, check_connectivity
from ..db.database import SessionLocal
from ..models.models import NetworkScanResult

logger = logging.getLogger(__name__)

# 无人机图传设备特征端口
DRONE_TRANSMITTER_PORTS = [554, 8554, 8080, 8000, 1935, 1883]
# 基站特征端口
BASE_STATION_PORTS = [8080, 8001, 8000, 1883]


def discover_devices(
    subnet: str = "192.168.1",
    scan_ports_list: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    扫描子网，发现所有设备并分类。

    Args:
        subnet: 子网前缀，默认 "192.168.1"
        scan_ports_list: 要扫描的端口列表

    Returns:
        扫描结果字典，包含发现的设备列表和统计信息
    """
    if scan_ports_list is None:
        scan_ports_list = DRONE_TRANSMITTER_PORTS + BASE_STATION_PORTS

    scan_id = f"scan_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
    logger.info(f"[Discovery] 开始扫描子网 {subnet}.x, 扫描ID: {scan_id}")

    # 执行子网扫描
    raw_results = scan_subnet(subnet, ports=scan_ports_list)

    # 分类设备
    drone_transmitters = []
    base_stations = []
    unknown_devices = []

    for device in raw_results:
        open_port_numbers = [p["port"] for p in device["open_ports"]]
        device_type = _classify_device(device["ip"], open_port_numbers)

        device_entry = {
            "ip": device["ip"],
            "hostname": device["hostname"],
            "ping_ms": device["ping_ms"],
            "open_ports": device["open_ports"],
            "device_type": device_type,
        }

        if device_type == "drone_transmitter":
            drone_transmitters.append(device_entry)
        elif device_type == "base_station":
            base_stations.append(device_entry)
        else:
            unknown_devices.append(device_entry)

    # 保存扫描结果到数据库
    _save_scan_results(scan_id, raw_results)

    result = {
        "scan_id": scan_id,
        "subnet": f"{subnet}.0/24",
        "total_hosts": len(raw_results),
        "drone_transmitters": drone_transmitters,
        "drone_transmitter_count": len(drone_transmitters),
        "base_stations": base_stations,
        "base_station_count": len(base_stations),
        "unknown_devices": unknown_devices,
        "unknown_count": len(unknown_devices),
        "scanned_at": datetime.utcnow().isoformat(),
    }

    logger.info(f"[Discovery] 扫描完成: {len(drone_transmitters)} 台无人机图传设备, "
                f"{len(base_stations)} 台基站, {len(unknown_devices)} 台未知设备")

    return result


def identify_drone_transmitter(ip: str) -> Optional[Dict[str, Any]]:
    """
    识别指定IP是否为无人机图传设备。

    通过检查特征端口（554/RTSP, 8554/RTSP-Alt, 8080/HTTP）来判断。

    Args:
        ip: 目标IP

    Returns:
        设备信息字典，如果不是无人机则返回None
    """
    # ping检查
    ping_result = ping(ip)
    if not ping_result.success:
        logger.warning(f"[Discovery] {ip} 不可达")
        return None

    # 扫描无人机特征端口
    port_results = scan_ports(ip, DRONE_TRANSMITTER_PORTS)
    open_ports = [p for p in port_results if p.is_open]

    if not open_ports:
        logger.info(f"[Discovery] {ip} 无无人机特征端口开放")
        return None

    device_type = _classify_device(ip, [p.port for p in open_ports])

    return {
        "ip": ip,
        "ping_ms": ping_result.response_time_ms,
        "open_ports": [{"port": p.port, "service": p.service_name, "response_ms": p.response_time_ms} for p in open_ports],
        "device_type": device_type,
        "is_drone": device_type == "drone_transmitter",
    }


def scan_target_devices(
    drone_ip: str = "192.168.1.201",
    base_station_ip: str = "192.168.1.200",
) -> Dict[str, Any]:
    """
    扫描指定目标设备（无人机图传和基站），执行完整连通性检测。

    Args:
        drone_ip: 无人机图传设备IP
        base_station_ip: 基站图传设备IP

    Returns:
        包含两个设备连通性报告的字典
    """
    results = {}

    # 检测无人机图传设备
    drone_info = identify_drone_transmitter(drone_ip)
    drone_connectivity = check_connectivity(base_station_ip, drone_ip, DRONE_TRANSMITTER_PORTS)

    results["drone_transmitter"] = {
        "ip": drone_ip,
        "identified": drone_info is not None,
        "device_info": drone_info,
        "connectivity": {
            "ping_success": drone_connectivity.ping.success if drone_connectivity.ping else False,
            "ping_ms": drone_connectivity.ping.response_time_ms if drone_connectivity.ping else None,
            "packet_loss": drone_connectivity.packet_loss,
            "stability": drone_connectivity.stability,
            "open_ports": [
                {"port": p.port, "service": p.service_name, "is_open": p.is_open}
                for p in drone_connectivity.ports
            ],
            "summary": drone_connectivity.summary,
        },
    }

    # 检测基站
    base_info = identify_drone_transmitter(base_station_ip)
    base_connectivity = check_connectivity(drone_ip, base_station_ip, [8080, 8001, 8000, 1883])

    results["base_station"] = {
        "ip": base_station_ip,
        "reachable": base_connectivity.ping.success if base_connectivity.ping else False,
        "ping_ms": base_connectivity.ping.response_time_ms if base_connectivity.ping else None,
        "open_ports": [
            {"port": p.port, "service": p.service_name, "is_open": p.is_open}
            for p in base_connectivity.ports
        ],
        "summary": base_connectivity.summary,
    }

    # 双向连通性总结
    results["bidirectional"] = {
        "drone_reachable": results["drone_transmitter"]["connectivity"]["ping_success"],
        "base_station_reachable": results["base_station"]["reachable"],
        "communication_ready": (
            results["drone_transmitter"]["connectivity"]["ping_success"]
            and results["base_station"]["reachable"]
        ),
    }

    return results


def _classify_device(ip: str, open_ports: List[int]) -> str:
    """根据开放端口分类设备"""
    if ip == "192.168.1.200":
        return "base_station"
    if ip == "192.168.1.201":
        return "drone_transmitter"

    has_rtsp = any(p in [554, 8554] for p in open_ports)
    has_http_alt = 8080 in open_ports or 8000 in open_ports
    has_rtmp = 1935 in open_ports
    has_mqtt = 1883 in open_ports or 8883 in open_ports

    if has_rtsp and (has_http_alt or has_rtmp):
        return "drone_transmitter"
    if has_http_alt and not has_rtsp:
        return "base_station"
    return "unknown"


def _save_scan_results(scan_id: str, raw_results: List[Dict[str, Any]]):
    """将扫描结果保存到数据库"""
    db = SessionLocal()
    try:
        for device in raw_results:
            record = NetworkScanResult(
                scan_id=scan_id,
                ip_address=device["ip"],
                hostname=device.get("hostname"),
                open_ports=json.dumps(device.get("open_ports", [])),
                response_time_ms=device.get("ping_ms"),
                device_type=_classify_device(
                    device["ip"],
                    [p["port"] for p in device.get("open_ports", [])],
                ),
            )
            db.add(record)
        db.commit()
        logger.info(f"[Discovery] 扫描结果已保存到数据库, scan_id={scan_id}")
    except Exception as e:
        db.rollback()
        logger.error(f"[Discovery] 保存扫描结果失败: {e}")
    finally:
        db.close()