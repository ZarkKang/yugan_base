"""
服务层 - 巡检数据处理服务
"""
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from ..models.models import InspectionRecord, Shelf, RFIDTag, Drone, InspectionStatus
from ..image.qr_code import QRCodeDecoder
from ..db.redis import RedisClient, RedisStream

logger = logging.getLogger(__name__)


class InspectionService:
    """巡检数据处理服务"""

    def __init__(self, db: Session):
        self.db = db
        self.qr_decoder = QRCodeDecoder()
        self.redis: Optional[RedisClient] = None

    def init_redis(self, redis_client: RedisClient):
        """初始化Redis连接"""
        self.redis = redis_client

    def process_qr_code(self, image_path: str) -> List[str]:
        """处理二维码识别"""
        try:
            codes = self.qr_decoder.decode_image(image_path)
            logger.info(f"识别到 {len(codes)} 个二维码: {codes}")
            return codes
        except Exception as e:
            logger.error(f"二维码处理失败: {e}")
            return []

    def process_qr_code_from_bytes(self, image_bytes: bytes) -> List[str]:
        """从字节数据处理二维码"""
        try:
            codes = self.qr_decoder.decode_bytes(image_bytes)
            return codes
        except Exception as e:
            logger.error(f"二维码处理失败: {e}")
            return []

    def match_inspection_data(
        self,
        qr_codes: List[str],
        rfid_tags: List[str],
        shelf_id: Optional[int] = None
    ) -> tuple[bool, Optional[str]]:
        """
        比对巡检数据

        Returns:
            (是否匹配, 不匹配原因)
        """
        if not qr_codes and not rfid_tags:
            return False, "无检测数据"

        if shelf_id:
            shelf = self.db.query(Shelf).filter(Shelf.id == shelf_id).first()
            if shelf and shelf.qr_code:
                if shelf.qr_code not in qr_codes:
                    return False, f"货架二维码不匹配: 期望 {shelf.qr_code}"

            # 检查RFID标签
            expected_tags = [tag.tag_id for tag in shelf.rfid_tags] if shelf else []
            found_tags = set(rfid_tags) & set(expected_tags)
            if len(found_tags) < len(expected_tags) * 0.8:
                return False, f"RFID标签匹配率过低: {len(found_tags)}/{len(expected_tags)}"

        return True, None

    def create_inspection_record(
        self,
        drone_id: int,
        record_code: str,
        qr_codes: Optional[List[str]] = None,
        rfid_tags: Optional[List[str]] = None,
        shelf_id: Optional[int] = None,
        rfid_tag_id: Optional[int] = None,
        image_path: Optional[str] = None,
        position: Optional[Dict[str, float]] = None
    ) -> Optional[InspectionRecord]:
        """创建巡检记录"""
        try:
            # 比对数据
            is_matched, reason = self.match_inspection_data(
                qr_codes or [],
                rfid_tags or [],
                shelf_id
            )

            record = InspectionRecord(
                record_code=record_code,
                drone_id=drone_id,
                shelf_id=shelf_id,
                rfid_tag_id=rfid_tag_id,
                qr_code_data=json.dumps(qr_codes) if qr_codes else None,
                rfid_data=json.dumps(rfid_tags) if rfid_tags else None,
                detected_qr_codes=json.dumps(qr_codes) if qr_codes else None,
                detected_rfid_tags=json.dumps(rfid_tags) if rfid_tags else None,
                image_path=image_path,
                is_matched=is_matched,
                mismatch_reason=reason,
                status=InspectionStatus.ABNORMAL if not is_matched else InspectionStatus.COMPLETED,
                inspection_time=datetime.now()
            )

            if position:
                record.drone_position_x = position.get("x")
                record.drone_position_y = position.get("y")
                record.drone_position_z = position.get("z")

            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)

            logger.info(f"创建巡检记录: {record_code}, 匹配: {is_matched}")
            return record

        except Exception as e:
            logger.error(f"创建巡检记录失败: {e}")
            self.db.rollback()
            return None

    def push_to_queue(self, stream_name: str, data: Dict[str, Any]) -> bool:
        """推送数据到消息队列"""
        if not self.redis or not self.redis.client:
            logger.warning("Redis未连接")
            return False
        try:
            stream = RedisStream(self.redis.client)
            stream.xadd(stream_name, data, maxlen=1000)
            return True
        except Exception as e:
            logger.error(f"推送队列失败: {e}")
            return False


class RFIDService:
    """RFID数据处理服务"""

    def __init__(self, db: Session):
        self.db = db

    def parse_rfid_data(self, raw_data: str) -> Optional[Dict[str, Any]]:
        """解析RFID原始数据"""
        # TODO: 根据实际RFID协议解析
        try:
            # 示例: TAG:xxx,RSSI:-60,TYPE:ISO15693
            result = {}
            for part in raw_data.split(","):
                key, value = part.split(":")
                result[key.lower()] = value
            return result
        except Exception as e:
            logger.error(f"RFID数据解析失败: {e}")
            return None

    def update_tag_read(self, tag_id: str, rssi: Optional[int] = None) -> bool:
        """更新标签读取信息"""
        try:
            tag = self.db.query(RFIDTag).filter(RFIDTag.tag_id == tag_id).first()
            if tag:
                tag.last_read_time = datetime.now()
                if rssi:
                    tag.last_read_strength = rssi
                self.db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"更新RFID标签失败: {e}")
            self.db.rollback()
            return False
