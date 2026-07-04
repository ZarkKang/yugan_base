"""
RFID API路由 - 读取/写入标签数据 (PRE系列 UHF 模块)
  GET  /api/v1/rfid/diagnose       诊断RFID连接环境
  GET  /api/v1/rfid/status         检查RFID连接状态
  POST /api/v1/rfid/connect        连接/重连RFID
  POST /api/v1/rfid/read           单次读取标签
  POST /api/v1/rfid/write          写入标签
  POST /api/v1/rfid/scan/start     启动连续扫描
  POST /api/v1/rfid/scan/stop      停止连续扫描
  POST /api/v1/rfid/scan/clear     清空标签缓存
  GET  /api/v1/rfid/tags           获取已扫描标签列表
  POST /api/v1/rfid/bind           绑定SKU到RFID标签 (写标签+注册数据库)
  POST /api/v1/rfid/verify         验证标签绑定 (读标签+查数据库)
  GET  /api/v1/rfid/registered-tags 列出所有已注册标签
  POST /api/v1/rfid/lock           锁定/解锁标签内存
  POST /api/v1/rfid/kill           杀死标签
  GET  /api/v1/rfid/power          获取发射功率
  POST /api/v1/rfid/power          设置发射功率
  POST /api/v1/rfid/query          设置盘存 Query 参数
  POST /api/v1/rfid/region         设置工作地区

  ── 看板扩展（本次新增） ──
  GET  /api/v1/rfid/scan/history   拉取扫描事件历史（增量轮询）
  GET  /api/v1/rfid/scan/stats     看板统计（总数/唯一标签/分类计数）
  POST /api/v1/rfid/scan/clear-history  清空扫描历史
  POST /api/v1/rfid/scan/auto      启停"自动扫描模式"（封装 connect+start）
"""
import logging
import sys
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..hardware.rfid_reader import get_rfid_reader, RFIDTag as RFIDTagHW
from ..hardware.serial import list_available_ports
from ..models.models import RFIDTag as RFIDTagDB, SKU
from ..db.database import get_db
from ..schemas.schemas import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rfid", tags=["RFID"])


# ═══════════════════════════════════════════════════════════
#  诊断端点
# ═══════════════════════════════════════════════════════════

@router.get("/diagnose")
def diagnose():
    """诊断RFID连接环境 — 检测串口、驱动和模块状态"""
    diagnostic = {
        "success": True,
        "data": {
            "platform": sys.platform,
            "pyserial_available": False,
            "serial_ports": [],
            "reader_connected": False,
            "reader_scanning": False,
            "connection_info": {},
            "issues": [],
        }
    }

    # 1. 检查 pyserial
    try:
        import serial
        diagnostic["data"]["pyserial_available"] = True
    except ImportError:
        diagnostic["data"]["issues"].append({
            "level": "critical",
            "msg": "pyserial 未安装，请执行: pip install pyserial",
        })

    # 2. 列出串口
    try:
        ports = list_available_ports()
        diagnostic["data"]["serial_ports"] = ports
        if not ports:
            diagnostic["data"]["issues"].append({
                "level": "warning",
                "msg": "未检测到任何串口。请检查: (1) RFID模块电源指示灯 (2) USB线是否插紧 (3) CP2102驱动是否安装",
            })
    except Exception as e:
        diagnostic["data"]["issues"].append({
            "level": "error",
            "msg": f"无法检测串口: {e}",
        })

    # 3. 检查RFID读卡器状态
    try:
        reader = get_rfid_reader()
        diagnostic["data"]["reader_connected"] = reader.is_connected()
        diagnostic["data"]["reader_scanning"] = reader._running
        diagnostic["data"]["connection_info"] = reader.get_connection_info()
        if not reader.is_connected():
            diagnostic["data"]["issues"].append({
                "level": "info",
                "msg": "RFID读卡器未连接。调用 POST /rfid/connect 或 POST /rfid/connect?port=COM3 连接",
            })
    except Exception as e:
        diagnostic["data"]["issues"].append({
            "level": "error",
            "msg": f"RFID读卡器异常: {e}",
        })

    # 4. 平台特定提示
    if sys.platform == "win32":
        diagnostic["data"]["issues"].append({
            "level": "info",
            "msg": "Windows系统: 请确认设备管理器中有 COM 端口且无黄色感叹号。CP2102驱动: https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers",
        })
    elif "linux" in sys.platform:
        diagnostic["data"]["issues"].append({
            "level": "info",
            "msg": "Linux系统: 请确认 /dev/ttyUSB* 存在且有读写权限 (sudo chmod 666 /dev/ttyUSB0)",
        })

    return diagnostic


