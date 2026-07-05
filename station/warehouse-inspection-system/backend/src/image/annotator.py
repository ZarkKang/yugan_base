"""
QR 框选标注模块
================
在原图上绘制 QR 码框选矩形 + 标签，用于生成证据图。

设计目的：
当 QR 识别命中后，生成两张证据图保存到 ImageRecord：
  1. 裁剪出的 QR 区域小图 → ImageRecord.qr_cropped_path
  2. 带 QR 框选标注的原图 → ImageRecord.annotated_path

复用 image.crop.save_image 进行持久化。
"""
import cv2
import numpy as np
from typing import Tuple, Optional
import logging

from .crop import save_image

logger = logging.getLogger(__name__)


def draw_qr_bbox(
    img: np.ndarray,
    bbox: Tuple[int, int, int, int],
    label: str = "",
    color: Tuple[int, int, int] = (0, 255, 0),
    thickness: int = 2,
    font_scale: float = 0.6,
) -> np.ndarray:
    """
    在原图上绘制 QR 框选矩形 + 标签（不修改原图）。

    Args:
        img: 原图（BGR ndarray）
        bbox: (x, y, w, h) 框选区域
        label: 标签文本（一般为 QR 解码内容）
        color: 框线颜色（BGR），默认绿色
        thickness: 框线粗细
        font_scale: 标签字体大小

    Returns:
        标注后的图像副本（原图不变）
    """
    if img is None or bbox is None:
        return img

    out = img.copy()
    x, y, w, h = bbox

    # 绘制矩形框
    cv2.rectangle(out, (x, y), (x + w, y + h), color, thickness)

    # 绘制标签（位于框上方）
    if label:
        label_y = max(0, y - 8)  # 防止越界
        # 文本背景（便于在复杂背景下阅读）
        (text_w, text_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1
        )
        cv2.rectangle(
            out,
            (x, max(0, label_y - text_h - baseline - 2)),
            (x + text_w + 4, label_y + 2),
            color,
            -1,  # 填充
        )
        # 文字（黑色，便于在彩色背景上阅读）
        cv2.putText(
            out, label, (x + 2, label_y),
            cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1, cv2.LINE_AA,
        )

    return out


def save_annotated(
    image: np.ndarray,
    path: str,
    format: Optional[str] = "jpg",
) -> bool:
    """
    保存带标注的图像（委托给 image.crop.save_image）。

    Args:
        image: 标注后的图像
        path: 保存路径
        format: 图片格式（如 'jpg', 'png'）

    Returns:
        是否保存成功
    """
    return save_image(image, path, format)


def save_qr_dual_images(
    original_img: np.ndarray,
    cropped_img: np.ndarray,
    bbox: Tuple[int, int, int, int],
    qr_text: str,
    crop_path: str,
    annotated_path: str,
) -> Tuple[bool, bool]:
    """
    一次性保存 QR 双图证据。

    Args:
        original_img: 原图（用于生成标注图）
        cropped_img: 裁剪出的 QR 区域小图
        bbox: (x, y, w, h) 框选位置（用于在原图上绘制矩形）
        qr_text: QR 解码内容（用作标签）
        crop_path: 裁剪图保存路径
        annotated_path: 标注图保存路径

    Returns:
        (crop_saved, annotated_saved) 两个布尔值分别表示是否保存成功
    """
    crop_ok = False
    annot_ok = False

    # 1. 保存裁剪图
    try:
        crop_ok = save_image(cropped_img, crop_path, format="jpg")
        if not crop_ok:
            logger.warning("[Annotator] 裁剪图保存失败: %s", crop_path)
    except Exception as e:
        logger.error("[Annotator] 裁剪图保存异常: %s | 错误: %s", crop_path, e)

    # 2. 生成并保存标注图
    try:
        annotated = draw_qr_bbox(original_img, bbox, label=qr_text)
        annot_ok = save_annotated(annotated, annotated_path, format="jpg")
        if not annot_ok:
            logger.warning("[Annotator] 标注图保存失败: %s", annotated_path)
    except Exception as e:
        logger.error("[Annotator] 标注图保存异常: %s | 错误: %s", annotated_path, e)

    return crop_ok, annot_ok
