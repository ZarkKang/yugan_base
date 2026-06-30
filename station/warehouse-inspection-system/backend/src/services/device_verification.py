"""
设备身份验证服务 — 验证无人机设备型号、固件版本、通信协议兼容性
支持两种模式:
- active:  基站主动向无人机IP发起HTTP请求
- passive: 无人机主动上报设备信息，基站查询存储的记录
"""
import json
import logging
import socket
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from ..db.database import SessionLocal
from ..models.models import DroneDevice, Drone

logger = logging.getLogger(__name__)

# 系统支持的协议列表
SUPPORTED_PROTOCOLS = ["HTTP", "RTSP", "MQTT", "WebSocket"]
# 已知兼容的无人机图传设备型号
KNOWN_DEVICE_MODELS = [
    {"model": "DJI-Lightbridge-2", "manufacturer": "DJI", "protocols": ["HTTP", "RTSP"]},
    {"model": "DJI-O3-Air-Unit", "manufacturer": "DJI", "protocols": ["HTTP", "RTSP"]},
    {"model": "DJI-O4-Air-Unit", "manufacturer": "DJI", "protocols": ["HTTP", "RTSP"]},
    {"model": "Walksnail-Avatar", "manufacturer": "Walksnail", "protocols": ["HTTP", "RTSP"]},
    {"model": "HDZero-VTX", "manufacturer": "HDZero", "protocols": ["HTTP"]},
    {"model": "SIYI-HM30", "manufacturer": "SIYI", "protocols": ["HTTP", "MQTT"]},
    {"model": "Custom-ESP32", "manufacturer": "Custom", "protocols": ["HTTP", "MQTT", "WebSocket"]},
    {"model": "Generic-IP-Camera", "manufacturer": "Generic", "protocols": ["HTTP", "RTSP"]},
]