@router.get("/ports")
def list_ports():
    """扫描可用串口列表"""
    try:
        ports = list_available_ports()
        return APIResponse(success=True, data={"ports": ports})
    except Exception as e:
        return APIResponse(success=False, message=f"扫描串口失败: {e}", data={"ports": []})


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


@router.post("/disconnect")
def disconnect_rfid():
    """断开RFID读卡器连接"""
    reader = get_rfid_reader()
    reader.disconnect()
    return APIResponse(success=True, message="RFID已断开连接")


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
#  看板扩展端点（扫描历史 / 统计 / 自动扫描模式）
# ═══════════════════════════════════════════════════════════

@router.get("/scan/history")
def get_scan_history(
    limit: int = Query(100, ge=1, le=1000, description="最多返回条数"),
    since: float = Query(0.0, ge=0.0, description="仅返回 read_time > since 的事件（Unix 秒）"),
):
    """拉取扫描事件历史（最新在前，支持增量轮询）

    前端看板用法：首次 since=0 拉全量，之后用上一轮最大 read_time 作为 since 增量拉取。
    """
    reader = get_rfid_reader()
    items = reader.get_scan_history(limit=limit, since=since)
    # 序列化时间戳为 ISO 字符串，便于前端展示
    serialized = [
        {
            "tag_id": e["tag_id"],
            "rssi": e["rssi"],
            "pc": e["pc"],
            "crc": e["crc"],
            "read_time": e["read_time"],
            "read_time_iso": datetime.fromtimestamp(e["read_time"]).isoformat() if e["read_time"] else None,
            "mode": e["mode"],
        }
        for e in items
    ]
    return APIResponse(success=True, data={
        "total": len(serialized),
        "events": serialized,
    })


@router.get("/scan/stats")
def get_scan_stats():
    """看板统计：总数、唯一标签、auto/single/manual 分类计数、扫描状态"""
    reader = get_rfid_reader()
    stats = reader.get_scan_stats()
    return APIResponse(success=True, data=stats)


@router.post("/scan/clear-history")
def clear_scan_history():
    """清空扫描事件历史（不清空 _last_tags 缓存）"""
    reader = get_rfid_reader()
    reader.clear_scan_history()
    return APIResponse(success=True, message="扫描历史已清空")


class AutoScanRequest(BaseModel):
    enable: bool = Field(..., description="true=启动自动扫描(连接+开始), false=停止")


@router.post("/scan/auto")
def set_auto_scan(req: AutoScanRequest):
    """启停"自动扫描模式" — 一键封装 connect + start_continuous_scan

    与 /scan/start 区别：本端点会先确保已连接，便于前端"一键启动"。
    停止时仅停扫描，不断开连接。
    """
    reader = get_rfid_reader()
    if req.enable:
        if not reader.is_connected():
            if not reader.connect():
                return APIResponse(success=False, message="RFID连接失败，无法启动自动扫描")
        if reader._running:
            return APIResponse(success=True, message="自动扫描已在运行", data={"scanning": True})
        reader.start_continuous_scan()
        return APIResponse(success=True, message="自动扫描已启动", data={"scanning": True})
    else:
        reader.stop_continuous_scan()
        return APIResponse(success=True, message="自动扫描已停止", data={"scanning": False})


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


# ═══════════════════════════════════════════════════════════
#  SKU绑定RFID标签（基站端核心操作）
# ═══════════════════════════════════════════════════════════

class BindRequest(BaseModel):
    sku_id: int = Field(..., description="SKU ID — 将标签绑定到此商品")
    goods_name: Optional[str] = None
    shelf_id: Optional[int] = None
    quantity: int = 1


