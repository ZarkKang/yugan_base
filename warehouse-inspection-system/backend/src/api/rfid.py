"""
RFID API路由 - 读取/写入标签数据 (PRE系列 UHF 模块)
  GET  /api/v1/rfid/status         检查RFID连接状态
  POST /api/v1/rfid/connect        连接/重连RFID
  POST /api/v1/rfid/read           单次读取标签
  POST /api/v1/rfid/write          写入标签
  POST /api/v1/rfid/scan/start     启动连续扫描
  POST /api/v1/rfid/scan/stop      停止连续扫描
  POST /api/v1/rfid/scan/clear     清空标签缓存
  GET  /api/v1/rfid/tags           获取已扫描标签列表
  POST /api/v1/rfid/lock           锁定/解锁标签内存
  POST /api/v1/rfid/kill           杀死标签
  GET  /api/v1/rfid/power          获取发射功率
  POST /api/v1/rfid/power          设置发射功率
  POST /api/v1/rfid/query          设置盘存 Query 参数
  POST /api/v1/rfid/region         设置工作地区
"""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from ..hardware.rfid_reader import get_rfid_reader, RFIDTag
from ..schemas.schemas import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rfid", tags=["RFID"])


class RFIDConnectRequest(BaseModel):
    port: Optional[str] = Field(None, description="端口路径, 留空自动探测")
    baudrate: Optional[int] = Field(None, description="波特率, 如9600/115200")


class RFIDWriteRequest(BaseModel):
    data: str = Field(..., description="要写入的数据")
    tag_id: Optional[str] = Field(None, description="目标标签ID, 留空写入任意标签")


@router.get("/status")
def get_rfid_status():
    """获取RFID读卡器当前连接状态"""
    reader = get_rfid_reader()
    info = reader.get_connection_info()
    info["last_tags"] = [t.__dict__() for t in reader.get_last_tags()]
    return APIResponse(success=True, data=info)


@router.post("/connect")
def connect_rfid(req: RFIDConnectRequest):
    """连接/重新连接RFID读卡器"""
    reader = get_rfid_reader()
    # 如果已连接则断开重连
    if reader.is_connected():
        reader.disconnect()
    ok = reader.connect(port=req.port, baudrate=req.baudrate)
    info = reader.get_connection_info()
    if ok:
        return APIResponse(success=True, message="RFID已连接", data=info)
    else:
        return APIResponse(success=False, message="RFID连接失败，请检查硬件和串口", data=info)


@router.post("/read")
def read_rfid_tag():
    """单次读取RFID标签"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接，请先调用/rfid/connect")
    tag = reader.read_single_tag(timeout=3.0)
    if tag:
        return APIResponse(success=True, message="读取成功", data=tag.__dict__())
    else:
        return APIResponse(success=True, message="未扫描到标签", data=None)


@router.post("/write")
def write_rfid_tag(req: RFIDWriteRequest):
    """向RFID标签写入数据"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接，请先调用/rfid/connect")
    ok = reader.write_tag(data=req.data, tag_id=req.tag_id)
    if ok:
        return APIResponse(success=True, message="写入成功")
    else:
        return APIResponse(success=False, message="写入失败", data=None)


@router.post("/scan/start")
def start_continuous_scan():
    """启动连续RFID扫描"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.start_continuous_scan()
    return APIResponse(success=True, message="连续扫描已启动", data={"scanning": True})


@router.post("/scan/stop")
def stop_continuous_scan():
    """停止连续RFID扫描"""
    reader = get_rfid_reader()
    reader.stop_continuous_scan()
    return APIResponse(success=True, message="连续扫描已停止", data={"scanning": False})


@router.get("/tags")
def get_scanned_tags():
    """获取最近扫描到的RFID标签列表"""
    reader = get_rfid_reader()
    tags = reader.get_last_tags()
    return APIResponse(success=True, data={
        "total": len(tags),
        "tags": [t.__dict__() for t in tags]
    })


@router.post("/scan/clear")
def clear_tags():
    """清空标签缓存"""
    reader = get_rfid_reader()
    reader.clear_last_tags()
    return APIResponse(success=True, message="标签缓存已清空")


# ═══════════════════════════════════════════════════════════
#  PRE 模块扩展端点
# ═══════════════════════════════════════════════════════════

class LockRequest(BaseModel):
    lock_opt: int = Field(1, description="0=unlock, 1=lock, 2=perma_unlock, 3=perma_lock")
    mem_space: int = Field(2, description="0=KillPwd, 1=AccessPwd, 2=EPC, 3=TID, 4=User")
    access_pwd: Optional[str] = Field(None, description="访问密码(hex, 4字节), 默认00000000")


class KillRequest(BaseModel):
    kill_pwd: Optional[str] = Field(None, description="销毁密码(hex, 4字节), 默认00000000")


class PowerSetRequest(BaseModel):
    power_dbm: int = Field(..., ge=5, le=30, description="发射功率(dBm), 5-30")


class QueryParamsRequest(BaseModel):
    dr: int = Field(0, description="DR=8(0), DR=64/3(1)")
    m: int = Field(0, description="M=1(0), M=2(1), M=4(2), M=8(3)")
    trext: int = Field(1, description="0=无导频, 1=有导频")
    sel: int = Field(0, description="0/1=ALL, 2=~SL, 3=SL")
    session: int = Field(0, description="S0(0)-S3(3)")
    target: int = Field(0, description="A(0), B(1)")
    q: int = Field(4, ge=0, le=15, description="Q值, 0-15")


class RegionRequest(BaseModel):
    region: int = Field(..., description="0x01=中国2, 0x02=美标, 0x03=欧标, 0x04=中国1")


@router.post("/lock")
def lock_tag(req: LockRequest):
    """锁定/解锁标签内存"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = bytes.fromhex(req.access_pwd) if req.access_pwd else b'\x00\x00\x00\x00'
    ok = reader.lock_tag(lock_opt=req.lock_opt, mem_space=req.mem_space, access_pwd=pwd)
    return APIResponse(success=ok, message="操作成功" if ok else "操作失败")


@router.post("/kill")
def kill_tag(req: KillRequest):
    """杀死标签 (慎用)"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = bytes.fromhex(req.kill_pwd) if req.kill_pwd else b'\x00\x00\x00\x00'
    ok = reader.kill_tag(kill_pwd=pwd)
    return APIResponse(success=ok, message="标签已销毁" if ok else "销毁失败")


@router.get("/power")
def get_power():
    """获取当前发射功率(dBm)"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        raise HTTPException(status_code=503, detail="RFID未连接")
    pwr = reader.get_power()
    return APIResponse(success=pwr is not None, data={"power_dbm": pwr})


@router.post("/power")
def set_power(req: PowerSetRequest):
    """设置发射功率"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_power(req.power_dbm)
    return APIResponse(success=True, message=f"功率已设为 {req.power_dbm} dBm")


@router.post("/query")
def set_query_params(req: QueryParamsRequest):
    """设置盘存 Query 参数"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_query_params(
        dr=req.dr, m=req.m, trext=req.trext,
        sel=req.sel, session=req.session, target=req.target, q=req.q,
    )
    return APIResponse(success=True, message="Query参数已更新")


@router.post("/region")
def set_region(req: RegionRequest):
    """设置工作地区"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_region(req.region)
    return APIResponse(success=True, message=f"地区已设为 0x{req.region:02X}")