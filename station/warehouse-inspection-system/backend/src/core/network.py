"""
网络工具模块 — ping、端口扫描、子网扫描、连通性诊断
"""
import subprocess
import socket
import platform
import concurrent.futures
import logging
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
DEFAULT_TIMEOUT = 2.0
MAX_WORKERS = 50


@dataclass
class PingResult:
    ip: str
    success: bool
    response_time_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class PortResult:
    ip: str
    port: int
    is_open: bool
    service_name: Optional[str] = None
    response_time_ms: Optional[float] = None


@dataclass
class ConnectivityReport:
    source_ip: str
    target_ip: str
    ping: Optional[PingResult] = None
    ports: List[PortResult] = field(default_factory=list)
    packet_loss: float = 0.0
    avg_response_ms: Optional[float] = None
    stability: str = "unknown"  # stable / unstable / poor
    summary: str = ""


def ping(ip: str, timeout: float = DEFAULT_TIMEOUT, count: int = 1) -> PingResult:
    """Ping 目标IP，返回结果"""
    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), ip]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(int(timeout)), ip]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        if result.returncode == 0:
            # 解析响应时间
            response_time = _parse_ping_time(result.stdout)
            return PingResult(ip=ip, success=True, response_time_ms=response_time)
        else:
            return PingResult(ip=ip, success=False, error="ping failed (no response)")
    except subprocess.TimeoutExpired:
        return PingResult(ip=ip, success=False, error="ping timeout")
    except Exception as e:
        return PingResult(ip=ip, success=False, error=str(e))


