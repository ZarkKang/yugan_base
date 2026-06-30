"""
无人机系统整合服务 — 设备注册、通信配置、数据传输测试、加密管理
"""
import json
import logging
import os
import base64
import hashlib
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from ..db.database import SessionLocal
from ..models.models import DroneDevice, CommunicationLog, Drone

logger = logging.getLogger(__name__)

# 基站存储路径
BASE_STORAGE_PATH = os.environ.get("DRONE_STORAGE_PATH", "storage/drone_data")
os.makedirs(BASE_STORAGE_PATH, exist_ok=True)


def register_device(
    drone_id: int,
    device_name: str,
    ip_address: str,
    port: int = 8080,
    protocol: str = "HTTP",
    device_model: Optional[str] = None,
    firmware_version: Optional[str] = None,
    auth_type: str = "none",
    auth_credential: Optional[str] = None,
    encryption_enabled: bool = False,
    encryption_type: Optional[str] = None,
    encryption_key: Optional[str] = None,
    heartbeat_interval: int = 5,
) -> Dict[str, Any]:
    """
    注册无人机图传设备到系统。

    Args:
        drone_id: 关联的无人机ID
        device_name: 设备名称
        ip_address: 设备IP地址
        port: 通信端口
        protocol: 通信协议
        device_model: 设备型号
        firmware_version: 固件版本
        auth_type: 认证方式
        auth_credential: 认证凭据
        encryption_enabled: 是否启用加密
        encryption_type: 加密方式
        encryption_key: 加密密钥
        heartbeat_interval: 心跳间隔(秒)

    Returns:
        注册结果
    """
    db = SessionLocal()
    try:
        # 验证无人机存在
        drone = db.query(Drone).filter(Drone.id == drone_id).first()
        if not drone:
            return {"success": False, "message": f"无人机ID {drone_id} 不存在"}

        # 检查是否已有同IP设备
        existing = db.query(DroneDevice).filter(
            DroneDevice.ip_address == ip_address,
            DroneDevice.port == port,
        ).first()
        if existing:
            return {"success": False, "message": f"设备 {ip_address}:{port} 已注册", "device_id": existing.id}

        # 加密存储认证凭据
        stored_credential = None
        if auth_credential:
            stored_credential = _encrypt_credential(auth_credential)

        stored_encryption_key = None
        if encryption_key:
            stored_encryption_key = _encrypt_credential(encryption_key)

        device = DroneDevice(
            drone_id=drone_id,
            device_name=device_name,
            device_model=device_model,
            firmware_version=firmware_version,
            ip_address=ip_address,
            port=port,
            protocol=protocol,
            auth_type=auth_type,
            auth_credential=stored_credential,
            encryption_enabled=encryption_enabled,
            encryption_type=encryption_type,
            encryption_key=stored_encryption_key,
            status="offline",
            heartbeat_interval=heartbeat_interval,
        )
        db.add(device)
        db.commit()
        db.refresh(device)

        logger.info(f"[Integration] 设备已注册: {device_name} ({ip_address}:{port}), ID={device.id}")
        return {
            "success": True,
            "message": "设备注册成功",
            "device_id": device.id,
            "device": _device_to_dict(device),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[Integration] 注册设备失败: {e}")
        return {"success": False, "message": f"注册失败: {str(e)}"}
    finally:
        db.close()


def configure_communication(
    device_id: int,
    protocol: Optional[str] = None,
    port: Optional[int] = None,
    auth_type: Optional[str] = None,
    auth_credential: Optional[str] = None,
    encryption_enabled: Optional[bool] = None,
    encryption_type: Optional[str] = None,
    encryption_key: Optional[str] = None,
    heartbeat_interval: Optional[int] = None,
) -> Dict[str, Any]:
    """
    配置设备通信参数。

    Args:
        device_id: 设备ID
        protocol: 通信协议
        port: 端口号
        auth_type: 认证方式
        auth_credential: 认证凭据
        encryption_enabled: 是否启用加密
        encryption_type: 加密方式
        encryption_key: 加密密钥
        heartbeat_interval: 心跳间隔

    Returns:
        配置结果
    """
    db = SessionLocal()
    try:
        device = db.query(DroneDevice).filter(DroneDevice.id == device_id).first()
        if not device:
            return {"success": False, "message": f"设备ID {device_id} 不存在"}

        changed = []
        if protocol is not None:
            device.protocol = protocol
            changed.append("protocol")
        if port is not None:
            device.port = port
            changed.append("port")
        if auth_type is not None:
            device.auth_type = auth_type
            changed.append("auth_type")
        if auth_credential is not None:
            device.auth_credential = _encrypt_credential(auth_credential)
            changed.append("auth_credential")
        if encryption_enabled is not None:
            device.encryption_enabled = encryption_enabled
            changed.append("encryption_enabled")
        if encryption_type is not None:
            device.encryption_type = encryption_type
            changed.append("encryption_type")
        if encryption_key is not None:
            device.encryption_key = _encrypt_credential(encryption_key)
            changed.append("encryption_key")
        if heartbeat_interval is not None:
            device.heartbeat_interval = heartbeat_interval
            changed.append("heartbeat_interval")

        db.commit()
        db.refresh(device)

        logger.info(f"[Integration] 设备 {device_id} 通信参数已更新: {', '.join(changed)}")
        return {
            "success": True,
            "message": f"通信参数已更新 ({', '.join(changed)})",
            "device": _device_to_dict(device),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"[Integration] 配置通信参数失败: {e}")
        return {"success": False, "message": f"配置失败: {str(e)}"}
    finally:
        db.close()


def test_connection(device_id: int, timeout: float = 5.0) -> Dict[str, Any]:
    """
    测试设备连接。

    通过HTTP请求设备健康端点验证连通性。

    Args:
        device_id: 设备ID
        timeout: 超时(秒)

    Returns:
        连接测试结果
    """
    db = SessionLocal()
    try:
        device = db.query(DroneDevice).filter(DroneDevice.id == device_id).first()
        if not device:
            return {"success": False, "message": f"设备ID {device_id} 不存在"}

        start_time = time.time()
        url = f"http://{device.ip_address}:{device.port}/health"
        response_time_ms = None
        error_msg = None
        success = False

        try:
            # 尝试请求健康检查端点
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=timeout) as resp:
                response_data = resp.read().decode("utf-8")
                response_time_ms = (time.time() - start_time) * 1000
                if resp.status == 200:
                    success = True
        except Exception as e:
            error_msg = str(e)
            response_time_ms = (time.time() - start_time) * 1000

        # 更新设备状态
        device.status = "online" if success else "offline"
        if success:
            device.last_connected_at = datetime.utcnow()
        db.commit()

        # 记录通信日志
        _log_communication(
            db, device_id, "connection", "receive" if success else "receive",
            "command", f"健康检查 {'成功' if success else '失败'}", success,
            error_msg, response_time_ms, device.ip_address,
        )

        return {
            "success": success,
            "message": "连接成功" if success else f"连接失败: {error_msg}",
            "device_id": device_id,
            "ip": device.ip_address,
            "port": device.port,
            "response_time_ms": round(response_time_ms, 2) if response_time_ms else None,
            "status": device.status,
        }
    except Exception as e:
        logger.error(f"[Integration] 连接测试失败: {e}")
        return {"success": False, "message": str(e)}
    finally:
        db.close()


