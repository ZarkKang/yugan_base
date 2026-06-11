"""
RFID API路由 - 读取/写入标签数据
  GET  /api/v1/rfid/status         检查RFID连接状态
  POST /api/v1/rfid/connect        连接/重连RFID
  POST /api/v1/rfid/read           单次读取标签
  POST /api/v1/rfid/write          写入标签
  POST /api/v1/rfid/scan-start     启动连续扫描
  POST /api/v1/rfid/scan-stop      停止连续扫描
  GET  /api/v1/rfid/tags           获取已扫描标签列表
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