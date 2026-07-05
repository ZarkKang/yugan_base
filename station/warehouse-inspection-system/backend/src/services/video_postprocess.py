"""
视频后处理公共模块
==================
从 gateway.py 与 videos.py 抽取的公共视频后处理逻辑：
  抽帧 + 分组 + 拼接 + QR 识别 → 写 VideoData 状态 →
  写 InventoryItem → 触发 QR×RFID 交叉校验 → 广播事件

三条视频通道（multipart 上传、gateway Base64、WS 实时流）最终汇入此函数，
保证 QR 识别与库存判定逻辑一致。

调用方负责：
  1. 视频文件已落盘
  2. VideoData 记录已创建（含 source / stream_session_id / waypoint_markers 等字段）
  3. 调用 postprocess_video() 触发后处理
"""
import os
import json
import logging
from typing import Optional, List
from datetime import datetime

from ..db.database import SessionLocal
from ..models.models import VideoData, InventoryItem

logger = logging.getLogger(__name__)


def postprocess_video(
    file_path: str,
    video_rec_id: int,
    task_code: Optional[str] = None,
    waypoint_id: Optional[str] = None,
    expected_sku: Optional[str] = None,
    drone_code: Optional[str] = None,
    source: str = "upload",
) -> None:
    """
    视频后处理：抽帧 + QR 识别 + 写库存 + 交叉校验。

    在独立线程中调用（守护线程），由各调用方负责线程管理。
    本函数自行管理 SessionLocal 生命周期。

    Args:
        file_path: 视频文件绝对路径
        video_rec_id: VideoData 记录 ID（跨 Session 重新查询）
        task_code: 关联任务编号（可空）
        waypoint_id: 关联航点 ID（可空）
        expected_sku: 预期 SKU（来自 Waypoint.expected_sku，可空）
        drone_code: 无人机编号（仅用于日志，可空）
        source: 数据来源 'upload' / 'gateway' / 'ws_stream'（仅用于日志）

    流程：
      1. 抽帧 + 分组 + 拼接 + QR 识别（image.video_processor.process_video）
      2. 更新 VideoData: frame_count / qr_codes_json / processing_status
      3. 为每个 QR 写 InventoryItem（调用 gateway._classify_qr_inventory）
      4. 触发 QR×RFID 交叉校验（gateway._cross_validate_qr_rfid）
      5. 广播 video_processed 事件（gateway._broadcast）
    """
    db = SessionLocal()
    try:
        # 跨 Session 重新查询 VideoData
        video_rec = db.query(VideoData).filter(VideoData.id == video_rec_id).first()
        if not video_rec:
            logger.error("[VideoPostprocess] VideoData 记录不存在: id=%s", video_rec_id)
            return

        # 1. 抽帧 + 分组 + 拼接 + QR 识别
        try:
            from ..image.video_processor import process_video as process_video_file
            qr_codes, frame_count, status = process_video_file(file_path)
        except ImportError as e:
            logger.error("[VideoPostprocess] 视频处理模块导入失败: %s", e)
            video_rec.processing_status = "failed"
            video_rec.processing_error = f"视频处理模块不可用: {e}"
            db.commit()
            return
        except Exception as e:
            logger.error("[VideoPostprocess] 视频处理异常: %s", e, exc_info=True)
            video_rec.processing_status = "failed"
            video_rec.processing_error = str(e)
            db.commit()
            return

        # 2. 更新 VideoData 记录
        video_rec.frame_extracted = True
        video_rec.frame_count = frame_count
        video_rec.qr_codes_json = json.dumps(qr_codes, ensure_ascii=False)
        video_rec.qr_recognized = bool(qr_codes)
        video_rec.processing_status = status
        if status == "failed":
            video_rec.processing_error = "处理失败，详见日志"
        elif status == "timeout":
            video_rec.processing_error = "处理超时，部分结果可能不完整"
        db.commit()

        # 3. 为每个识别到的 QR 码写 InventoryItem + 触发交叉校验
        if qr_codes and task_code:
            # 懒导入避免循环依赖
            from ..api.gateway import _classify_qr_inventory, _cross_validate_qr_rfid, _broadcast

            for qr_text in qr_codes:
                inv_status, inv_msg = _classify_qr_inventory(
                    qr_text,
                    expected_sku=expected_sku,
                    task_code=task_code,
                    waypoint_id=waypoint_id,
                    db=db,
                )
                inv_item = InventoryItem(
                    sku=qr_text,
                    expected_sku=expected_sku,
                    expected_location="",
                    task_id=task_code,
                    waypoint_id=waypoint_id,
                    status=inv_status,
                    message=inv_msg,
                    confidence=0.8,
                    source_qr_data=qr_text,
                )
                db.add(inv_item)
            db.commit()
            logger.info(
                "[VideoPostprocess] QR识别写库存: %d 个 (video=%s, task=%s, source=%s, drone=%s)",
                len(qr_codes), video_rec.id, task_code, source, drone_code or "N/A",
            )

            # 触发 QR×RFID 交叉校验
            _cross_validate_qr_rfid(task_code, waypoint_id, qr_codes, rfid_epcs=None, db=db)

        logger.info(
            "[VideoPostprocess] 视频处理完成: id=%s frames=%d qr=%d status=%s source=%s",
            video_rec.id, frame_count, len(qr_codes), status, source,
        )

        # 4. 广播完成事件给 /ws/monitor
        try:
            from ..api.gateway import _broadcast
            _broadcast("video_processed", {
                "video_id": video_rec.id,
                "drone_code": drone_code,
                "task_code": task_code,
                "waypoint_id": waypoint_id,
                "frame_count": frame_count,
                "qr_count": len(qr_codes),
                "qr_codes": qr_codes[:10] if qr_codes else [],
                "status": status,
                "source": source,
            })
        except Exception as e:
            logger.debug("[VideoPostprocess] 广播事件失败: %s", e)

    except Exception as e:
        logger.error("[VideoPostprocess] 后台视频处理失败: %s", e, exc_info=True)
        try:
            video_rec = db.query(VideoData).filter(VideoData.id == video_rec_id).first()
            if video_rec:
                video_rec.processing_status = "failed"
                video_rec.processing_error = str(e)
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