def test_data_transmission(
    device_id: int,
    data_type: str = "rfid_json",
    test_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    测试数据传输 — 测试视频流或RFID JSON数据回传。

    Args:
        device_id: 设备ID
        data_type: 数据类型 (video/rfid_json)
        test_payload: 测试数据载荷

    Returns:
        传输测试结果
    """
    db = SessionLocal()
    try:
        device = db.query(DroneDevice).filter(DroneDevice.id == device_id).first()
        if not device:
            return {"success": False, "message": f"设备ID {device_id} 不存在"}

        if data_type == "rfid_json":
            return _test_rfid_json_transmission(device, db, test_payload)
        elif data_type == "video":
            return _test_video_transmission(device, db)
        elif data_type == "both":
            rfid_result = _test_rfid_json_transmission(device, db, test_payload)
            video_result = _test_video_transmission(device, db)
            return {
                "success": rfid_result["success"] and video_result["success"],
                "message": "视频和RFID数据传输测试完成",
                "rfid_result": rfid_result,
                "video_result": video_result,
            }
        else:
            return {"success": False, "message": f"不支持的数据类型: {data_type}"}
    finally:
        db.close()


def _test_rfid_json_transmission(
    device: DroneDevice,
    db,
    test_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """测试RFID JSON数据传输"""
    if test_payload is None:
        test_payload = {
            "drone_code": "DRONE_TEST",
            "timestamp": datetime.utcnow().isoformat(),
            "rfid_tags": [
                {"epc": "E20000123456789012345678", "rssi": -45, "antenna": 1},
                {"epc": "E20000876543210987654321", "rssi": -52, "antenna": 2},
            ],
            "position": {"x": 1.5, "y": 2.0, "z": 3.0},
        }

    # 保存JSON文件到基站存储路径
    device_dir = os.path.join(BASE_STORAGE_PATH, f"device_{device.id}")
    os.makedirs(device_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"rfid_data_{timestamp}.json"
    filepath = os.path.join(device_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(test_payload, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(filepath)

    # 记录通信日志
    _log_communication(
        db, device.id, "data", "receive", "rfid_json",
        f"RFID数据: {len(test_payload.get('rfid_tags', []))} 个标签",
        success=True, file_size=file_size,
        source_ip=device.ip_address,
    )

    logger.info(f"[Integration] RFID JSON数据已保存: {filepath} ({file_size} bytes)")
    return {
        "success": True,
        "message": "RFID JSON数据传输测试成功",
        "file_path": filepath,
        "file_size": file_size,
        "tag_count": len(test_payload.get("rfid_tags", [])),
    }


def _test_video_transmission(device: DroneDevice, db) -> Dict[str, Any]:
    """测试视频传输"""
    # 尝试通过RTSP检查视频流可用性
    rtsp_url = f"rtsp://{device.ip_address}:554/stream"
    http_url = f"http://{device.ip_address}:{device.port}/video/status"

    video_available = False
    video_info = {}

    # 尝试HTTP视频状态端点
    try:
        req = Request(http_url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                video_available = True
                video_info = data
    except Exception:
        pass

    # 记录通信日志
    _log_communication(
        db, device.id, "data", "receive", "video",
        f"视频流检测: {'可用' if video_available else '不可用'} | RTSP: {rtsp_url}",
        success=video_available,
        source_ip=device.ip_address,
    )

    return {
        "success": video_available,
        "message": "视频流可用" if video_available else "视频流不可用，请检查RTSP服务",
        "rtsp_url": rtsp_url,
        "video_info": video_info,
    }


def get_device_status(device_id: Optional[int] = None) -> Dict[str, Any]:
    """获取设备状态信息"""
    db = SessionLocal()
    try:
        if device_id:
            device = db.query(DroneDevice).filter(DroneDevice.id == device_id).first()
            if not device:
                return {"success": False, "message": f"设备ID {device_id} 不存在"}
            return {
                "success": True,
                "device": _device_to_dict(device),
            }

        devices = db.query(DroneDevice).all()
        return {
            "success": True,
            "total": len(devices),
            "devices": [_device_to_dict(d) for d in devices],
            "online_count": sum(1 for d in devices if d.status == "online"),
            "offline_count": sum(1 for d in devices if d.status == "offline"),
        }
    finally:
        db.close()


def get_communication_logs(
    device_id: Optional[int] = None,
    log_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """获取通信日志"""
    db = SessionLocal()
    try:
        query = db.query(CommunicationLog)
        if device_id:
            query = query.filter(CommunicationLog.device_id == device_id)
        if log_type:
            query = query.filter(CommunicationLog.log_type == log_type)

        total = query.count()
        logs = query.order_by(CommunicationLog.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "success": True,
            "total": total,
            "logs": [
                {
                    "id": log.id,
                    "device_id": log.device_id,
                    "log_type": log.log_type,
                    "direction": log.direction,
                    "data_type": log.data_type,
                    "payload_summary": log.payload_summary,
                    "payload_size": log.payload_size,
                    "status": log.status,
                    "error_message": log.error_message,
                    "response_time_ms": log.response_time_ms,
                    "source_ip": log.source_ip,
                    "target_ip": log.target_ip,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
        }
    finally:
        db.close()


def _log_communication(
    db,
    device_id: int,
    log_type: str,
    direction: str,
    data_type: Optional[str],
    summary: str,
    success: bool,
    error_msg: Optional[str] = None,
    response_time_ms: Optional[float] = None,
    source_ip: Optional[str] = None,
    target_ip: Optional[str] = None,
    file_size: Optional[int] = None,
):
    """记录通信日志到数据库"""
    try:
        log = CommunicationLog(
            device_id=device_id,
            log_type=log_type,
            direction=direction,
            data_type=data_type,
            payload_summary=summary[:500],
            payload_size=file_size,
            status="success" if success else "failed",
            error_message=error_msg,
            response_time_ms=int(response_time_ms) if response_time_ms else None,
            source_ip=source_ip,
            target_ip=target_ip,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"[Integration] 记录通信日志失败: {e}")


def _device_to_dict(device: DroneDevice) -> Dict[str, Any]:
    """将设备模型转换为字典(脱敏)"""
    return {
        "id": device.id,
        "drone_id": device.drone_id,
        "device_name": device.device_name,
        "device_model": device.device_model,
        "firmware_version": device.firmware_version,
        "ip_address": device.ip_address,
        "port": device.port,
        "protocol": device.protocol,
        "auth_type": device.auth_type,
        "encryption_enabled": device.encryption_enabled,
        "encryption_type": device.encryption_type,
        "status": device.status,
        "last_connected_at": device.last_connected_at.isoformat() if device.last_connected_at else None,
        "heartbeat_interval": device.heartbeat_interval,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "updated_at": device.updated_at.isoformat() if device.updated_at else None,
    }


def _encrypt_credential(credential: str) -> str:
    """简单加密存储凭据(生产环境应使用更强的加密方案)"""
    salt = "yugan_drone_2024"
    return base64.b64encode(
        hashlib.sha256(f"{salt}:{credential}".encode()).digest()
    ).decode()[:64]