class VerifyRequest(BaseModel):
    tag_id: Optional[str] = Field(None, description="指定标签ID, 留空读取当前标签")


@router.post("/bind")
def bind_sku_to_tag(req: BindRequest, db: Session = Depends(get_db)):
    """
    基站端: 将SKU绑定到RFID标签
    流程: 1.查SKU → 2.扫描标签获取EPC → 3.写入SKU编码到标签 → 4.注册RFIDTag表
    返回: 绑定的EPC和SKU信息
    """
    # 0. 验证 SKU 存在
    sku = db.query(SKU).filter(SKU.id == req.sku_id).first()
    if not sku:
        return APIResponse(success=False, message=f"SKU不存在: id={req.sku_id}", data=None)

    goods_name = req.goods_name or sku.name

    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接，请先调用 /rfid/connect")

    # 1. 扫描标签获取 EPC
    tag = reader.read_single_tag(timeout=3.0)
    if tag is None:
        return APIResponse(success=False, message="未检测到RFID标签，请将标签靠近读卡器后重试", data=None)

    epc = tag.tag_id
    rssi = tag.rssi
    logger.info(f"[RFID Bind] 检测到标签 EPC={epc}, RSSI={rssi}")

    # 2. 写入SKU名称到标签User内存区
    data = goods_name.encode("utf-8")
    ok = reader.write_tag(data=data, tag_id=epc, mem_bank=3, start_addr=0)
    if not ok:
        return APIResponse(success=False, message=f"写入标签失败: EPC={epc}", data={"epc": epc})

    logger.info(f"[RFID Bind] 写入成功 EPC={epc} → SKU#{sku.id} {goods_name}")

    # 3. 注册到 RFIDTag 数据库表
    try:
        existing = db.query(RFIDTagDB).filter(RFIDTagDB.tag_id == epc).first()
        if existing:
            existing.sku_id = req.sku_id
            existing.goods_name = goods_name
            existing.shelf_id = req.shelf_id
            existing.goods_quantity = req.quantity
            existing.tag_type = "UHF-GEN2"
            existing.last_read_time = datetime.utcnow()
            existing.last_read_strength = rssi
            msg = f"标签已更新: EPC={epc} → SKU#{sku.id} {goods_name}"
        else:
            new_tag = RFIDTagDB(
                tag_id=epc,
                tag_type="UHF-GEN2",
                sku_id=req.sku_id,
                goods_name=goods_name,
                goods_quantity=req.quantity,
                shelf_id=req.shelf_id,
                last_read_strength=rssi,
            )
            db.add(new_tag)
            msg = f"绑定成功: EPC={epc} → SKU#{sku.id} {goods_name}"
        db.commit()
        logger.info(f"[RFID Bind] {msg}")
    except Exception as e:
        db.rollback()
        logger.error(f"[RFID Bind] 数据库注册失败: {e}")
        return APIResponse(success=False, message=f"数据库注册失败: {e}", data={"epc": epc})

    return APIResponse(success=True, message=msg, data={
        "epc": epc,
        "sku_id": req.sku_id,
        "goods_name": goods_name,
        "rssi": rssi,
        "shelf_id": req.shelf_id,
        "quantity": req.quantity,
    })


@router.post("/verify")
def verify_tag_binding(req: VerifyRequest, db: Session = Depends(get_db)):
    """
    基站端: 读取标签并验证与数据库的绑定是否匹配
    可用于: (1)基站自测 (2)无人机扫描后回传EPC验证
    """
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")

    # 读取标签
    tag = reader.read_single_tag(timeout=3.0)
    if tag is None:
        return APIResponse(success=False, message="未检测到标签", data=None)

    epc = tag.tag_id
    rssi = tag.rssi

    # 读标签 User 内存区获取写入的 SKU 标识
    try:
        user_data = reader.read_tag_data(mem_bank=3, start_addr=0, word_count=32)
        goods_from_tag = bytes(user_data).decode("utf-8", errors="replace").strip("\x00").strip() if user_data else ""
    except Exception:
        goods_from_tag = ""

    # 查数据库
    record = db.query(RFIDTagDB).filter(RFIDTagDB.tag_id == epc).first()
    if record:
        return APIResponse(success=True, message="验证成功: 标签已注册", data={
            "epc": epc,
            "rssi": rssi,
            "sku_id": record.sku_id,
            "tag_goods_name": goods_from_tag,
            "registered_goods_name": record.goods_name,
            "shelf_id": record.shelf_id,
            "quantity": record.goods_quantity,
            "match": goods_from_tag == record.goods_name,
        })
    else:
        return APIResponse(success=True, message="标签未在数据库中注册", data={
            "epc": epc,
            "rssi": rssi,
            "tag_goods_name": goods_from_tag,
            "registered_goods_name": None,
            "registered": False,
        })


