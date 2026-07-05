"""
视频抽帧 + QR识别处理器

数据流 (v2 逐帧识别优先):
  视频文件 → 按固定间隔抽帧
  → 逐帧QR识别(主通道, 每帧独立, 保持原始分辨率)
  → 未识别帧分组拼接后识别(辅助通道, 兜底)
  → 合并去重

核心优化:
  1. 逐帧识别为主 — 避免拼接扭曲QR定位图案
  2. 多检测器合并 — 三种方法结果合并而非短路
  3. 多尺度检测 — 缩放提升小码识别率
  4. 拼接识别降为辅助 — 仅对逐帧未命中的帧组尝试
"""
import os
import time
import cv2
import logging
import numpy as np
from datetime import datetime
from typing import List, Tuple, Optional, Set

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════
#  参数
# ═══════════════════════════════════════════
FRAME_INTERVAL_SEC = 0.5          # 抽帧间隔(秒) — 提高密度减少遗漏
HIST_CORRELATION_THRESHOLD = 0.70 # 同组相似度阈值(直方图相关性)
MAX_FRAMES_PER_GROUP = 8          # 单组最大帧数
MAX_TOTAL_FRAMES = 500            # 单视频最大抽帧数(0.5s间隔需更多配额)
EXTRACT_TIMEOUT_SEC = 120         # 抽帧超时(秒)
PROCESS_TIMEOUT_SEC = 300         # 整体处理超时(秒)

# 多尺度检测缩放因子
MULTISCALE_FACTORS = [1.0, 1.5, 2.0]  # 原图 + 放大1.5x + 放大2x


# ═══════════════════════════════════════════
#  检测器缓存
# ═══════════════════════════════════════════
_qr_detector_multi = None
_qr_detector_wechat = None


def _get_qr_detector_multi() -> cv2.QRCodeDetector:
    """获取 cv2.QRCodeDetector 实例（支持多码群读，单例缓存）。"""
    global _qr_detector_multi
    if _qr_detector_multi is None:
        _qr_detector_multi = cv2.QRCodeDetector()
    return _qr_detector_multi


def _get_qr_detector_wechat():
    """获取 WeChatQRCode 实例（单例缓存，需要模型文件）。"""
    global _qr_detector_wechat
    if _qr_detector_wechat is None:
        try:
            _qr_detector_wechat = cv2.wechat_qrcode_WeChatQRCode()
        except Exception:
            _qr_detector_wechat = False  # 标记不可用
    return _qr_detector_wechat if _qr_detector_wechat is not False else None


# ═══════════════════════════════════════════
#  抽帧
# ═══════════════════════════════════════════
def extract_frames(video_path: str, interval_sec: float = FRAME_INTERVAL_SEC,
                    timeout_sec: float = EXTRACT_TIMEOUT_SEC) -> List[np.ndarray]:
    """从视频中按固定时间间隔抽帧。

    Args:
        video_path: 视频文件路径
        interval_sec: 抽帧间隔(秒)
        timeout_sec: 抽帧超时(秒)，超时后返回已抽到的帧

    Returns:
        抽取到的帧列表(BGR ndarray)
    """
    if not os.path.exists(video_path):
        logger.warning("[VideoProcessor] 视频文件不存在: %s", video_path)
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning("[VideoProcessor] 无法打开视频: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_step = max(1, int(fps * interval_sec))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    logger.info("[VideoProcessor] 视频: %s fps=%.2f total=%d step=%d timeout=%ds",
                os.path.basename(video_path), fps, total_frames, frame_step, timeout_sec)

    frames = []
    idx = 0
    start_time = time.time()
    while len(frames) < MAX_TOTAL_FRAMES:
        ret = cap.grab()
        if not ret:
            break
        if idx % frame_step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                frames.append(frame)
        idx += 1
        # 每100帧检查一次超时
        if idx % 100 == 0:
            elapsed = time.time() - start_time
            if elapsed > timeout_sec:
                logger.warning("[VideoProcessor] 抽帧超时(%.1fs/%ds)，已抽%d帧，视频=%s",
                               elapsed, timeout_sec, len(frames), os.path.basename(video_path))
                break
    cap.release()
    logger.info("[VideoProcessor] 抽帧完成: %d 帧 (耗时%.1fs, 视频=%s)",
                len(frames), time.time() - start_time, os.path.basename(video_path))
    return frames


