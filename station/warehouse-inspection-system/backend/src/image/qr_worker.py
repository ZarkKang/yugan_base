"""
二维码识别引擎 - 后台异步Worker

功能:
  • 启动后台线程池，异步处理图像识别
  • 二维码区域检测与裁剪 (形态学+轮廓) → 提高识别率
  • 多策略尝试: WeChatQRCode → pyzbar
  • 多尺度解码: 1.0x / 1.5x / 0.7x
  • 图像质量评分 (Laplacian方差)
  • 识别后自动判定库存并写入 inventory_items
  • 兜底扫描: 每30s检查是否有卡住的 pending 图像
"""
import os
import cv2
import threading
import time
import queue
import logging
import numpy as np
from datetime import datetime
from typing import Optional, Tuple, List

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

from ..db.database import SessionLocal
from ..models.models import (
    ImageRecord, Waypoint, Task, InventoryItem,
    ImageStatus, InventoryStatus
)

logger = logging.getLogger(__name__)

# 存储根目录（与 gateway.py / videos.py 一致，可通过环境变量覆盖）
STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "storage")

# 全局单例
_engine_instance = None
_engine_lock = threading.Lock()


class QRCropResult:
    """二维码裁剪结果"""
    def __init__(self, cropped_img: np.ndarray, bbox: tuple, confidence: float):
        self.cropped_img = cropped_img  # 裁剪出的二维码区域
        self.bbox = bbox    # (x, y, w, h)
        self.confidence = confidence