@router.get("/registered-tags")
def get_registered_tags(db: Session = Depends(get_db)):
    """基站端: 列出所有已注册的RFID标签 (RFIDTag表全量)"""
    try:
        tags = db.query(RFIDTagDB).order_by(RFIDTagDB.created_at.desc()).all()
        return APIResponse(success=True, data={
            "total": len(tags),
            "tags": [
                {
                    "id": t.id,
                    "tag_id": t.tag_id,
                    "tag_type": t.tag_type,
                    "goods_name": t.goods_name,
                    "goods_quantity": t.goods_quantity,
                    "shelf_id": t.shelf_id,
                    "last_read_time": str(t.last_read_time) if t.last_read_time else None,
                    "last_read_strength": t.last_read_strength,
                    "created_at": str(t.created_at) if t.created_at else None,
                }
                for t in tags
            ]
        })
    except Exception as e:
        logger.error(f"[RFID] 查询注册标签失败: {e}")
        return APIResponse(success=False, message=f"查询失败: {e}", data={"tags": []})


# ═══════════════════════════════════════════════════════════
#  PRE 模块完整设置端点（对齐 PC 上位机全部功能）
# ═══════════════════════════════════════════════════════════

class FHSSRequest(BaseModel):
    on: bool = Field(..., description="FHSS开关: true=开, false=关")


class CWRequest(BaseModel):
    on: bool = Field(..., description="CW载波: true=开, false=关")


class ChannelRequest(BaseModel):
    channel: int = Field(..., description="RF信道编号")


class ModemRequest(BaseModel):
    mixer_gain: int = Field(3, ge=0, le=7, description="混频器增益 0-7")
    if_gain: int = Field(6, ge=0, le=7, description="中频增益 0-7")
    signal_threshold: int = Field(120, description="解码阈值")


class SelectRequest(BaseModel):
    target: int = Field(4, description="S0(0)/S1(1)/S2(2)/S3(3)/SL(4)")
    action: int = Field(0, description="Action, 参考ISO18000-6C")
    mem_bank: int = Field(1, description="0=RFU, 1=EPC, 2=TID, 3=USR")
    pointer: int = Field(32, description="起始地址(32bit)")
    mask_len: int = Field(0, description="Mask长度(bit)")
    mask: str = Field("", description="Mask数据(hex)")
    truncated: int = Field(0, description="0=禁用, 1=启用Truncate")


class InventoryModeRequest(BaseModel):
    mode: int = Field(..., ge=0, le=2, description="0=每次发Select, 1=不发, 2=除盘存外发")


class EnvModeRequest(BaseModel):
    mode: int = Field(..., ge=0, le=1, description="0=高灵敏, 1=密集读卡器")


class NVConfigRequest(BaseModel):
    enable: bool = Field(True, description="true=启用NV配置, false=禁用(擦除)")


class SleepTimeRequest(BaseModel):
    minutes: int = Field(..., ge=0, le=255, description="空闲休眠时间(分钟)")


class IOControlRequest(BaseModel):
    opt_type: int = Field(..., description="0=设置方向, 1=设置电平, 2=读取电平")
    io_port: int = Field(..., ge=1, le=4, description="IO端口 1-4")
    mode_or_level: int = Field(0, description="opt=0时: 0=输入,1=输出; opt=1时: 0=低,1=高")


class NXPConfigRequest(BaseModel):
    access_pwd: str = Field("00000000", description="访问密码(hex, 8字符)")
    config_data: int = Field(..., description="16位Config数据(要置1的位)")


