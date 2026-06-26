"""
API路由 - 无人机系统整合
======================
覆盖7个步骤的完整REST接口：
1. 网络连接验证
2. 无人机设备发现
3. 设备身份验证
4. 系统整合配置
5. 数据传输测试
6. 自动化任务配置
7. 监控与日志
"""
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db.database import get_db
from ..models.models import DroneDevice, CommunicationLog, NetworkScanResult, AutomatedTask, Drone
from ..schemas.schemas import APIResponse
from ..core.network import check_connectivity, ping_extended
from ..services.drone_discovery import discover_devices, scan_target_devices, identify_drone_transmitter
from ..services.device_verification import (
    verify_device,
    generate_verification_report,
    _verify_device_passive,
    verify_device_by_heartbeat,
)
from ..services.drone_integration import (
    register_device,
    configure_communication,
    test_connection,
    test_data_transmission,
    get_device_status,
    get_communication_logs,
)
from ..services.automated_task import (
    create_task,
    list_tasks,
    update_task,
    delete_task,
    run_task_manually,
    get_scheduler,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/drone-integration", tags=["无人机系统整合"])


# ============================================================
# 步骤1: 网络连接验证
# ============================================================

@router.post("/network/verify", response_model=APIResponse)
def verify_network(
    drone_ip: str = Query("192.168.1.201", description="无人机图传设备IP"),
    base_station_ip: str = Query("192.168.1.200", description="基站图传设备IP"),
    ports: Optional[str] = Query(None, description="要检测的端口列表，逗号分隔"),
):
    """
    验证无人机图传设备与基站之间的网络连接状态。

    执行内容:
    - Ping 测试 (4次)
    - 端口扫描 (554/8080/8000/8554/80/443/1883)
    - 丢包率分析
    - 稳定性评估
    """
    port_list = None
    if ports:
        port_list = [int(p.strip()) for p in ports.split(",")]

    try:
        report = check_connectivity(base_station_ip, drone_ip, port_list)

        return APIResponse(
            success=True,
            message="网络连接验证完成",
            data={
                "source_ip": report.source_ip,
                "target_ip": report.target_ip,
                "ping": {
                    "success": report.ping.success if report.ping else False,
                    "response_time_ms": report.ping.response_time_ms if report.ping else None,
                },
                "packet_loss_percent": report.packet_loss,
                "stability": report.stability,
                "open_ports": [
                    {
                        "port": p.port,
                        "service": p.service_name,
                        "is_open": p.is_open,
                        "response_ms": p.response_time_ms,
                    }
                    for p in report.ports
                ],
                "summary": report.summary,
            },
        )
    except Exception as e:
        logger.error(f"网络验证失败: {e}")
        return APIResponse(success=False, message=f"网络验证失败: {str(e)}")


# ============================================================
# 步骤2: 无人机设备发现
# ============================================================

@router.post("/discover", response_model=APIResponse)
def discover_drone_devices(
    subnet: str = Query("192.168.1", description="子网前缀"),
    scan_ports: Optional[str] = Query(None, description="扫描端口列表，逗号分隔"),
):
    """
    扫描子网，发现无人机图传设备和基站设备。

    重点识别:
    - 192.168.1.201 (无人机图传设备)
    - 192.168.1.200 (基站图传设备)
    """
    port_list = None
    if scan_ports:
        port_list = [int(p.strip()) for p in scan_ports.split(",")]

    try:
        result = discover_devices(subnet=subnet, scan_ports_list=port_list)

        return APIResponse(
            success=True,
            message=f"扫描完成，发现 {result['drone_transmitter_count']} 台无人机图传设备, "
                    f"{result['base_station_count']} 台基站",
            data=result,
        )
    except Exception as e:
        logger.error(f"设备发现失败: {e}")
        return APIResponse(success=False, message=f"设备发现失败: {str(e)}")


@router.post("/discover/target", response_model=APIResponse)
def scan_specific_targets(
    drone_ip: str = Query("192.168.1.201", description="无人机图传设备IP"),
    base_station_ip: str = Query("192.168.1.200", description="基站IP"),
):
    """
    扫描指定目标设备，执行完整连通性和身份识别检测。
    """
    try:
        result = scan_target_devices(drone_ip=drone_ip, base_station_ip=base_station_ip)

        return APIResponse(
            success=True,
            message="目标设备扫描完成",
            data=result,
        )
    except Exception as e:
        logger.error(f"目标设备扫描失败: {e}")
        return APIResponse(success=False, message=f"目标设备扫描失败: {str(e)}")


# ============================================================
# 步骤3: 设备身份验证
# ============================================================

@router.post("/device/verify", response_model=APIResponse)
def verify_device_identity(
    drone_code: Optional[str] = Query(None, description="无人机编号 (heartbeat模式必填)"),
    ip: Optional[str] = Query(None, description="设备IP (active/passive模式需要)"),
    port: int = Query(8080, description="HTTP端口"),
    mode: str = Query("heartbeat", description="验证模式: heartbeat(默认,利用心跳) / active(基站→无人机) / passive(无人机→基站上报)"),
):
    """
    验证设备身份，确认设备型号、固件版本和通信协议兼容性。

    三种模式:
    - heartbeat (默认, 推荐用于 uav_ground_bridge 纯上报型无人机):
        利用无人机主动上报的心跳判断在线状态，不反查无人机任何端口。
        需要 drone_code 参数。
    - active:  基站主动向无人机IP发起HTTP请求验证（需无人机端运行HTTP服务）
    - passive: 查询无人机通过 /device/report 端点上报的最新设备信息

    检查内容:
    - 设备型号和制造商
    - 固件版本
    - 支持的通信协议
    - 与系统协议的兼容性
    """
    try:
        if mode == "heartbeat":
            if not drone_code:
                return APIResponse(
                    success=False,
                    message="heartbeat 模式需要 drone_code 参数",
                    data={"verified": False, "mode": "heartbeat", "protocol_issues": ["缺少 drone_code 参数"]},
                )
            result = verify_device_by_heartbeat(drone_code)
        elif mode == "passive":
            if not ip:
                return APIResponse(
                    success=False,
                    message="passive 模式需要 ip 参数",
                    data={"verified": False, "mode": "passive", "protocol_issues": ["缺少 ip 参数"]},
                )
            result = _verify_device_passive(ip)
        else:
            if not ip:
                return APIResponse(
                    success=False,
                    message="active 模式需要 ip 参数",
                    data={"verified": False, "mode": "active", "protocol_issues": ["缺少 ip 参数"]},
                )
            result = verify_device(ip, port)

        report = generate_verification_report(result)

        return APIResponse(
            success=result["verified"],
            message="设备验证完成" if result["verified"] else "设备验证未完全通过",
            data={
                **result,
                "report": report,
            },
        )
    except Exception as e:
        logger.error(f"设备验证失败: {e}")
        return APIResponse(success=False, message=f"设备验证失败: {str(e)}")


@router.post("/device/report", response_model=APIResponse)
def receive_device_report(
    drone_code: str = Query(..., description="无人机编号"),
    ip_address: str = Query(..., description="设备IP"),
    device_model: Optional[str] = Query(None, description="设备型号"),
    manufacturer: Optional[str] = Query(None, description="制造商"),
    firmware_version: Optional[str] = Query(None, description="固件版本"),
    supported_protocols: Optional[str] = Query(None, description="支持的协议，逗号分隔"),
    port: int = Query(8080, description="HTTP服务端口"),
    ros_version: Optional[str] = Query(None, description="ROS版本"),
    os_version: Optional[str] = Query(None, description="操作系统版本"),
    cpu_info: Optional[str] = Query(None, description="CPU信息"),
    memory_mb: Optional[int] = Query(None, description="内存(MB)"),
    db: Session = Depends(get_db),
):
    """
    无人机端主动上报设备身份信息（被动验证模式）。

    无人机启动时调用此端点，基站接收并存储设备信息，
    后续验证向导可通过 passive 模式查询此信息而无需直接连接无人机。
    """
    try:
        from ..services.device_verification import save_device_report
        result = save_device_report(
            db=db,
            drone_code=drone_code,
            ip_address=ip_address,
            device_model=device_model,
            manufacturer=manufacturer,
            firmware_version=firmware_version,
            supported_protocols=supported_protocols,
            port=port,
            ros_version=ros_version,
            os_version=os_version,
            cpu_info=cpu_info,
            memory_mb=memory_mb,
        )

        return APIResponse(
            success=True,
            message="设备信息已接收",
            data=result,
        )
    except Exception as e:
        logger.error(f"设备信息上报失败: {e}")
        return APIResponse(success=False, message=f"上报失败: {str(e)}")


# ============================================================
# 步骤4: 系统整合配置
# ============================================================

@router.post("/device/register", response_model=APIResponse)
def register_drone_device(
    drone_id: int = Query(..., description="关联无人机ID"),
    device_name: str = Query(..., description="设备名称"),
    ip_address: str = Query("192.168.1.201", description="设备IP"),
    port: int = Query(8080, description="通信端口"),
    protocol: str = Query("HTTP", description="通信协议: HTTP/RTSP/MQTT/WebSocket"),
    device_model: Optional[str] = Query(None, description="设备型号"),
    firmware_version: Optional[str] = Query(None, description="固件版本"),
    auth_type: str = Query("none", description="认证方式: none/basic/token/certificate"),
    auth_credential: Optional[str] = Query(None, description="认证凭据"),
    encryption_enabled: bool = Query(False, description="是否启用加密"),
    encryption_type: Optional[str] = Query(None, description="加密方式: AES/TLS"),
    encryption_key: Optional[str] = Query(None, description="加密密钥"),
    heartbeat_interval: int = Query(5, description="心跳间隔(秒)"),
):
    """
    注册无人机图传设备到系统，配置通信参数和加密方式。
    """
    try:
        result = register_device(
            drone_id=drone_id,
            device_name=device_name,
            ip_address=ip_address,
            port=port,
            protocol=protocol,
            device_model=device_model,
            firmware_version=firmware_version,
            auth_type=auth_type,
            auth_credential=auth_credential,
            encryption_enabled=encryption_enabled,
            encryption_type=encryption_type,
            encryption_key=encryption_key,
            heartbeat_interval=heartbeat_interval,
        )

        return APIResponse(
            success=result["success"],
            message=result["message"],
            data=result.get("device"),
        )
    except Exception as e:
        logger.error(f"设备注册失败: {e}")
        return APIResponse(success=False, message=f"设备注册失败: {str(e)}")


@router.put("/device/{device_id}/configure", response_model=APIResponse)
def configure_device_communication(
    device_id: int,
    protocol: Optional[str] = Query(None, description="通信协议"),
    port: Optional[int] = Query(None, description="端口号"),
    auth_type: Optional[str] = Query(None, description="认证方式"),
    auth_credential: Optional[str] = Query(None, description="认证凭据"),
    encryption_enabled: Optional[bool] = Query(None, description="是否启用加密"),
    encryption_type: Optional[str] = Query(None, description="加密方式"),
    encryption_key: Optional[str] = Query(None, description="加密密钥"),
    heartbeat_interval: Optional[int] = Query(None, description="心跳间隔(秒)"),
):
    """
    配置已注册设备的通信参数。
    """
    try:
        result = configure_communication(
            device_id=device_id,
            protocol=protocol,
            port=port,
            auth_type=auth_type,
            auth_credential=auth_credential,
            encryption_enabled=encryption_enabled,
            encryption_type=encryption_type,
            encryption_key=encryption_key,
            heartbeat_interval=heartbeat_interval,
        )

        return APIResponse(
            success=result["success"],
            message=result["message"],
            data=result.get("device"),
        )
    except Exception as e:
        logger.error(f"通信配置失败: {e}")
        return APIResponse(success=False, message=f"配置失败: {str(e)}")


@router.post("/device/{device_id}/test-connection", response_model=APIResponse)
def test_device_connection(
    device_id: int,
    timeout: float = Query(5.0, description="超时(秒)"),
):
    """
    测试设备连接状态。
    """
    try:
        result = test_connection(device_id, timeout)
        return APIResponse(
            success=result["success"],
            message=result["message"],
            data=result,
        )
    except Exception as e:
        return APIResponse(success=False, message=str(e))


# ============================================================
# 步骤5: 数据传输测试
# ============================================================

@router.post("/transmission/test", response_model=APIResponse)
def test_transmission(
    device_id: int = Query(..., description="设备ID"),
    data_type: str = Query("rfid_json", description="数据类型: rfid_json/video/both"),
):
    """
    测试数据传输 — 视频流传输和RFID JSON文件回传功能。

    测试内容:
    - rfid_json: 测试RFID标签数据JSON文件生成和回传
    - video: 测试视频流可用性
    - both: 同时测试视频和RFID
    """
    try:
        result = test_data_transmission(device_id, data_type)
        return APIResponse(
            success=result["success"],
            message=result["message"],
            data=result,
        )
    except Exception as e:
        logger.error(f"传输测试失败: {e}")
        return APIResponse(success=False, message=f"传输测试失败: {str(e)}")


# ============================================================
# 步骤6: 自动化任务配置
# ============================================================

@router.post("/tasks", response_model=APIResponse)
def create_automated_task(
    device_id: int = Query(..., description="设备ID"),
    task_name: str = Query(..., description="任务名称"),
    task_type: str = Query(..., description="任务类型: video_capture/rfid_read/both"),
    schedule_type: str = Query("interval", description="调度类型: interval/cron/once"),
    schedule_value: str = Query(..., description="调度值: 秒数/cron表达式/ISO时间"),
    target_storage_path: str = Query("drone_data", description="基站目标存储路径"),
    target_shelves: Optional[str] = Query(None, description='目标货架编号JSON列表,如 ["SHELF-001","SHELF-002"]'),
    video_duration: int = Query(30, description="视频采集时长(秒)"),
    video_resolution: str = Query("1920x1080", description="视频分辨率"),
    rfid_read_duration: int = Query(10, description="RFID读取时长(秒)"),
    json_filename_pattern: str = Query("drone_{device_id}_{timestamp}.json", description="JSON文件名模板"),
    enabled: bool = Query(True, description="是否启用"),
):
    """
    创建自动化任务，配置无人机按预定指令执行采集操作。

    任务类型:
    - video_capture: 定时视频采集
    - rfid_read: 定时RFID数据读取
    - both: 视频+RFID同时执行

    调度类型:
    - interval: 间隔秒数 (如 "60" 表示每60秒)
    - cron: cron表达式 (如 "*/5" 表示每5分钟)
    - once: 指定时间ISO格式 (如 "2026-06-21T12:00:00")

    target_shelves:
        目标货架编号JSON列表字符串, 如 '["SHELF-001","SHELF-002"]'
    """
    try:
        result = create_task(
            device_id=device_id,
            task_name=task_name,
            task_type=task_type,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            target_storage_path=target_storage_path,
            target_shelves=target_shelves,
            video_duration=video_duration,
            video_resolution=video_resolution,
            rfid_read_duration=rfid_read_duration,
            json_filename_pattern=json_filename_pattern,
            enabled=enabled,
        )

        return APIResponse(
            success=result["success"],
            message=result["message"],
            data=result.get("task"),
        )
    except Exception as e:
        logger.error(f"创建任务失败: {e}")
        return APIResponse(success=False, message=f"创建任务失败: {str(e)}")


@router.get("/tasks", response_model=APIResponse)
def get_automated_tasks(
    device_id: Optional[int] = Query(None, description="按设备ID过滤"),
):
    """获取自动化任务列表"""
    try:
        result = list_tasks(device_id)
        return APIResponse(
            success=True,
            message=f"共 {result['total']} 个任务",
            data=result,
        )
    except Exception as e:
        return APIResponse(success=False, message=str(e))


@router.put("/tasks/{task_id}", response_model=APIResponse)
def update_automated_task(
    task_id: int,
    task_name: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    schedule_type: Optional[str] = Query(None),
    schedule_value: Optional[str] = Query(None),
    target_storage_path: Optional[str] = Query(None),
    video_duration: Optional[int] = Query(None),
    video_resolution: Optional[str] = Query(None),
    rfid_read_duration: Optional[int] = Query(None),
    json_filename_pattern: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
):
    """更新自动化任务配置"""
    kwargs = {k: v for k, v in locals().items() if k != "task_id" and v is not None}
    result = update_task(task_id, **kwargs)
    return APIResponse(
        success=result["success"],
        message=result["message"],
        data=result.get("task"),
    )


@router.delete("/tasks/{task_id}", response_model=APIResponse)
def delete_automated_task(task_id: int):
    """删除自动化任务"""
    result = delete_task(task_id)
    return APIResponse(success=result["success"], message=result["message"])


@router.post("/tasks/{task_id}/run", response_model=APIResponse)
def run_task_now(task_id: int):
    """手动立即执行任务"""
    result = run_task_manually(task_id)
    return APIResponse(
        success=result["success"],
        message=result["message"],
        data=result.get("task"),
    )


# ============================================================
# 步骤7: 监控与日志
# ============================================================

@router.get("/monitor/status", response_model=APIResponse)
def monitor_device_status(
    device_id: Optional[int] = Query(None, description="设备ID，不传则返回全部"),
):
    """
    获取设备状态监控信息。

    包含:
    - 设备在线/离线状态
    - 最后连接时间
    - 通信日志统计
    """
    try:
        result = get_device_status(device_id)

        return APIResponse(
            success=result["success"],
            message=f"获取设备状态成功",
            data=result,
        )
    except Exception as e:
        logger.error(f"获取设备状态失败: {e}")
        return APIResponse(success=False, message=f"获取状态失败: {str(e)}")


@router.get("/logs", response_model=APIResponse)
def get_logs(
    device_id: Optional[int] = Query(None, description="设备ID"),
    log_type: Optional[str] = Query(None, description="日志类型: connection/data/error/heartbeat"),
    limit: int = Query(100, ge=1, le=1000, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """
    获取通信日志。

    日志类型:
    - connection: 连接日志
    - data: 数据传输日志
    - error: 错误日志
    - heartbeat: 心跳日志
    """
    try:
        result = get_communication_logs(
            device_id=device_id,
            log_type=log_type,
            limit=limit,
            offset=offset,
        )

        return APIResponse(
            success=True,
            message=f"共 {result['total']} 条日志",
            data=result,
        )
    except Exception as e:
        logger.error(f"获取日志失败: {e}")
        return APIResponse(success=False, message=f"获取日志失败: {str(e)}")


@router.get("/scans", response_model=APIResponse)
def get_scan_history(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
):
    """获取历史扫描记录"""
    db = next(get_db())
    try:
        scans = (
            db.query(NetworkScanResult)
            .order_by(NetworkScanResult.discovered_at.desc())
            .limit(limit)
            .all()
        )

        # 按scan_id分组
        scan_groups = {}
        for scan in scans:
            if scan.scan_id not in scan_groups:
                scan_groups[scan.scan_id] = {
                    "scan_id": scan.scan_id,
                    "scanned_at": scan.discovered_at.isoformat() if scan.discovered_at else None,
                    "devices": [],
                }
            scan_groups[scan.scan_id]["devices"].append({
                "ip": scan.ip_address,
                "hostname": scan.hostname,
                "device_type": scan.device_type,
                "verified": scan.verified,
                "registered": scan.registered,
            })

        return APIResponse(
            success=True,
            message=f"共 {len(scan_groups)} 次扫描记录",
            data={"scans": list(scan_groups.values())},
        )
    finally:
        db.close()