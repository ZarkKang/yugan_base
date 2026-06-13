"""
RFID自动入库服务
- 后台线程监听RFID标签 → EPC查RFIDTag → 事务更新库存 → 写入库记录
- 安全启停，与FastAPI lifespan shutdown联动
"""
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from ..db.database import SessionLocal
from ..models.models import RFIDTag, Inventory, InboundRecord
from ..hardware.rfid_reader import get_rfid_reader, RFIDTag as HWTag

logger = logging.getLogger(__name__)


class InboundService:
    """RFID自动入库服务（单例）"""

    def __init__(self):
        self._running = False
        self._tags_scanned = 0
        self._records_created = 0
        self._errors = 0
        self._started_at: Optional[datetime] = None
        self._stopped_at: Optional[datetime] = None
        self._lock = threading.Lock()

    # ── 公有接口 ──────────────────────────────────────────

    def start(self) -> Dict[str, Any]:
        """启动自动入库"""
        with self._lock:
            if self._running:
                return {"success": False, "message": "入库服务已在运行"}

            reader = get_rfid_reader()
            if not reader.is_connected():
                if not reader.connect():
                    return {"success": False, "message": "RFID读卡器连接失败，无法启动入库"}

            self._running = True
            self._tags_scanned = 0
            self._records_created = 0
            self._errors = 0
            self._started_at = datetime.now(timezone.utc)
            self._stopped_at = None

            # 注册回调
            reader.on_tag_detected = self._on_tag_detected
            reader.start_continuous_scan()

            logger.info("[入库] 自动入库已启动")
            return {"success": True, "message": "入库服务已启动"}

    def stop(self) -> Dict[str, Any]:
        """停止自动入库"""
        with self._lock:
            if not self._running:
                return {"success": False, "message": "入库服务未在运行"}

            self._running = False
            reader = get_rfid_reader()
            reader.stop_continuous_scan()
            reader.on_tag_detected = None
            self._stopped_at = datetime.now(timezone.utc)

            logger.info(f"[入库] 自动入库已停止, 扫描={self._tags_scanned}, 入库={self._records_created}, 错误={self._errors}")
            return {
                "success": True,
                "message": "入库服务已停止",
                "data": {
                    "tags_scanned": self._tags_scanned,
                    "records_created": self._records_created,
                    "errors": self._errors,
                }
            }

    def status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "success": True,
            "data": {
                "running": self._running,
                "tags_scanned": self._tags_scanned,
                "records_created": self._records_created,
                "errors": self._errors,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "stopped_at": self._stopped_at.isoformat() if self._stopped_at else None,
            }
        }

    # ── RFID 标签处理 ─────────────────────────────────────

    def _on_tag_detected(self, tag: HWTag):
        """RFID标签检测回调 — 在后台扫描线程中调用"""
        if not self._running:
            return

        with self._lock:
            self._tags_scanned += 1

        epc = tag.tag_id
        rssi = tag.rssi
        logger.debug(f"[入库] 检测到标签: EPC={epc}, RSSI={rssi}")

        db: Optional[Session] = None
        try:
            db = SessionLocal()
            self._process_tag(db, epc, rssi)
            db.commit()
            with self._lock:
                self._records_created += 1
        except Exception as e:
            if db:
                db.rollback()
            with self._lock:
                self._errors += 1
            logger.error(f"[入库] 处理标签失败 EPC={epc}: {e}", exc_info=True)
        finally:
            if db:
                db.close()

    def _process_tag(self, db: Session, epc: str, rssi: Optional[int]):
        """
        事务内处理单个标签:
          1. 查 RFIDTag 表 (tag_id == epc) → 获取 goods_name, shelf_id
          2. 若未注册 → 仅写入库失败记录
          3. 若已注册 → 更新 Inventory (quantity++, last_read_at)
                      → 写入库成功记录
        """
        rfid_tag = db.query(RFIDTag).filter(RFIDTag.tag_id == epc).first()

        if rfid_tag is None:
            record = InboundRecord(
                epc=epc,
                status="failed",
                message="RFID标签未在系统中注册",
                rssi=rssi,
                created_at=datetime.now(timezone.utc),
            )
            db.add(record)
            logger.warning(f"[入库] EPC={epc} 未注册，仅记录日志")
            return

        goods_name = rfid_tag.goods_name
        shelf_id = rfid_tag.shelf_id

        # UPSERT Inventory
        inv = db.query(Inventory).filter(Inventory.rfid_tag_id == rfid_tag.id).first()
        if inv is None:
            inv = Inventory(
                rfid_tag_id=rfid_tag.id,
                goods_name=goods_name,
                shelf_id=shelf_id,
                quantity=1,
                last_read_at=datetime.now(timezone.utc),
            )
            db.add(inv)
        else:
            inv.quantity += 1
            inv.last_read_at = datetime.now(timezone.utc)
            inv.goods_name = goods_name
            inv.shelf_id = shelf_id

        # INSERT InboundRecord
        record = InboundRecord(
            rfid_tag_id=rfid_tag.id,
            epc=epc,
            goods_name=goods_name,
            shelf_id=shelf_id,
            rssi=rssi,
            status="success",
            message="",
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)

        logger.info(f"[入库] EPC={epc} → {goods_name}, 库存+1")


# ═══════════════════════════════════════════════════════════
#  全局单例
# ═══════════════════════════════════════════════════════════
_inbound_service: Optional[InboundService] = None
_service_lock = threading.Lock()


def get_inbound_service() -> InboundService:
    """获取入库服务单例"""
    global _inbound_service
    with _service_lock:
        if _inbound_service is None:
            _inbound_service = InboundService()
        return _inbound_service