class NXPReadProtectRequest(BaseModel):
    access_pwd: str = Field("00000000", description="访问密码(hex, 8字符)")
    is_reset: bool = Field(False, description="true=ResetReadProtect, false=ReadProtect")


class NXPEASRequest(BaseModel):
    access_pwd: str = Field("00000000", description="访问密码(hex, 8字符)")
    is_set: bool = Field(True, description="true=Set PSF, false=Reset PSF")


class MonzaQTRequest(BaseModel):
    access_pwd: str = Field("00000000", description="访问密码(hex, 8字符)")
    is_write: bool = Field(False, description="false=QT Read, true=QT Write")
    qt_sr: bool = Field(False, description="true=缩短距离, false=正常距离")
    qt_mem: bool = Field(False, description="true=Public Memory, false=Private Memory")
    is_persistence: bool = Field(True, description="true=写入NV, false=仅volatile")


# ── 模块信息 ──────────────────────────────────────────────

@router.get("/info")
def get_module_info():
    """获取模块信息(硬件版本/软件版本/厂商)"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    info = reader.get_module_info()
    return APIResponse(success=info is not None, data={"module_info": info})


# ── FHSS / CW ─────────────────────────────────────────────

@router.post("/fhss")
def set_fhss(req: FHSSRequest):
    """设置FHSS跳频开关"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_fhss(req.on)
    return APIResponse(success=True, message=f"FHSS已{'开启' if req.on else '关闭'}")


@router.post("/cw")
def set_cw(req: CWRequest):
    """设置CW载波开关"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_cw(req.on)
    return APIResponse(success=True, message=f"CW载波已{'开启' if req.on else '关闭'}")


# ── RF 信道 ────────────────────────────────────────────────

@router.post("/channel")
def set_channel(req: ChannelRequest):
    """设置RF信道"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_rf_channel(req.channel)
    return APIResponse(success=True, message=f"RF信道已设为 {req.channel}")


@router.get("/channel")
def get_channel():
    """获取当前RF信道"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        raise HTTPException(status_code=503, detail="RFID未连接")
    ch = reader.get_rf_channel()
    return APIResponse(success=ch is not None, data={"channel": ch})


# ── Modem 参数 ─────────────────────────────────────────────

@router.post("/modem")
def set_modem(req: ModemRequest):
    """设置Modem参数"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_modem_params(
        mixer_gain=req.mixer_gain,
        if_gain=req.if_gain,
        signal_threshold=req.signal_threshold,
    )
    return APIResponse(success=True, message="Modem参数已更新")


@router.get("/modem")
def get_modem():
    """读取Modem参数"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        raise HTTPException(status_code=503, detail="RFID未连接")
    params = reader.get_modem_params()
    return APIResponse(success=params is not None, data=params)


# ── Select 参数 ────────────────────────────────────────────

@router.post("/select")
def set_select(req: SelectRequest):
    """设置ISO18000-6C Select参数"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    mask_bytes = bytes.fromhex(req.mask) if req.mask else b''
    reader.set_select_params(
        target=req.target, action=req.action, mem_bank=req.mem_bank,
        pointer=req.pointer, mask_len=req.mask_len, mask=mask_bytes,
        truncated=req.truncated,
    )
    return APIResponse(success=True, message="Select参数已更新")


@router.get("/select")
def get_select():
    """获取Select参数"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        raise HTTPException(status_code=503, detail="RFID未连接")
    params = reader.get_select_params()
    return APIResponse(success=params is not None, data=params)


# ── 盘存模式 / 环境模式 ────────────────────────────────────

@router.post("/mode")
def set_inventory_mode(req: InventoryModeRequest):
    """设置盘存模式"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_inventory_mode(req.mode)
    mode_names = {0: "每条命令前发Select", 1: "不发Select", 2: "除盘存外发Select"}
    return APIResponse(success=True, message=f"盘存模式已设为: {mode_names.get(req.mode, str(req.mode))}")


