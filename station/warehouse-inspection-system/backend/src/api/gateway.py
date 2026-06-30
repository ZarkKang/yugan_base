"""
API路由 - 数据接收网关
=====================
核心数据流入口：接收无人机回传的原始数据（RFID、二维码、图像、传感器），
分类存储到数据库，触发后台异步处理（二维码识别、库存比对）。
"""
import json
import base64
import os
import re
import time
import logging
import threading
import queue
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..db.database import get_db, SessionLocal
from ..models.models import (
    Drone, Task, ImageRecord, InspectionRecord, RFIDTag, SKU, Inventory,
    InspectionStatus
)
from ..schemas.schemas import (
    DataReceiveRequest,
    DataReceiveResponse,
    QRCodeProcessRequest,
    QRCodeProcessResponse,
    APIResponse,
)
from ..hardware.rfid_reader import get_rfid_reader, RFIDTag as HWTag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gateway", tags=["数据接收"])

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")
DATA_DIR = os.path.join(STORAGE_ROOT, "gateway")
os.makedirs(DATA_DIR, exist_ok=True)

# EPC 格式校验: 24字符大写hex (ISO 18000-6C 标准)
EPC_PATTERN = re.compile(r'^[0-9A-F]{24}$')

# 后台处理队列
_processing_queue = queue.Queue(maxsize=1000)
_processor_started = False
_processor_lock = threading.Lock()


def _ensure_processor():
    """确保后台处理器已启动"""
    global _processor_started
    if _processor_started:
        return
    with _processor_lock:
        if _processor_started:
            return
        for i in range(2):
            t = threading.Thread(
                target=_background_worker,
                name=f"gateway-worker-{i}",
                daemon=True,
            )
            t.start()
        _processor_started = True
        logger.info("[Gateway] 后台处理器已启动 (2 workers)")


def _background_worker():
    """后台处理Worker - 从队列取出数据并处理"""
    while True:
        try:
            item = _processing_queue.get(timeout=5)
        except queue.Empty:
            continue
        try:
            _process_background_task(item)
        except Exception as e:
            logger.error(f"[Gateway] 后台处理异常: {e}", exc_info=True)
        finally:
            _processing_queue.task_done()


# ── 1. 数据接收入口 ────────────────────────────────