# ═══════════════════════════════════════════
#  场景分组 + 拼接 (辅助通道使用)
# ═══════════════════════════════════════════
def _hist_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """计算两帧图像的直方图相关性(0~1，越高越相似)。"""
    try:
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
        ha = cv2.calcHist([ga], [0], None, [256], [0, 256])
        hb = cv2.calcHist([gb], [0], None, [256], [0, 256])
        cv2.normalize(ha, ha, 0, 1, cv2.NORM_MINMAX)
        cv2.normalize(hb, hb, 0, 1, cv2.NORM_MINMAX)
        return float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
    except Exception:
        return 0.0


def group_frames_by_scene(frames: List[np.ndarray],
                          threshold: float = HIST_CORRELATION_THRESHOLD) -> List[List[np.ndarray]]:
    """将相似帧分组(可拼接为一组长图)。

    规则: 相邻帧直方图相关性 >= threshold 视为同组；否则开启新组。
    每组最多 MAX_FRAMES_PER_GROUP 帧，超过则切分新组。
    """
    if not frames:
        return []

    groups: List[List[np.ndarray]] = [[frames[0]]]
    for prev, cur in zip(frames[:-1], frames[1:]):
        sim = _hist_correlation(prev, cur)
        last_group = groups[-1]
        if sim >= threshold and len(last_group) < MAX_FRAMES_PER_GROUP:
            last_group.append(cur)
        else:
            groups.append([cur])

    logger.info("[VideoProcessor] 场景分组: %d 帧 → %d 组", len(frames), len(groups))
    return groups


def stitch_group_horizontal(frames: List[np.ndarray]) -> Optional[np.ndarray]:
    """将一组帧水平拼接为一张长图。

    优先用 cv2.Stitcher (有透视校正)；失败则退化到简单水平拼接。
    """
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]

    # 方法1: OpenCV Stitcher (scans 模式适合横向序列)
    try:
        stitcher = cv2.Stitcher_create(cv2.Stitcher_SCANS)
        status, pano = stitcher.stitch(frames)
        if status == cv2.Stitcher_OK and pano is not None:
            return pano
    except Exception as e:
        logger.debug("[VideoProcessor] Stitcher 失败，退化为水平拼接: %s", e)

    # 方法2: 简单水平拼接(统一高度)
    try:
        resized = []
        target_h = min(f.shape[0] for f in frames)
        for f in frames:
            if f.shape[0] != target_h:
                scale = target_h / f.shape[0]
                new_w = int(f.shape[1] * scale)
                f = cv2.resize(f, (new_w, target_h), interpolation=cv2.INTER_AREA)
            resized.append(f)
        return np.hstack(resized)
    except Exception as e:
        logger.warning("[VideoProcessor] 水平拼接失败: %s", e)
        return frames[0]  # 至少返回第一帧


# ═══════════════════════════════════════════
#  QR 识别核心
# ═══════════════════════════════════════════
def _recognize_qr_single_detector(img: np.ndarray, detector_type: str) -> List[str]:
    """用单个检测器识别QR码，返回识别结果列表。"""
    codes: List[str] = []

    if detector_type == "qr_detector_multi":
        try:
            detector = _get_qr_detector_multi()
            decoded_ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
            if decoded_ok and decoded_info is not None:
                for text in decoded_info:
                    text = text.strip() if text else ""
                    if text:
                        codes.append(text)
        except Exception:
            pass

    elif detector_type == "wechat":
        try:
            detector_wechat = _get_qr_detector_wechat()
            if detector_wechat is not None:
                results, _ = detector_wechat.detectAndDecode(img)
                for r in results:
                    r = r.strip() if r else ""
                    if r:
                        codes.append(r)
        except Exception:
            pass

    elif detector_type == "pyzbar":
        try:
            from pyzbar.pyzbar import decode as pyzbar_decode
            for r in pyzbar_decode(img):
                if r.type == 'QRCODE':
                    data = r.data.decode("utf-8", errors="ignore").strip()
                    if data:
                        codes.append(data)
        except ImportError:
            pass
        except Exception:
            pass

    return codes


def recognize_qr_on_image(img: np.ndarray) -> List[str]:
    """对单张图像做QR识别（支持多码群读），返回识别到的二维码内容列表。

    三种检测器结果合并（不再短路），最大化召回率。
    优先级: QRCodeDetector.detectAndDecodeMulti → WeChatQRCode → pyzbar
    """
    all_codes: Set[str] = set()

    # 三种检测器依次执行，结果合并
    for detector_type in ("qr_detector_multi", "wechat", "pyzbar"):
        codes = _recognize_qr_single_detector(img, detector_type)
        all_codes.update(codes)

    if all_codes:
        logger.debug("[VideoProcessor] 单帧识别到 %d 个QR码", len(all_codes))

    return list(all_codes)


