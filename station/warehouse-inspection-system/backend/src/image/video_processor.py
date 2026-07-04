"""
视频抽帧 + 场景分组 + 拼接 + QR识别处理器

数据流:
  视频文件 → 按固定间隔抽帧 → 场景相似度分组(直方图相关性)
  → 每组水平拼接为长图 → 对每张长图做QR识别 → 汇总QR码列表

设计依据 (用户需求 Q17):
  "全抽，但是可以先筛选出可以拼接到一起的图片为一整组视频帧，
   这样的话所有筛选出来的照片就相当于一张长图片，再对每一张进行扫描，
   这样是否可以适当减少性能开销"
"""
import os
import cv2
import logging
import numpy as np
from datetime import datetime
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

# 默认参数
FRAME_INTERVAL_SEC = 1.0          # 抽帧间隔(秒)
HIST_CORRELATION_THRESHOLD = 0.70 # 同组相似度阈值(直方图相关性)
MAX_FRAMES_PER_GROUP = 8          # 单组最大帧数(避免长图过长)
MAX_TOTAL_FRAMES = 200            # 单视频最大抽帧数(保护)


def extract_frames(video_path: str, interval_sec: float = FRAME_INTERVAL_SEC) -> List[np.ndarray]:
    """从视频中按固定时间间隔抽帧。

    Args:
        video_path: 视频文件路径
        interval_sec: 抽帧间隔(秒)

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
    logger.info("[VideoProcessor] 视频: %s fps=%.2f total=%d step=%d",
                os.path.basename(video_path), fps, total_frames, frame_step)

    frames = []
    idx = 0
    while len(frames) < MAX_TOTAL_FRAMES:
        ret = cap.grab()
        if not ret:
            break
        if idx % frame_step == 0:
            ok, frame = cap.retrieve()
            if ok and frame is not None:
                frames.append(frame)
        idx += 1
    cap.release()
    logger.info("[VideoProcessor] 抽帧完成: %d 帧 (视频=%s)",
                len(frames), os.path.basename(video_path))
    return frames


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


def recognize_qr_on_image(img: np.ndarray) -> List[str]:
    """对单张图像做QR识别，返回识别到的二维码内容列表。"""
    codes: List[str] = []

    # 方法1: WeChatQRCode (准确率高)
    try:
        detector = cv2.wechat_qrcode_WeChatQRCode()
        results, _ = detector.detectAndDecode(img)
        for r in results:
            r = r.strip()
            if r:
                codes.append(r)
        if codes:
            return codes
    except Exception:
        pass

    # 方法2: pyzbar
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        for r in pyzbar_decode(img):
            if r.type == 'QRCODE':
                data = r.data.decode("utf-8", errors="ignore").strip()
                if data:
                    codes.append(data)
    except ImportError:
        logger.warning("[VideoProcessor] pyzbar 未安装，QR识别能力受限")
    except Exception as e:
        logger.debug("[VideoProcessor] pyzbar 异常: %s", e)

    return codes


def process_video(video_path: str) -> Tuple[List[str], int, str]:
    """完整处理一个视频文件: 抽帧 → 分组 → 拼接 → QR识别。

    Returns:
        (qr_codes_list, frame_count, status)
        status: "completed" / "failed" / "empty"
    """
    try:
        frames = extract_frames(video_path)
        if not frames:
            return [], 0, "empty"

        groups = group_frames_by_scene(frames)
        all_codes: List[str] = []
        for gi, group in enumerate(groups):
            pano = stitch_group_horizontal(group)
            if pano is None:
                continue
            codes = recognize_qr_on_image(pano)
            if codes:
                all_codes.extend(codes)
                logger.info("[VideoProcessor] 组 %d 识别到 %d 个QR码: %s",
                            gi, len(codes), codes[:3])

        # 去重保持顺序
        seen = set()
        unique_codes = []
        for c in all_codes:
            if c not in seen:
                seen.add(c)
                unique_codes.append(c)

        logger.info("[VideoProcessor] 视频处理完成: %d 帧, %d 组, %d 个QR码 (视频=%s)",
                    len(frames), len(groups), len(unique_codes),
                    os.path.basename(video_path))
        return unique_codes, len(frames), "completed"

    except Exception as e:
        logger.error("[VideoProcessor] 视频处理失败: %s (视频=%s)",
                     e, os.path.basename(video_path), exc_info=True)
        return [], 0, "failed"