class QRRecognitionEngine:
    """二维码异步识别引擎（单例）"""

    def __init__(self, max_workers: int = 2):
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=500)
        self._wechat = None
        self._init_lock = threading.Lock()
        self._running = True
        self._threads: List[threading.Thread] = []

        # 启动 worker 线程
        for i in range(max_workers):
            t = threading.Thread(
                target=self._worker, name=f"qr-worker-{i}", daemon=True
            )
            t.start()
            self._threads.append(t)

        # 启动兜底扫描线程
        t = threading.Thread(
            target=self._rescue_worker, name="qr-rescue", daemon=True
        )
        t.start()
        self._threads.append(t)

        logger.info(f"[QR引擎] 启动完成 (workers={max_workers}, pyzbar={HAS_PYZBAR})")

    # ── 懒初始化 WeChatQRCode ──────────────────────────
    def _get_wechat(self):
        if self._wechat is None:
            with self._init_lock:
                if self._wechat is None:
                    try:
                        self._wechat = cv2.wechat_qrcode_WeChatQRCode()
                        logger.info("[QR引擎] WeChatQRCode 模型已加载")
                    except Exception as e:
                        logger.warning(f"[QR引擎] WeChatQRCode 不可用: {e}，将仅使用 pyzbar")
                        self._wechat = "disabled"
        return self._wechat if self._wechat != "disabled" else None

    # ── 提交识别任务 ──────────────────────────────────
    def submit(self, image_id: str, file_path: str, expected_sku: Optional[str] = None):
        """提交一个识别任务到队列"""
        try:
            self._queue.put({
                "image_id": image_id,
                "file_path": file_path,
                "expected_sku": expected_sku,
                "submitted_at": time.time(),
            }, block=False)
        except queue.Full:
            logger.warning(f"[QR引擎] 队列已满，图像 {image_id} 将被兜底扫描处理")

    # ── Worker 主循环 ─────────────────────────────────
    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=5)
            except queue.Empty:
                continue
            try:
                self._process_one(item)
            except Exception as e:
                logger.error(f"[QR引擎] 处理异常 ({item.get('image_id')}): {e}", exc_info=True)
                self._mark_failed(item["image_id"], str(e))
            finally:
                self._queue.task_done()

    # ── 兜底Worker: 每30秒扫描卡住的pending图像 ────────
    def _rescue_worker(self):
        while self._running:
            time.sleep(30)
            try:
                db = SessionLocal()
                try:
                    threshold = datetime.utcnow().timestamp() - 60
                    rows = (
                        db.query(ImageRecord)
                        .filter(ImageRecord.status == "pending")
                        .filter(
                            (ImageRecord.queued_at.is_(None))
                            | (ImageRecord.queued_at < datetime.fromtimestamp(threshold))
                        )
                        .limit(50)
                        .all()
                    )
                    for img in rows:
                        if img.file_path and os.path.exists(img.file_path):
                            self.submit(img.id, img.file_path, img.expected_sku)
                            img.queued_at = datetime.utcnow()
                    if rows:
                        db.commit()
                        logger.info(f"[QR引擎] 兜底扫描: 重新入队 {len(rows)} 张图像")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"[QR引擎] 兜底扫描异常: {e}")

    # ── 处理单张图像 ──────────────────────────────────
    def _process_one(self, item: dict):
        image_id = item["image_id"]
        file_path = item["file_path"]
        expected_sku = item.get("expected_sku")

        if not file_path or not os.path.exists(file_path):
            self._mark_failed(image_id, "源文件不存在")
            return

        db = SessionLocal()
        try:
            record = db.query(ImageRecord).filter(ImageRecord.id == image_id).with_for_update().first()
            if not record:
                return
            if record.status in ("processed", "failed"):
                return
            record.status = "processing"
            record.processing_started_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()

        # 1) 读取图像
        img = cv2.imread(file_path)
        if img is None:
            self._mark_failed(image_id, "无法读取图像文件（可能已损坏）")
            return

        # 2) 质量评分
        quality = self._score_quality(img)

        # 3) 二维码区域检测与裁剪 → 多区域逐个尝试
        qr_text, confidence, decoder = None, 0.0, None
        # 保留命中区域（用于 QR 双图保存：裁剪图 + 标注图）
        hit_crop = None  # 命中的裁剪图（ndarray）
        hit_bbox = None  # 命中的 bbox (x, y, w, h)
        crop_regions = self._detect_qr_regions(img)

        # 全图也尝试
        all_regions = list(crop_regions)
        all_regions.append((img, (0, 0, img.shape[1], img.shape[0]), 0.5))  # 全图

        for crop_img, bbox, crop_conf in all_regions:
            # 多尺度 + 多解码器
            text, conf, dec = self._try_decode(crop_img)
            if text:
                if confidence == 0.0 or conf > confidence:
                    qr_text, confidence, decoder = text, conf, dec
                    hit_crop = crop_img
                    hit_bbox = bbox
                # 如果置信度足够高就停止搜索
                if conf > 0.8:
                    break

        # 4) 若仍未识别到且质量较差，预处理增强后重试
        if not qr_text and quality < 200.0:
            for crop_img, bbox, crop_conf in all_regions[:3]:  # 只重试前3个区域
                enhanced = self._preprocess(crop_img)
                text2, conf2, dec2 = self._try_decode(enhanced)
                if text2:
                    qr_text = text2
                    confidence = conf2
                    decoder = (dec2 or "") + "+enhanced"
                    hit_crop = crop_img  # 保留命中的裁剪图（增强前的原图）
                    hit_bbox = bbox
                    break

        # 5) 写入结果 + 库存判定
        db = SessionLocal()
        try:
            record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
            if not record:
                return

            record.status = "processed"
            record.processed_at = datetime.utcnow()
            record.qr_data = qr_text
            record.confidence = confidence
            record.image_quality_score = quality
            record.decoder_used = decoder or "none"

            inventory_status = "missing"
            inventory_message = "未识别到二维码"
            if qr_text:
                inventory_status, inventory_message = self._classify_inventory(
                    qr_text, expected_sku, record.task_id, record.waypoint_id, db
                )
                # 写入 inventory_items (normal / misplaced / extra / duplicate)
                if inventory_status in ("normal", "misplaced", "extra", "duplicate"):
                    self._insert_inventory_item(record, qr_text, inventory_status, inventory_message, confidence, db)

            record.inventory_status = inventory_status
            record.inventory_message = inventory_message

            # ── QR 双图证据保存（仅在 QR 命中时） ──
            # 裁剪图: 裁剪出的 QR 区域小图 → ImageRecord.qr_cropped_path
            # 标注图: 带 QR 框选标注的原图 → ImageRecord.annotated_path
            if qr_text and hit_crop is not None and hit_bbox is not None:
                crop_path, annot_path = self._save_qr_evidence_images(
                    img, hit_crop, hit_bbox, qr_text, record
                )
                if crop_path:
                    record.qr_cropped_path = crop_path
                if annot_path:
                    record.annotated_path = annot_path

            db.commit()
            self._update_task_counts(record.task_id, db)
            logger.info(
                f"[QR引擎] {image_id} → SKU={qr_text or 'N/A'} "
                f"decoder={decoder} quality={quality:.1f} inventory={inventory_status}"
            )
        except Exception as e:
            db.rollback()
            logger.error(f"[QR引擎] 写入结果失败: {image_id}: {e}", exc_info=True)
            self._mark_failed(image_id, f"数据库写入失败: {e}")
        finally:
            db.close()

    # ── QR码区域检测: 形态学+轮廓 ──────────────────────
    def _detect_qr_regions(self, img: np.ndarray) -> List[tuple]:
        """
        使用形态学操作 + 轮廓检测定位图像中可能的二维码区域。
        返回: [(裁剪图, bbox(x,y,w,h), confidence), ...]
        """
        regions = []
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            h, w = gray.shape

            # 方法1: 梯度法 - 检测边缘密集的矩形区域
            grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            gradient = cv2.magnitude(grad_x, grad_y)
            gradient = np.uint8(np.clip(gradient, 0, 255))

            # 二值化并做形态学闭运算让QR区域连成块
            _, binary = cv2.threshold(gradient, 30, 255, cv2.THRESH_BINARY)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
            closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=3)

            # 找轮廓
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            candidates = []
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 500 or area > w * h * 0.8:
                    continue
                x, y, bw, bh = cv2.boundingRect(cnt)
                aspect = bw / (bh + 1e-6)
                # QR码通常是正方形，宽高比 0.5~2.0
                if 0.3 < aspect < 3.0 and bw > 40 and bh > 40:
                    # 评分: 越大越好，越接近正方形越好
                    score = area * (1.0 - abs(aspect - 1.0) / 2.0)
                    candidates.append((score, (x, y, bw, bh)))

            # 保留最高得分的3个区域
            candidates.sort(key=lambda c: c[0], reverse=True)
            for score, (x, y, bw, bh) in candidates[:3]:
                # 扩大10%边界
                expand = 0.1
                nx = max(0, int(x - bw * expand))
                ny = max(0, int(y - bh * expand))
                nw = min(w - nx, int(bw * (1 + 2*expand)))
                nh = min(h - ny, int(bh * (1 + 2*expand)))
                if nw > 0 and nh > 0:
                    crop = img[ny:ny+nh, nx:nx+nw]
                    regions.append((crop, (nx, ny, nw, nh), score / 100000.0))

        except Exception as e:
            logger.debug(f"[QR引擎] 区域检测异常: {e}")

        return regions

    # ── 图像质量评分 ──────────────────────────────────
    def _score_quality(self, img: np.ndarray) -> float:
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            return float(lap_var)
        except Exception:
            return 0.0

    # ── 多尺度 + 多解码器 ─────────────────────────────
    def _try_decode(self, img: np.ndarray) -> Tuple[Optional[str], float, Optional[str]]:
        scales = [1.0, 1.5, 0.7, 2.0]
        for scale in scales:
            if scale != 1.0:
                h, w = img.shape[:2]
                resized = cv2.resize(img, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_CUBIC)
            else:
                resized = img

            # 1) WeChatQRCode (主)
            wechat = self._get_wechat()
            if wechat is not None:
                try:
                    texts, _, _, _ = wechat.detectAndDecode(resized)
                    for t in texts:
                        if isinstance(t, str) and t.strip():
                            return t.strip(), 0.95, "wechat_qrcode"
                        if isinstance(t, bytes):
                            s = t.decode("utf-8", errors="ignore").strip()
                            if s:
                                return s, 0.95, "wechat_qrcode"
                except Exception:
                    pass

            # 2) pyzbar (备用)
            if HAS_PYZBAR:
                try:
                    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(resized.shape) == 3 else resized
                    results = pyzbar_decode(gray)
                    if results:
                        data = results[0].data.decode("utf-8", errors="ignore").strip()
                        if data:
                            q = float(getattr(results[0], 'quality', 50))
                            return data, q / 100.0, "pyzbar"
                except Exception:
                    pass

        return None, 0.0, None

    # ── 图像预处理 (去噪 + 自适应阈值 + 锐化) ─────────
    def _preprocess(self, img: np.ndarray) -> np.ndarray:
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
            # 去噪
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            # 自适应阈值二值化
            thresh = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            # 轻度锐化
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
            sharp = cv2.filter2D(thresh, -1, kernel)
            return cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR)
        except Exception:
            return img

    # ── 库存业务判定 ──────────────────────────────────
    def _classify_inventory(
        self,
        qr_text: str,
        expected_sku: Optional[str],
        task_code: Optional[str],
        waypoint_id: Optional[str],
        db,
    ) -> Tuple[str, str]:
        """判定扫描到的SKU与预期的关系"""
        if not expected_sku:
            # 无预期: 检查是否重复
            if task_code:
                exists = (
                    db.query(ImageRecord)
                    .filter(
                        ImageRecord.task_id == task_code,
                        ImageRecord.qr_data == qr_text,
                        ImageRecord.waypoint_id != waypoint_id,
                    )
                    .first()
                )
                if exists:
                    return "duplicate", f"SKU {qr_text} 已在其他位置存在"
            return "extra", f"无预期SKU，实际扫描到 {qr_text}，标记为多货"

        if qr_text == expected_sku:
            return "normal", "SKU与预期一致，位置正确"

        return "misplaced", f"预期SKU为 {expected_sku}，实际扫描到 {qr_text}"

    # ── 写入 inventory_items ──────────────────────────
    def _insert_inventory_item(
        self,
        record: ImageRecord,
        qr_text: str,
        status: str,
        message: str,
        confidence: float,
        db,
    ):
        item = InventoryItem(
            sku=qr_text,
            expected_sku=record.expected_sku,
            expected_location="",
            task_id=record.task_id,
            waypoint_id=record.waypoint_id,
            image_id=record.id,
            position_x=record.position_x,
            position_y=record.position_y,
            position_z=record.position_z,
            status=status,
            message=message,
            confidence=confidence,
            source_qr_data=qr_text,
        )
        db.add(item)

    # ── 更新任务统计 ──────────────────────────────────
    def _update_task_counts(self, task_code: str, db):
        if not task_code:
            return
        task = db.query(Task).filter(Task.task_code == task_code).first()
        if not task:
            return
        imgs = db.query(ImageRecord).filter(ImageRecord.task_id == task_code).all()
        if imgs:
            task.total_recognized = sum(1 for i in imgs if i.qr_data)
            task.total_failed = sum(1 for i in imgs if i.status == "failed")
            task.pending_count = sum(1 for i in imgs if i.status in ("pending", "processing"))

    # ── QR 双图证据保存 ──────────────────────────────
    def _save_qr_evidence_images(
        self,
        original_img: np.ndarray,
        cropped_img: np.ndarray,
        bbox: tuple,
        qr_text: str,
        record: ImageRecord,
    ) -> tuple:
        """
        保存 QR 双图证据：
          1. 裁剪图: 裁剪出的 QR 区域小图 → qr_cropped_path
          2. 标注图: 带 QR 框选标注的原图 → annotated_path

        存储路径:
          storage/qr_crops/{task_code}/{waypoint_id}/crop_{image_id}_{ts}.jpg
          storage/qr_crops/{task_code}/{waypoint_id}/annotated_{image_id}_{ts}.jpg

        Args:
            original_img: 原图（用于生成标注图）
            cropped_img: 命中的 QR 区域裁剪图
            bbox: (x, y, w, h) 框选位置
            qr_text: QR 解码内容
            record: ImageRecord 实例

        Returns:
            (crop_path, annot_path) — 失败时对应位置为 None
        """
        from .annotator import save_qr_dual_images

        # 路径: storage/qr_crops/{task_code}/{waypoint_id}/
        task_dir = record.task_id or "no_task"
        wp_dir = record.waypoint_id or "no_wp"
        crop_dir = os.path.join(STORAGE_ROOT, "qr_crops", task_dir, wp_dir)
        try:
            os.makedirs(crop_dir, exist_ok=True)
        except Exception as e:
            logger.error("[QR引擎] 创建 QR 证据目录失败: %s | 错误: %s", crop_dir, e)
            return None, None

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        crop_path = os.path.join(crop_dir, f"crop_{record.id}_{ts}.jpg")
        annot_path = os.path.join(crop_dir, f"annotated_{record.id}_{ts}.jpg")

        crop_ok, annot_ok = save_qr_dual_images(
            original_img, cropped_img, bbox, qr_text, crop_path, annot_path
        )

        if crop_ok:
            logger.debug("[QR引擎] QR 裁剪图已保存: %s", crop_path)
        if annot_ok:
            logger.debug("[QR引擎] QR 标注图已保存: %s", annot_path)

        return (crop_path if crop_ok else None,
                annot_path if annot_ok else None)

    # ── 标记失败 ──────────────────────────────────────
    def _mark_failed(self, image_id: str, error: str):
        db = SessionLocal()
        try:
            record = db.query(ImageRecord).filter(ImageRecord.id == image_id).first()
            if record and record.status not in ("processed", "failed"):
                record.status = "failed"
                record.error_message = error
                record.processed_at = datetime.utcnow()
                db.commit()
                logger.warning(f"[QR引擎] 识别失败: {image_id}: {error}")
        finally:
            db.close()


def get_recognition_engine() -> QRRecognitionEngine:
    """获取全局单例引擎"""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = QRRecognitionEngine(max_workers=2)
    return _engine_instance