def recognize_qr_multiscale(img: np.ndarray) -> List[str]:
    """多尺度QR识别 — 对图像做不同缩放后识别，提升小码识别率。

    对原图 + 放大1.5x + 放大2x 分别识别，合并结果。
    """
    all_codes: Set[str] = set()

    for factor in MULTISCALE_FACTORS:
        if factor == 1.0:
            scaled = img
        else:
            h, w = img.shape[:2]
            new_w, new_h = int(w * factor), int(h * factor)
            # 限制放大后尺寸，避免内存爆炸
            if new_w * new_h > 4096 * 4096:
                continue
            scaled = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        codes = recognize_qr_on_image(scaled)
        all_codes.update(codes)

    return list(all_codes)


# ═══════════════════════════════════════════
#  主处理流程
# ═══════════════════════════════════════════
def process_video(video_path: str, timeout_sec: float = PROCESS_TIMEOUT_SEC) -> Tuple[List[str], int, str]:
    """完整处理一个视频文件: 抽帧 → 逐帧QR识别(主) → 拼接识别(辅) → 合并去重。

    流程:
      1. 按间隔抽帧
      2. 逐帧QR识别（主通道: 每帧独立识别，保持原始分辨率）
      3. 对逐帧未识别到QR的帧，分组拼接后识别（辅助通道: 兜底）
      4. 合并去重

    Args:
        video_path: 视频文件路径
        timeout_sec: 整体处理超时(秒)

    Returns:
        (qr_codes_list, frame_count, status)
        status: "completed" / "failed" / "empty" / "timeout"
    """
    start_time = time.time()
    try:
        # 1. 抽帧
        extract_timeout = timeout_sec * 0.4  # 抽帧占40%时间预算
        frames = extract_frames(video_path, timeout_sec=extract_timeout)
        if not frames:
            return [], 0, "empty"

        if time.time() - start_time > timeout_sec:
            logger.warning("[VideoProcessor] 抽帧阶段超时 (视频=%s)",
                           os.path.basename(video_path))
            return [], len(frames), "timeout"

        # 2. 逐帧QR识别（主通道）
        all_codes: Set[str] = set()
        frames_without_qr: List[np.ndarray] = []  # 记录未识别到QR的帧

        logger.info("[VideoProcessor] 开始逐帧识别: %d 帧", len(frames))
        for i, frame in enumerate(frames):
            # 超时检查
            if time.time() - start_time > timeout_sec * 0.85:
                # 预留15%时间给辅助通道
                logger.warning("[VideoProcessor] 逐帧识别超时，已处理 %d/%d 帧",
                               i, len(frames))
                break

            codes = recognize_qr_multiscale(frame)
            if codes:
                all_codes.update(codes)
            else:
                frames_without_qr.append(frame)

        logger.info("[VideoProcessor] 逐帧识别完成: 识别到 %d 个QR码, %d 帧无QR",
                    len(all_codes), len(frames_without_qr))

        # 3. 辅助通道: 对未识别帧分组拼接后识别（兜底）
        if frames_without_qr and len(all_codes) == 0:
            logger.info("[VideoProcessor] 逐帧无结果，启用拼接辅助通道")
            groups = group_frames_by_scene(frames_without_qr)
            for gi, group in enumerate(groups):
                if time.time() - start_time > timeout_sec:
                    break
                pano = stitch_group_horizontal(group)
                if pano is None:
                    continue
                codes = recognize_qr_on_image(pano)
                all_codes.update(codes)
                if codes:
                    logger.info("[VideoProcessor] 辅助通道组 %d 识别到 %d 个QR码",
                                gi, len(codes))

        # 4. 去重保持顺序
        seen = set()
        unique_codes = []
        for c in sorted(all_codes):  # 排序保证稳定顺序
            if c not in seen:
                seen.add(c)
                unique_codes.append(c)

        elapsed = time.time() - start_time
        final_status = "timeout" if elapsed > timeout_sec else "completed"
        logger.info("[VideoProcessor] 视频处理完成: %d 帧, %d 个QR码, 耗时%.1fs (视频=%s, status=%s)",
                    len(frames), len(unique_codes),
                    elapsed, os.path.basename(video_path), final_status)
        return unique_codes, len(frames), final_status

    except Exception as e:
        logger.error("[VideoProcessor] 视频处理失败: %s (视频=%s)",
                     e, os.path.basename(video_path), exc_info=True)
        return [], 0, "failed"