def ping_extended(ip: str, count: int = 4, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """扩展Ping测试 — 多次ping，返回丢包率和稳定性评估"""
    results = []
    for i in range(count):
        r = ping(ip, timeout=timeout, count=1)
        results.append(r)

    success_count = sum(1 for r in results if r.success)
    packet_loss = (count - success_count) / count * 100
    avg_response = None
    if success_count > 0:
        times = [r.response_time_ms for r in results if r.success and r.response_time_ms is not None]
        if times:
            avg_response = sum(times) / len(times)

    if success_count == count:
        stability = "stable"
    elif success_count >= count * 0.5:
        stability = "unstable"
    else:
        stability = "poor"

    return {
        "ip": ip,
        "total": count,
        "success": success_count,
        "failed": count - success_count,
        "packet_loss_percent": round(packet_loss, 1),
        "avg_response_ms": round(avg_response, 2) if avg_response else None,
        "stability": stability,
        "details": results,
    }


def scan_port(ip: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> PortResult:
    """扫描单个端口是否开放"""
    start = time.time()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((ip, port))
        elapsed = (time.time() - start) * 1000
        if result == 0:
            service = _get_service_name(port)
            return PortResult(ip=ip, port=port, is_open=True, service_name=service, response_time_ms=elapsed)
        else:
            return PortResult(ip=ip, port=port, is_open=False, response_time_ms=elapsed)
    except socket.error as e:
        return PortResult(ip=ip, port=port, is_open=False, response_time_ms=None)
    finally:
        sock.close()


def scan_ports(ip: str, ports: List[int], timeout: float = DEFAULT_TIMEOUT) -> List[PortResult]:
    """并发扫描多个端口"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(ports), 20)) as executor:
        futures = {executor.submit(scan_port, ip, port, timeout): port for port in ports}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                port = futures[future]
                results.append(PortResult(ip=ip, port=port, is_open=False))
    return sorted(results, key=lambda r: r.port)


def scan_subnet(subnet: str, ports: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    """
    扫描子网内所有活动主机及其开放端口。

    Args:
        subnet: 子网前缀，如 "192.168.1"
        ports: 要扫描的端口列表，默认扫描常用端口

    Returns:
        活动主机列表，每项包含IP、主机名、ping时间、开放端口
    """
    if ports is None:
        ports = [80, 443, 554, 8080, 8000, 8001, 8554, 1935, 1883, 8883, 22, 21]

    all_ips = [f"{subnet}.{i}" for i in range(1, 255)]
    results = []

    # 第一步：并发ping所有IP
    active_hosts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(ping, ip): ip for ip in all_ips}
        for future in concurrent.futures.as_completed(futures):
            try:
                r = future.result()
                if r.success:
                    active_hosts.append(r)
            except Exception:
                pass

    logger.info(f"[Network] 子网扫描: {len(active_hosts)}/{len(all_ips)} 台主机在线")

    # 第二步：对活动主机扫描端口
    for host in active_hosts:
        hostname = _resolve_hostname(host.ip)
        port_results = scan_ports(host.ip, ports)

        open_ports = [p for p in port_results if p.is_open]
        result = {
            "ip": host.ip,
            "hostname": hostname,
            "ping_ms": host.response_time_ms,
            "open_ports": [{"port": p.port, "service": p.service_name, "response_ms": p.response_time_ms} for p in open_ports],
            "total_open_ports": len(open_ports),
        }
        results.append(result)

    return sorted(results, key=lambda r: r["ip"])


def check_connectivity(source_ip: str, target_ip: str, ports: Optional[List[int]] = None) -> ConnectivityReport:
    """
    全面连通性检测：ping + 端口扫描 + 稳定性评估

    Args:
        source_ip: 源IP（基站，如 192.168.1.200）
        target_ip: 目标IP（无人机图传设备，如 192.168.1.201）
        ports: 要检测的端口列表

    Returns:
        ConnectivityReport 连通性报告
    """
    if ports is None:
        ports = [554, 8080, 8000, 8554, 80, 443, 1883]

    # 扩展ping测试
    ping_info = ping_extended(target_ip, count=4)
    ping_result = PingResult(
        ip=target_ip,
        success=ping_info["success"] > 0,
        response_time_ms=ping_info["avg_response_ms"],
    )

    # 端口扫描
    port_results = scan_ports(target_ip, ports)

    # 构建报告
    open_count = sum(1 for p in port_results if p.is_open)
    report = ConnectivityReport(
        source_ip=source_ip,
        target_ip=target_ip,
        ping=ping_result,
        ports=port_results,
        packet_loss=ping_info["packet_loss_percent"],
        avg_response_ms=ping_info["avg_response_ms"],
        stability=ping_info["stability"],
        summary=f"连通性: {'良好' if ping_result.success and open_count > 0 else '异常'} | "
                f"丢包率: {ping_info['packet_loss_percent']}% | "
                f"开放端口: {open_count}/{len(ports)}",
    )
    return report


def _parse_ping_time(output: str) -> Optional[float]:
    """从ping输出中解析响应时间"""
    import re
    if IS_WINDOWS:
        match = re.search(r"时间[=<]\s*(\d+)ms", output)
        if match:
            return float(match.group(1))
        match = re.search(r"time[=<]\s*(\d+)ms", output)
        if match:
            return float(match.group(1))
    else:
        match = re.search(r"time=\s*(\d+\.?\d*)\s*ms", output)
        if match:
            return float(match.group(1))
    return None


def _resolve_hostname(ip: str) -> Optional[str]:
    """反查主机名"""
    try:
        return socket.getfqdn(ip)
    except Exception:
        return None


def _get_service_name(port: int) -> Optional[str]:
    """根据端口号获取常见服务名"""
    _SERVICE_MAP = {
        80: "HTTP",
        443: "HTTPS",
        554: "RTSP",
        8080: "HTTP-Alt",
        8000: "HTTP-Dev",
        8001: "HTTP-Dev2",
        8554: "RTSP-Alt",
        1935: "RTMP",
        1883: "MQTT",
        8883: "MQTT-TLS",
        21: "FTP",
        22: "SSH",
    }
    return _SERVICE_MAP.get(port)