def verify_device(
    ip: str,
    port: int = 8080,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    验证设备身份，获取设备信息并检查协议兼容性。

    Args:
        ip: 设备IP
        port: 设备HTTP端口
        timeout: 请求超时(秒)

    Returns:
        验证结果，包含设备信息、协议兼容性、建议
    """
    result = {
        "ip": ip,
        "port": port,
        "verified": False,
        "device_model": None,
        "manufacturer": None,
        "firmware_version": None,
        "supported_protocols": [],
        "protocol_compatible": False,
        "protocol_issues": [],
        "raw_device_info": None,
        "recommendations": [],
        "verified_at": datetime.utcnow().isoformat(),
    }

    # 尝试获取设备信息
    device_info = _fetch_device_info(ip, port, timeout)

    if device_info is None:
        result["protocol_issues"].append("无法获取设备信息，设备可能不支持HTTP API")
        result["recommendations"].append("请确认设备HTTP服务是否运行在指定端口")
        return result

    result["raw_device_info"] = device_info

    # 提取设备身份信息
    model = device_info.get("model") or device_info.get("device_model") or device_info.get("product_name")
    manufacturer = device_info.get("manufacturer") or device_info.get("vendor") or device_info.get("brand")
    firmware = device_info.get("firmware_version") or device_info.get("firmware") or device_info.get("version")
    protocols = device_info.get("protocols") or device_info.get("supported_protocols") or []

    result["device_model"] = model
    result["manufacturer"] = manufacturer
    result["firmware_version"] = firmware
    result["supported_protocols"] = protocols if isinstance(protocols, list) else [protocols]

    # 检查是否为已知型号
    known_model = _match_known_model(model, manufacturer)
    if known_model:
        result["known_model"] = known_model
        result["verified"] = True
        logger.info(f"[Verification] 设备 {ip} 识别为已知型号: {known_model['model']} ({known_model['manufacturer']})")
    else:
        result["verified"] = True  # 能获取到信息即视为基本验证通过
        result["recommendations"].append(f"设备型号 '{model}' 不在已知兼容列表中，建议手动验证兼容性")

    # 检查协议兼容性
    result["protocol_compatible"], result["protocol_issues"] = _check_protocol_compatibility(
        result["supported_protocols"], known_model
    )

    if not result["protocol_compatible"]:
        result["recommendations"].append(
            f"协议不兼容: {'; '.join(result['protocol_issues'])}。"
            f"系统支持: {', '.join(SUPPORTED_PROTOCOLS)}"
        )

    return result


def batch_verify_devices(
    devices: List[Dict[str, Any]],
    timeout: float = 5.0,
) -> List[Dict[str, Any]]:
    """批量验证设备"""
    results = []
    for device in devices:
        ip = device.get("ip")
        port = device.get("port", 8080)
        if ip:
            result = verify_device(ip, port, timeout)
            result["original_entry"] = device
            results.append(result)
    return results


def generate_verification_report(verification_result: Dict[str, Any]) -> str:
    """生成验证报告文本"""
    lines = [
        "=" * 50,
        "  无人机设备身份验证报告",
        "=" * 50,
        f"设备IP:       {verification_result['ip']}:{verification_result['port']}",
        f"设备型号:     {verification_result['device_model'] or '未知'}",
        f"制造商:       {verification_result['manufacturer'] or '未知'}",
        f"固件版本:     {verification_result['firmware_version'] or '未知'}",
        f"支持的协议:   {', '.join(verification_result['supported_protocols']) or '无'}",
        f"协议兼容:     {'是' if verification_result['protocol_compatible'] else '否'}",
        f"验证结果:     {'通过' if verification_result['verified'] else '未通过'}",
        f"验证时间:     {verification_result['verified_at']}",
    ]

    if verification_result["protocol_issues"]:
        lines.append(f"协议问题:     {'; '.join(verification_result['protocol_issues'])}")

    if verification_result["recommendations"]:
        lines.append("建议:")
        for rec in verification_result["recommendations"]:
            lines.append(f"  - {rec}")

    lines.append("=" * 50)
    return "\n".join(lines)


def _fetch_device_info(ip: str, port: int, timeout: float) -> Optional[Dict[str, Any]]:
    """通过HTTP获取设备信息"""
    endpoints = [
        f"http://{ip}:{port}/api/device/info",
        f"http://{ip}:{port}/api/info",
        f"http://{ip}:{port}/info",
        f"http://{ip}:{port}/api/v1/device/info",
        f"http://{ip}:{port}/status",
        f"http://{ip}:{port}/api/status",
    ]

    for url in endpoints:
        try:
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=timeout) as response:
                data = response.read().decode("utf-8")
                info = json.loads(data)
                if isinstance(info, dict):
                    logger.info(f"[Verification] 从 {url} 获取到设备信息")
                    return info
        except (URLError, HTTPError, json.JSONDecodeError, socket.timeout) as e:
            logger.debug(f"[Verification] {url} 不可用: {e}")
            continue
        except Exception as e:
            logger.debug(f"[Verification] {url} 异常: {e}")
            continue

    return None


def _match_known_model(model: Optional[str], manufacturer: Optional[str]) -> Optional[Dict[str, Any]]:
    """匹配已知设备型号"""
    if not model:
        return None
    model_lower = model.lower()
    for known in KNOWN_DEVICE_MODELS:
        if known["model"].lower() in model_lower or model_lower in known["model"].lower():
            return known
        if manufacturer and known["manufacturer"].lower() in manufacturer.lower():
            return known
    return None


def _check_protocol_compatibility(
    device_protocols: List[str],
    known_model: Optional[Dict[str, Any]] = None,
) -> tuple:
    """
    检查协议兼容性。

    Returns:
        (是否兼容, 问题列表)
    """
    issues = []

    if not device_protocols:
        if known_model:
            device_protocols = known_model.get("protocols", [])
        else:
            issues.append("设备未声明支持的协议")
            return False, issues

    # 标准化协议名
    normalized = [p.upper().strip() for p in device_protocols]

    compatible = False
    for proto in normalized:
        if proto in SUPPORTED_PROTOCOLS:
            compatible = True
            break

    if not compatible:
        issues.append(f"设备协议 ({', '.join(device_protocols)}) 与系统不兼容")
        issues.append(f"系统支持的协议: {', '.join(SUPPORTED_PROTOCOLS)}")

    return compatible, issues


# ============================================================
# 被动验证模式: 无人机主动上报 → 基站存储 → 查询验证
# ============================================================

def save_device_report(
    db,
    drone_code: str,
    ip_address: str,
    device_model: Optional[str] = None,
    manufacturer: Optional[str] = None,
    firmware_version: Optional[str] = None,
    supported_protocols: Optional[str] = None,
    port: int = 8080,
    ros_version: Optional[str] = None,
    os_version: Optional[str] = None,
    cpu_info: Optional[str] = None,
    memory_mb: Optional[int] = None,
) -> Dict[str, Any]:
    """
    存储无人机上报的设备身份信息。

    无人机启动时调用此函数，将设备信息存入 DroneDevice 表。
    如果已存在同 IP 设备则更新，否则新建。
    """
    protocols_list = []
    if supported_protocols:
        protocols_list = [p.strip() for p in supported_protocols.split(",")]

    # 查找或创建 DroneDevice 记录
    existing = db.query(DroneDevice).filter(
        DroneDevice.ip_address == ip_address,
    ).first()

    if existing:
        # 更新已有记录
        if device_model:
            existing.device_model = device_model
        if firmware_version:
            existing.firmware_version = firmware_version
        existing.port = port
        existing.status = "online"
        existing.last_connected_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)

        logger.info(f"[Verification] 被动验证: 更新设备 {ip_address} 信息 (model={device_model})")
        return {
            "action": "updated",
            "device_id": existing.id,
            "ip_address": ip_address,
            "device_model": device_model,
            "firmware_version": firmware_version,
            "supported_protocols": protocols_list,
            "ros_version": ros_version,
            "os_version": os_version,
            "cpu_info": cpu_info,
            "memory_mb": memory_mb,
            "reported_at": datetime.utcnow().isoformat(),
        }
    else:
        # 查找关联的无人机
        drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
        drone_id = drone.id if drone else None

        # 创建新记录
        new_device = DroneDevice(
            drone_id=drone_id,
            device_name=f"Drone-{drone_code}",
            device_model=device_model,
            firmware_version=firmware_version,
            ip_address=ip_address,
            port=port,
            protocol="HTTP",
            auth_type="none",
            encryption_enabled=False,
            status="online",
            heartbeat_interval=5,
            last_connected_at=datetime.utcnow(),
        )
        db.add(new_device)
        db.commit()
        db.refresh(new_device)

        logger.info(f"[Verification] 被动验证: 注册新设备 {ip_address} (model={device_model}, drone={drone_code})")
        return {
            "action": "created",
            "device_id": new_device.id,
            "ip_address": ip_address,
            "device_model": device_model,
            "firmware_version": firmware_version,
            "supported_protocols": protocols_list,
            "ros_version": ros_version,
            "os_version": os_version,
            "cpu_info": cpu_info,
            "memory_mb": memory_mb,
            "reported_at": datetime.utcnow().isoformat(),
        }


def _verify_device_passive(ip: str) -> Dict[str, Any]:
    """
    被动验证: 查询无人机上报的设备信息。

    不主动连接无人机，而是查询数据库中已存储的设备报告。
    """
    result = {
        "ip": ip,
        "port": None,
        "verified": False,
        "device_model": None,
        "manufacturer": None,
        "firmware_version": None,
        "supported_protocols": [],
        "protocol_compatible": False,
        "protocol_issues": [],
        "raw_device_info": None,
        "recommendations": [],
        "verified_at": datetime.utcnow().isoformat(),
        "mode": "passive",
    }

    db = SessionLocal()
    try:
        device = db.query(DroneDevice).filter(
            DroneDevice.ip_address == ip,
        ).order_by(DroneDevice.last_connected_at.desc()).first()

        if not device:
            result["protocol_issues"].append(
                f"无人机 {ip} 尚未上报设备信息。"
                f"请确保无人机端已启动并在启动时调用 POST /drone-integration/device/report。"
            )
            result["recommendations"].append("等待无人机上报设备信息，或使用 active 模式直接连接验证")
            return result

        result["port"] = device.port
        result["device_model"] = device.device_model
        result["manufacturer"] = "DJI" if device.device_model and "DJI" in device.device_model else None
        result["firmware_version"] = device.firmware_version
        result["supported_protocols"] = ["HTTP"]
        result["raw_device_info"] = {
            "model": device.device_model,
            "firmware_version": device.firmware_version,
            "ip_address": device.ip_address,
            "port": device.port,
            "status": device.status,
            "last_connected_at": device.last_connected_at.isoformat() if device.last_connected_at else None,
        }

        # 匹配已知型号
        known_model = _match_known_model(device.device_model, result["manufacturer"])
        if known_model:
            result["known_model"] = known_model
            result["supported_protocols"] = known_model.get("protocols", ["HTTP"])
            result["verified"] = True
        else:
            result["verified"] = True
            result["recommendations"].append(
                f"设备型号 '{device.device_model}' 不在已知兼容列表中，建议手动验证"
            )

        # 协议兼容性
        result["protocol_compatible"], result["protocol_issues"] = _check_protocol_compatibility(
            result["supported_protocols"], known_model
        )

        if device.status == "offline":
            result["recommendations"].append("设备上次上报后已离线，请检查无人机运行状态")

        logger.info(f"[Verification] 被动验证 {ip}: {device.device_model}, status={device.status}")
        return result

    finally:
        db.close()


# ============================================================
# 心跳验证模式: 利用无人机主动上报的心跳判断在线状态
# 与无人机端 uav_ground_bridge 的纯上报型架构一致
# ============================================================

HEARTBEAT_ONLINE_THRESHOLD_SECONDS = 30


def upsert_device_from_heartbeat(db, drone: Drone) -> Optional[DroneDevice]:
    """
    心跳到达时自动创建/更新 DroneDevice 记录。
    无人机端只需发送心跳，基站自动维护设备表，无需额外上报接口。
    """
    existing = db.query(DroneDevice).filter(
        DroneDevice.drone_id == drone.id
    ).first()

    now = datetime.utcnow()
    if existing:
        existing.status = "online"
        existing.last_connected_at = now
        db.commit()
        db.refresh(existing)
        return existing

    new_device = DroneDevice(
        drone_id=drone.id,
        device_name=f"Drone-{drone.drone_code}",
        device_model=drone.model or "uav_ground_bridge",
        firmware_version=None,
        ip_address="0.0.0.0",
        port=0,
        protocol="HTTP-Client",
        auth_type="none",
        encryption_enabled=False,
        status="online",
        heartbeat_interval=5,
        last_connected_at=now,
    )
    db.add(new_device)
    db.commit()
    db.refresh(new_device)
    logger.info(f"[Verification] 心跳验证: 自动注册设备 {drone.drone_code} (device_id={new_device.id})")
    return new_device


def verify_device_by_heartbeat(drone_code: str, db=None) -> Dict[str, Any]:
    """
    心跳验证: 通过 drones 表的 last_seen 判断无人机是否在线。
    不反查无人机任何端口，与 uav_ground_bridge 纯上报型架构一致。

    在线判据: last_seen 在 HEARTBEAT_ONLINE_THRESHOLD_SECONDS 秒内。
    """
    result = {
        "ip": None,
        "port": None,
        "verified": False,
        "device_model": None,
        "manufacturer": None,
        "firmware_version": None,
        "supported_protocols": ["HTTP"],
        "protocol_compatible": True,
        "protocol_issues": [],
        "raw_device_info": None,
        "recommendations": [],
        "verified_at": datetime.utcnow().isoformat(),
        "mode": "heartbeat",
    }

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
        if not drone:
            result["protocol_issues"].append(f"无人机 {drone_code} 未注册")
            result["recommendations"].append("请先通过 POST /api/v1/drones/ 注册无人机")
            return result

        result["ip"] = "via-heartbeat"
        result["device_model"] = drone.model or "uav_ground_bridge"

        now = datetime.utcnow()
        if drone.last_seen and (now - drone.last_seen).total_seconds() <= HEARTBEAT_ONLINE_THRESHOLD_SECONDS:
            result["verified"] = True
            result["raw_device_info"] = {
                "drone_code": drone.drone_code,
                "status": drone.status,
                "battery_level": drone.battery_level,
                "last_seen": drone.last_seen.isoformat() if drone.last_seen else None,
                "last_position": {
                    "x": drone.last_position_x,
                    "y": drone.last_position_y,
                    "z": drone.last_position_z,
                },
            }
            # 心跳在线, 自动维护 DroneDevice 记录
            upsert_device_from_heartbeat(db, drone)
            logger.info(f"[Verification] 心跳验证通过 {drone_code}: status={drone.status}, last_seen={drone.last_seen}")
        else:
            last_seen_str = drone.last_seen.isoformat() if drone.last_seen else "从未"
            result["protocol_issues"].append(
                f"无人机 {drone_code} 心跳超时 (最后心跳: {last_seen_str}, 阈值 {HEARTBEAT_ONLINE_THRESHOLD_SECONDS}s)"
            )
            result["recommendations"].append("请确认无人机端 uav_ground_bridge 节点已启动并发送心跳")
            # 标记设备离线
            device = db.query(DroneDevice).filter(DroneDevice.drone_id == drone.id).first()
            if device and device.status != "offline":
                device.status = "offline"
                db.commit()

        return result
    finally:
        if own_session:
            db.close()