@router.post("/env")
def set_env_mode(req: EnvModeRequest):
    """设置读卡器环境模式"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_reader_env_mode(req.mode)
    env_names = {0: "高灵敏模式", 1: "密集读卡器模式"}
    return APIResponse(success=True, message=f"环境模式已设为: {env_names.get(req.mode, str(req.mode))}")


# ── NV 配置 ────────────────────────────────────────────────

@router.post("/nv/save")
def save_nv_config(req: NVConfigRequest):
    """保存配置到NV Memory"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.save_config_to_nv(req.enable)
    if req.enable:
        return APIResponse(success=True, message="配置已保存到NV Memory，下次上电自动加载")
    else:
        return APIResponse(success=True, message="NV配置已禁用并擦除")


@router.post("/nv/load")
def load_nv_config():
    """从NV Memory加载配置"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.load_config_from_nv()
    return APIResponse(success=True, message="已从NV Memory加载配置")


# ── 休眠 ───────────────────────────────────────────────────

@router.post("/sleep")
def module_sleep():
    """设置模块立即休眠"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.module_sleep()
    return APIResponse(success=True, message="模块已进入休眠模式")


@router.post("/sleep/time")
def set_sleep_time(req: SleepTimeRequest):
    """设置空闲休眠时间"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.set_sleep_time(req.minutes)
    return APIResponse(success=True, message=f"空闲休眠时间已设为 {req.minutes} 分钟")


# ── 重启 ───────────────────────────────────────────────────

@router.post("/restart")
def restart_module():
    """重启RFID模块"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.scanner_restart()
    return APIResponse(success=True, message="模块重启指令已发送")


# ── IO 控制 ────────────────────────────────────────────────

@router.post("/io")
def io_control(req: IOControlRequest):
    """IO控制"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.io_control(req.opt_type, req.io_port, req.mode_or_level)
    return APIResponse(success=True, message="IO控制指令已发送")


# ── 干扰扫描 / RSSI ────────────────────────────────────────

@router.post("/jammer")
def scan_jammer():
    """扫描干扰"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.scan_jammer()
    return APIResponse(success=True, message="干扰扫描已启动")


@router.post("/rssi")
def scan_rssi():
    """扫描RSSI"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.scan_rssi()
    return APIResponse(success=True, message="RSSI扫描已启动")


# ── NXP G2X 特殊指令 ───────────────────────────────────────

@router.post("/nxp/config")
def nxp_change_config(req: NXPConfigRequest):
    """NXP G2X ChangeConfig"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = req.access_pwd if req.access_pwd else "00000000"
    reader.nxp_change_config(pwd, req.config_data)
    return APIResponse(success=True, message="NXP ChangeConfig已发送")


@router.post("/nxp/readprotect")
def nxp_read_protect(req: NXPReadProtectRequest):
    """NXP G2X ReadProtect / ResetReadProtect"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = req.access_pwd if req.access_pwd else "00000000"
    reader.nxp_read_protect(pwd, req.is_reset)
    msg = "ResetReadProtect" if req.is_reset else "ReadProtect"
    return APIResponse(success=True, message=f"NXP {msg}已发送")


@router.post("/nxp/eas")
def nxp_change_eas(req: NXPEASRequest):
    """NXP G2X ChangeEAS"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = req.access_pwd if req.access_pwd else "00000000"
    reader.nxp_change_eas(pwd, req.is_set)
    msg = "Set PSF" if req.is_set else "Reset PSF"
    return APIResponse(success=True, message=f"NXP ChangeEAS ({msg})已发送")


@router.post("/nxp/alarm")
def nxp_eas_alarm():
    """NXP G2X EAS Alarm"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    reader.nxp_eas_alarm()
    return APIResponse(success=True, message="NXP EAS Alarm已发送")


# ── Monza QT ───────────────────────────────────────────────

@router.post("/monza/qt")
def monza_qt(req: MonzaQTRequest):
    """Monza QT Read/Write"""
    reader = get_rfid_reader()
    if not reader.is_connected():
        if not reader.connect():
            raise HTTPException(status_code=503, detail="RFID未连接")
    pwd = req.access_pwd if req.access_pwd else "00000000"
    reader.monza_qt(pwd, req.is_write, req.qt_sr, req.qt_mem, req.is_persistence)
    msg = "QT Write" if req.is_write else "QT Read"
    return APIResponse(success=True, message=f"Monza {msg}已发送")