@router.post("/receive", response_model=DataReceiveResponse)
async def receive_data(
    request: DataReceiveRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    接收无人机回传的原始数据。

    支持的数据类型:
    - image:    Base64编码的图像数据
    - rfid:     JSON格式的RFID标签列表 '["TAG001","TAG002"]'
    - qr_code:  已解码的二维码内容字符串
    - sbus:     JSON格式的SBUS遥控器数据
    - video:    视频帧元数据

    示例请求:
    ```json
    {
      "drone_code": "DRONE001",
      "data_type": "rfid",
      "payload": "[\"E20000123456789012345678\", \"E20000876543210987654321\"]",
      "position_x": 1.5,
      "position_y": 2.0,
      "position_z": 3.0
    }
    ```
    """
    # 验证无人机
    drone = db.query(Drone).filter(Drone.drone_code == request.drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: {request.drone_code}")

    record_id = None

    # 根据数据类型分类处理
    if request.data_type == "rfid":
        # 异步处理: 立即返回200, 确保无人机端1.5s超时内收到响应
        _ensure_processor()
        try:
            _processing_queue.put({
                "type": "rfid",
                "drone_code": request.drone_code,
                "drone_id": drone.id,
                "payload": request.payload,
                "position_x": request.position_x,
                "position_y": request.position_y,
                "position_z": request.position_z,
                "timestamp": request.timestamp,
                "metadata": request.metadata,
            }, block=False)
        except queue.Full:
            # 队列满时降级为同步处理
            record_id = _handle_rfid_data(drone, request, db)
        else:
            return DataReceiveResponse(
                success=True,
                message="RFID数据已接收，正在后台处理",
                record_id=None
            )
    elif request.data_type == "qr_code":
        record_id = _handle_qrcode_data(drone, request, db)
    elif request.data_type == "image":
        # 图像数据较大，放入后台队列处理
        _ensure_processor()
        try:
            _processing_queue.put({
                "type": "image",
                "drone_code": request.drone_code,
                "drone_id": drone.id,
                "payload": request.payload,
                "position_x": request.position_x,
                "position_y": request.position_y,
                "position_z": request.position_z,
                "timestamp": request.timestamp,
            }, block=False)
        except queue.Full:
            logger.warning("[Gateway] 队列已满，图像数据被丢弃")
            raise HTTPException(status_code=503, detail="服务器繁忙，请稍后重试")
        return DataReceiveResponse(
            success=True,
            message="图像数据已接收，正在后台处理",
            record_id=None
        )
    elif request.data_type == "sbus":
        # SBUS遥控器数据 - 更新无人机位置
        _handle_sbus_data(drone, request, db)
    elif request.data_type == "video":
        record_id = _handle_video_data(drone, request, db)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的数据类型: {request.data_type}")

    return DataReceiveResponse(
        success=True,
        message=f"数据已接收 ({request.data_type})",
        record_id=record_id
    )


# ── 2. 后台处理 ────────────────────────────────────

def _process_background_task(item: dict):
    """后台处理单个数据项（在独立线程中运行）"""
    data_type = item.get("type")
    db = SessionLocal()
    try:
        if data_type == "image":
            _process_image_in_background(item, db)
        elif data_type == "rfid":
            _process_rfid_in_background(item, db)
    except Exception as e:
        logger.error(f"[Gateway] 后台处理失败 ({data_type}): {e}", exc_info=True)
    finally:
        db.close()


# ── 3. 数据类型处理器 ──────────────────────────────

def _parse_rfid_payload(payload) -> list:
    """
    解析 RFID payload，兼容两种格式:
    1. 字典列表 (无人机端实际格式): [{"epc":"...","rssi_dbm":-62,"stamp":...}]
    2. 字符串列表 (旧格式): ["EPC1","EPC2"]

    返回统一的 [{"epc","rssi_dbm","stamp"}] 列表，跳过非法EPC。
    """
    try:
        tags = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(tags, list):
            tags = [tags]
    except (json.JSONDecodeError, TypeError):
        tags = [payload]

    normalized = []
    for tag in tags:
        if isinstance(tag, dict):
            epc = str(tag.get("epc", "")).upper().strip()
            rssi = tag.get("rssi_dbm")
            stamp = tag.get("stamp")
        elif isinstance(tag, str):
            epc = tag.upper().strip()
            rssi = None
            stamp = None
        else:
            continue

        # 校验 EPC: 24字符大写hex
        if not EPC_PATTERN.match(epc):
            logger.warning("[Gateway] 跳过非法EPC: %r", epc[:30])
            continue

        # 校验 RSSI 范围 (如果有)
        if rssi is not None:
            try:
                rssi = int(rssi)
                if rssi < -120 or rssi > 0:
                    logger.warning("[Gateway] RSSI超出范围: %s (epc=%s)", rssi, epc)
                    rssi = None
            except (ValueError, TypeError):
                rssi = None

        normalized.append({"epc": epc, "rssi_dbm": rssi, "stamp": stamp})

    return normalized


def _process_rfid_payload(item: dict, db: Session) -> Optional[int]:
    """
    RFID数据处理核心逻辑 (同步降级和异步队列共用)。
    支持: 字典格式payload、EPC/RSSI校验、幂等去重(基于record_code)。
    """
    drone_id = item["drone_id"]
    drone = db.query(Drone).filter(Drone.id == drone_id).first()
    if not drone:
        logger.warning("[Gateway] 无人机不存在: id=%s", drone_id)
        return None

    payload = item["payload"]
    position_x = item.get("position_x")
    position_y = item.get("position_y")
    position_z = item.get("position_z")
    meta = item.get("metadata") or {}

    # 解析并校验
    tags = _parse_rfid_payload(payload)
    if not tags:
        logger.warning("[Gateway] RFID数据为空或全部非法 (drone=%s)", drone.drone_code)
        _update_drone_position_from_coords(drone, position_x, position_y, position_z, db)
        return None

    # 幂等键: 同一航点同一时间戳的重复上传只入库一次
    task_code = meta.get("task_code", "NOTASK")
    waypoint_id = meta.get("waypoint_id", 0)
    meta_ts = meta.get("timestamp", time.time())
    if isinstance(meta_ts, str):
        try:
            meta_ts = float(meta_ts)
        except (ValueError, TypeError):
            meta_ts = time.time()

    idempotent_key = "RFID_{}_{}_{}_{}".format(drone.id, task_code, waypoint_id, int(meta_ts))

    # 幂等检查: 已存在则跳过
    existing = db.query(InspectionRecord).filter(
        InspectionRecord.record_code == idempotent_key
    ).first()
    if existing:
        logger.info("[Gateway] RFID数据幂等跳过(已存在): %s", idempotent_key)
        _update_drone_position_from_coords(drone, position_x, position_y, position_z, db)
        return existing.id

    # 批量查询 RFIDTag (避免N+1)
    epc_list = [t["epc"] for t in tags]
    rfid_tags = db.query(RFIDTag).filter(RFIDTag.tag_id.in_(epc_list)).all()
    rfid_map = {rt.tag_id: rt for rt in rfid_tags}

    resolved_tags = []
    for tag in tags:
        epc = tag["epc"]
        rfid_tag = rfid_map.get(epc)
        if rfid_tag and rfid_tag.sku_id:
            resolved_tags.append({
                "epc": epc,
                "rssi_dbm": tag["rssi_dbm"],
                "sku_id": rfid_tag.sku_id,
                "goods_name": rfid_tag.goods_name,
                "shelf_id": rfid_tag.shelf_id,
            })
        else:
            resolved_tags.append({
                "epc": epc,
                "rssi_dbm": tag["rssi_dbm"],
                "sku_id": None,
                "goods_name": rfid_tag.goods_name if rfid_tag else None,
                "shelf_id": None,
            })

    record = InspectionRecord(
        record_code=idempotent_key,
        drone_id=drone.id,
        rfid_data=json.dumps(epc_list, ensure_ascii=False),
        detected_rfid_tags=json.dumps(resolved_tags, ensure_ascii=False),
        status=InspectionStatus.PENDING,
        drone_position_x=position_x,
        drone_position_y=position_y,
        drone_position_z=position_z,
        inspection_time=datetime.utcnow(),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(InspectionRecord).filter(
            InspectionRecord.record_code == idempotent_key
        ).first()
        logger.info("[Gateway] RFID数据并发幂等跳过: %s", idempotent_key)
        _update_drone_position_from_coords(drone, position_x, position_y, position_z, db)
        return existing.id if existing else None

    db.refresh(record)
    _update_drone_position_from_coords(drone, position_x, position_y, position_z, db)

    resolved_count = sum(1 for t in resolved_tags if t["sku_id"])
    logger.info("[Gateway] RFID数据: %d 标签, %d 已识别 (drone=%s, wp=%s)",
                len(tags), resolved_count, drone.drone_code, waypoint_id)
    return record.id


def _handle_rfid_data(drone: Drone, request: DataReceiveRequest, db: Session) -> Optional[int]:
    """处理RFID标签数据 (同步降级路径，队列满时调用)。"""
    item = {
        "drone_id": drone.id,
        "payload": request.payload,
        "position_x": request.position_x,
        "position_y": request.position_y,
        "position_z": request.position_z,
        "timestamp": request.timestamp,
        "metadata": request.metadata,
    }
    return _process_rfid_payload(item, db)


def _handle_qrcode_data(drone: Drone, request: DataReceiveRequest, db: Session) -> Optional[int]:
    """处理二维码数据"""
    qr_data = request.payload

    record = InspectionRecord(
        record_code=f"QR_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}",
        drone_id=drone.id,
        qr_code_data=qr_data,
        detected_qr_codes=json.dumps([qr_data], ensure_ascii=False),
        status=InspectionStatus.PENDING,
        drone_position_x=request.position_x,
        drone_position_y=request.position_y,
        drone_position_z=request.position_z,
        inspection_time=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    _update_drone_position(drone, request, db)

    logger.info(f"[Gateway] QR数据已存储: {qr_data[:50]} (drone={drone.drone_code})")
    return record.id


def _handle_sbus_data(drone: Drone, request: DataReceiveRequest, db: Session):
    """处理SBUS遥控器数据 - 更新无人机位置/状态"""
    _update_drone_position(drone, request, db)
    try:
        sbus_data = json.loads(request.payload) if isinstance(request.payload, str) else request.payload
        logger.debug(f"[Gateway] SBUS数据: {sbus_data}")
    except (json.JSONDecodeError, TypeError):
        pass


def _handle_video_data(drone: Drone, request: DataReceiveRequest, db: Session) -> Optional[int]:
    """处理视频帧元数据"""
    _update_drone_position(drone, request, db)

    record = InspectionRecord(
        record_code=f"VID_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}",
        drone_id=drone.id,
        status=InspectionStatus.PENDING,
        drone_position_x=request.position_x,
        drone_position_y=request.position_y,
        drone_position_z=request.position_z,
        inspection_time=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record.id


def _process_image_in_background(item: dict, db: Session):
    """后台处理图像数据 - 解码Base64并保存"""
    try:
        payload = item["payload"]
        drone_code = item["drone_code"]

        # 解码Base64图像
        if "," in payload and payload.startswith("data:"):
            # 处理 data:image/jpeg;base64,xxx 格式
            payload = payload.split(",", 1)[1]
        image_bytes = base64.b64decode(payload)

        # 保存到文件
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"gw_{drone_code}_{timestamp}.jpg"
        dir_path = os.path.join(DATA_DIR, drone_code)
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, filename)

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        file_size = len(image_bytes)

        # 创建ImageRecord
        from ..models.models import ImageRecord as ImgRec
        record = ImgRec(
            drone_id=item["drone_id"],
            file_path=file_path,
            file_name=filename,
            file_size=file_size,
            file_format="jpeg",
            position_x=item.get("position_x"),
            position_y=item.get("position_y"),
            position_z=item.get("position_z"),
            status="pending",
            queued_at=datetime.utcnow(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        # 提交到QR识别引擎
        try:
            from ..image.qr_worker import get_recognition_engine
            engine = get_recognition_engine()
            engine.submit(image_id=record.id, file_path=file_path, expected_sku=None)
        except Exception as e:
            logger.warning(f"[Gateway] QR识别提交失败: {e}")

        logger.info(f"[Gateway] 图像已保存: {record.id} ({file_size/1024:.1f}KB)")

    except base64.binascii.Error as e:
        logger.error(f"[Gateway] Base64解码失败: {e}")
    except Exception as e:
        logger.error(f"[Gateway] 图像处理失败: {e}", exc_info=True)


def _process_rfid_in_background(item: dict, db: Session):
    """后台处理RFID数据 (异步队列调用)"""
    try:
        _process_rfid_payload(item, db)
    except Exception as e:
        logger.error(f"[Gateway] RFID后台处理失败: {e}", exc_info=True)


# ── 4. 二维码处理 ──────────────────────────────────

@router.post("/qrcode/process", response_model=QRCodeProcessResponse)
async def process_qr_code(
    request: QRCodeProcessRequest,
    db: Session = Depends(get_db)
):
    """
    处理二维码识别请求。

    支持两种方式:
    1. image_path: 本地图像文件路径
    2. image_base64: Base64编码的图像数据

    返回识别到的二维码内容列表。
    """
    codes = []

    if request.image_base64:
        # 从Base64解码并识别
        try:
            import cv2
            import numpy as np

            payload = request.image_base64
            if "," in payload and payload.startswith("data:"):
                payload = payload.split(",", 1)[1]

            image_bytes = base64.b64decode(payload)
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is not None:
                # 使用pyzbar识别
                try:
                    from pyzbar.pyzbar import decode as pyzbar_decode
                    results = pyzbar_decode(img)
                    for r in results:
                        if r.type == 'QRCODE':
                            data = r.data.decode("utf-8", errors="ignore").strip()
                            if data:
                                codes.append(data)
                except ImportError:
                    logger.warning("[Gateway] pyzbar不可用，无法识别二维码")
                    return QRCodeProcessResponse(
                        success=False,
                        codes=[],
                        message="pyzbar未安装，请安装libzbar0"
                    )
            else:
                return QRCodeProcessResponse(success=False, codes=[], message="无法解码图像")

        except Exception as e:
            logger.error(f"[Gateway] QR识别异常: {e}")
            return QRCodeProcessResponse(success=False, codes=[], message=str(e))

    elif request.image_path:
        # 从文件路径读取并识别
        if not os.path.exists(request.image_path):
            return QRCodeProcessResponse(
                success=False,
                codes=[],
                message=f"图像文件不存在: {request.image_path}"
            )

        try:
            import cv2
            img = cv2.imread(request.image_path)
            if img is not None:
                try:
                    from pyzbar.pyzbar import decode as pyzbar_decode
                    results = pyzbar_decode(img)
                    for r in results:
                        if r.type == 'QRCODE':
                            data = r.data.decode("utf-8", errors="ignore").strip()
                            if data:
                                codes.append(data)
                except ImportError:
                    return QRCodeProcessResponse(
                        success=False,
                        codes=[],
                        message="pyzbar未安装"
                    )
        except Exception as e:
            logger.error(f"[Gateway] QR文件识别异常: {e}")
            return QRCodeProcessResponse(success=False, codes=[], message=str(e))

    else:
        return QRCodeProcessResponse(
            success=False,
            codes=[],
            message="请提供 image_path 或 image_base64"
        )

    return QRCodeProcessResponse(
        success=True,
        codes=codes,
        message=f"识别到 {len(codes)} 个二维码" if codes else "未识别到二维码"
    )


# ── 5. RFID读取 ────────────────────────────────────

@router.post("/rfid/read", response_model=DataReceiveResponse)
async def read_rfid(
    drone_code: str,
    db: Session = Depends(get_db)
):
    """
    通过RFID读卡器读取标签数据。

    会尝试连接硬件RFID读卡器并读取当前范围内的标签。
    读取到的标签会自动存入数据库。
    """
    # 验证无人机
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first()
    if not drone:
        raise HTTPException(status_code=404, detail=f"无人机不存在: {drone_code}")

    reader = get_rfid_reader()

    # 尝试连接
    if not reader.is_connected():
        if not reader.connect():
            return DataReceiveResponse(
                success=False,
                message="RFID读卡器未连接，请检查硬件"
            )

    # 读取标签
    tags = reader.read_multiple_tags(timeout=3.0, count=50)
    if not tags:
        return DataReceiveResponse(
            success=True,
            message="未检测到RFID标签",
            record_id=None
        )

    # 存入数据库
    tag_ids = [t.tag_id for t in tags]
    record = InspectionRecord(
        record_code=f"RFID_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:-3]}",
        drone_id=drone.id,
        rfid_data=json.dumps(tag_ids, ensure_ascii=False),
        detected_rfid_tags=json.dumps(tag_ids, ensure_ascii=False),
        status=InspectionStatus.PENDING,
        inspection_time=datetime.utcnow(),
    )
    db.add(record)

    # 同步RFID标签到标签表
    for tag in tags:
        existing = db.query(RFIDTag).filter(RFIDTag.tag_id == tag.tag_id).first()
        if existing:
            existing.last_read_time = datetime.utcnow()
            existing.last_read_strength = tag.rssi
        else:
            new_tag = RFIDTag(
                tag_id=tag.tag_id,
                last_read_time=datetime.utcnow(),
                last_read_strength=tag.rssi,
            )
            db.add(new_tag)

    db.commit()
    db.refresh(record)

    logger.info(f"[Gateway] RFID读取完成: {len(tags)} 个标签 (drone={drone_code})")
    return DataReceiveResponse(
        success=True,
        message=f"读取到 {len(tags)} 个标签",
        record_id=record.id
    )


# ── 辅助函数 ───────────────────────────────────────

def _update_drone_position(drone: Drone, request: DataReceiveRequest, db: Session):
    """更新无人机最后位置"""
    _update_drone_position_from_coords(
        drone, request.position_x, request.position_y, request.position_z, db
    )


def _update_drone_position_from_coords(drone: Drone, x, y, z, db: Session):
    """更新无人机最后位置 (坐标参数版本，供异步处理使用)"""
    updated = False
    if x is not None:
        drone.last_position_x = x
        updated = True
    if y is not None:
        drone.last_position_y = y
        updated = True
    if z is not None:
        drone.last_position_z = z
        updated = True
    if updated:
        drone.last_seen = datetime.utcnow()
        db.commit()


# ── 6. 巡检差异对比 ─────────────────────────────────

@router.get("/inspection/compare")
def compare_inspection_results(
    drone_id: int,
    db: Session = Depends(get_db),
):
    """
    巡检差异对比: 取最近两次巡检记录，对比标签变化。
    
    返回:
    - current: 当次扫描到的标签列表
    - previous: 上一次扫描到的标签列表
    - missing: 上次有、这次没有 (缺货)
    - extra: 上次没有、这次有 (多货)
    """
    records = (
        db.query(InspectionRecord)
        .filter(InspectionRecord.drone_id == drone_id)
        .filter(InspectionRecord.rfid_data.isnot(None))
        .order_by(InspectionRecord.inspection_time.desc())
        .limit(2)
        .all()
    )

    if len(records) < 2:
        return APIResponse(success=True, message="巡检次数不足，需要至少2次记录才能对比", data={
            "current": len(records),
            "previous": 0,
            "missing": [],
            "extra": [],
        })

    current = records[0]
    previous = records[1]

    # 解析检测到的标签
    def parse_tags(record):
        try:
            data = json.loads(record.detected_rfid_tags)
            if data and isinstance(data[0], dict):
                # 新格式: 结构化数据
                return [t["epc"] for t in data]
            # 旧格式: 纯EPC列表
            return data
        except (json.JSONDecodeError, TypeError):
            return []

    current_epcs = set(parse_tags(current))
    previous_epcs = set(parse_tags(previous))

    missing = list(previous_epcs - current_epcs)
    extra = list(current_epcs - previous_epcs)

    # 解析为结构化
    def resolve_epcs(epcs):
        result = []
        for epc in epcs:
            tag = db.query(RFIDTag).filter(RFIDTag.tag_id == epc).first()
            result.append({
                "epc": epc,
                "sku_id": tag.sku_id if tag else None,
                "goods_name": tag.goods_name if tag else None,
            })
        return result

    return APIResponse(success=True, message="对比完成", data={
        "current": {
            "record_id": current.id,
            "time": str(current.inspection_time),
            "tags": resolve_epcs(current_epcs),
        },
        "previous": {
            "record_id": previous.id,
            "time": str(previous.inspection_time),
            "tags": resolve_epcs(previous_epcs),
        },
        "missing": resolve_epcs(missing),
        "extra": resolve_epcs(extra),
        "summary": f"异常: 缺货 {len(missing)} 个, 多货 {len(extra)} 个",
    })


# ── 7. 失败数据重放 ──────────────────────────────────

@router.post("/replay", response_model=APIResponse)
async def replay_failed_records(
    request: dict,
    db: Session = Depends(get_db)
):
    """
    重放无人机端 failed.jsonl 中的失败记录。

    无人机端上传失败后会写本地 logs/uav_ground_bridge_failed.jsonl,
    每行一个 JSON: {"kind":"heartbeat|waypoint_result","url":"...","body":{...},"error":"...","time":...}
    用户可手动提取这些记录, 通过本接口重新提交。
    幂等: 已成功入库的记录会自动跳过。
    """
    drone_code = request.get("drone_code")
    records = request.get("records", [])

    if not records:
        return APIResponse(success=False, message="未提供重放记录")

    # 验证无人机
    drone = db.query(Drone).filter(Drone.drone_code == drone_code).first() if drone_code else None

    replayed = 0
    skipped = 0
    failed = 0

    for record in records:
        try:
            kind = record.get("kind", "")
            body = record.get("body", {})

            if kind == "waypoint_result" and drone:
                # 重放 RFID 上传
                item = {
                    "drone_id": drone.id,
                    "payload": body.get("payload", ""),
                    "position_x": body.get("position_x"),
                    "position_y": body.get("position_y"),
                    "position_z": body.get("position_z"),
                    "metadata": body.get("metadata", {}),
                }
                result_id = _process_rfid_payload(item, db)
                if result_id is not None:
                    replayed += 1
                else:
                    skipped += 1

            elif kind == "heartbeat" and drone:
                # 重放心跳 (仅更新状态, 无需返回值)
                drone.status = body.get("status", drone.status)
                drone.battery_level = body.get("battery", drone.battery_level)
                pos = body.get("position", {})
                if pos:
                    drone.last_position_x = pos.get("x", drone.last_position_x)
                    drone.last_position_y = pos.get("y", drone.last_position_y)
                    drone.last_position_z = pos.get("z", drone.last_position_z)
                drone.last_seen = datetime.utcnow()
                db.commit()
                replayed += 1

            else:
                skipped += 1

        except Exception as e:
            logger.error(f"[Gateway] 重放失败: {e}", exc_info=True)
            failed += 1

    return APIResponse(
        success=True,
        message=f"重放完成: {replayed}条成功, {skipped}条跳过, {failed}条失败",
        data={"replayed": replayed, "skipped": skipped, "failed": failed}
    )