"""
图像处理模块 - 图像裁剪
"""
import cv2
import numpy as np
from typing import Tuple, Optional, List
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class ImageCropper:
    """图像裁剪工具"""

    @staticmethod
    def crop(image: np.ndarray,
             x: int, y: int,
             width: int, height: int) -> Optional[np.ndarray]:
        """
        裁剪图像

        Args:
            image: 原始图像
            x, y: 裁剪区域左上角坐标
            width, height: 裁剪区域宽高

        Returns:
            裁剪后的图像
        """
        h, w = image.shape[:2]
        if x < 0 or y < 0 or x + width > w or y + height > h:
            logger.warning(f"裁剪区域超出图像范围: ({x},{y},{width},{height}) vs 图像({w},{h})")
            return None
        return image[y:y+height, x:x+width]

    @staticmethod
    def crop_center(image: np.ndarray,
                    crop_width: int, crop_height: int) -> Optional[np.ndarray]:
        """
        从图像中心裁剪

        Args:
            image: 原始图像
            crop_width, crop_height: 裁剪宽高

        Returns:
            裁剪后的图像
        """
        h, w = image.shape[:2]
        x = (w - crop_width) // 2
        y = (h - crop_height) // 2
        return ImageCropper.crop(image, x, y, crop_width, crop_height)

    @staticmethod
    def crop_polygon(image: np.ndarray,
                     points: List[Tuple[int, int]]) -> Optional[np.ndarray]:
        """
        按多边形区域裁剪

        Args:
            image: 原始图像
            points: 多边形顶点列表 [(x,y), ...]

        Returns:
            裁剪后的图像
        """
        if len(points) < 3:
            return None

        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        pts = np.array(points, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)

        result = cv2.bitwise_and(image, image, mask=mask)

        x, y, w, h = cv2.boundingRect(pts)
        return result[y:y+h, x:x+w]


class ImageResizer:
    """图像缩放工具"""

    @staticmethod
    def resize(image: np.ndarray,
               width: Optional[int] = None,
               height: Optional[int] = None,
               keep_aspect: bool = True) -> np.ndarray:
        """
        调整图像大小

        Args:
            image: 原始图像
            width, height: 目标尺寸（至少提供一个）
            keep_aspect: 是否保持宽高比

        Returns:
            调整后的图像
        """
        h, w = image.shape[:2]

        if width is None and height is None:
            return image

        if keep_aspect:
            if width is not None:
                ratio = width / w
                height = int(h * ratio)
            else:
                ratio = height / h
                width = int(w * ratio)

        return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def resize_to_fit(image: np.ndarray,
                      max_width: int,
                      max_height: int) -> np.ndarray:
        """
        将图像缩放到适应指定尺寸

        Args:
            image: 原始图像
            max_width, max_height: 最大宽高

        Returns:
            缩放后的图像
        """
        h, w = image.shape[:2]
        ratio = min(max_width / w, max_height / h)
        if ratio >= 1:
            return image
        new_w, new_h = int(w * ratio), int(h * ratio)
        return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


class ImageRotator:
    """图像旋转工具"""

    @staticmethod
    def rotate(image: np.ndarray,
              angle: float,
              center: Optional[Tuple[int, int]] = None) -> np.ndarray:
        """
        旋转图像

        Args:
            image: 原始图像
            angle: 旋转角度（度）
            center: 旋转中心，默认为图像中心

        Returns:
            旋转后的图像
        """
        h, w = image.shape[:2]
        if center is None:
            center = (w // 2, h // 2)

        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, matrix, (w, h))

    @staticmethod
    def rotate_bound(image: np.ndarray,
                    angle: float) -> np.ndarray:
        """
        旋转图像并调整边界（不裁剪）

        Args:
            image: 原始图像
            angle: 旋转角度（度）

        Returns:
            旋转后的图像
        """
        h, w = image.shape[:2]
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        cos = np.abs(matrix[0, 0])
        sin = np.abs(matrix[0, 1])
        new_w = int((h * sin) + (w * cos))
        new_h = int((h * cos) + (w * sin))
        matrix[0, 2] += (new_w / 2) - center[0]
        matrix[1, 2] += (new_h / 2) - center[1]
        return cv2.warpAffine(image, matrix, (new_w, new_h))


def save_image(image: np.ndarray,
               path: str,
               format: Optional[str] = None) -> bool:
    """
    保存图像

    Args:
        image: 图像数组
        path: 保存路径
        format: 图片格式（如 'jpg', 'png'）

    Returns:
        是否成功
    """
    try:
        if format:
            pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            pil_img.save(path, format=format.upper())
        else:
            cv2.imwrite(path, image)
        return True
    except Exception as e:
        logger.error(f"保存图像失败: {e}")
        return False
