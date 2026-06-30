"""
图像处理模块 - 二维码识别
"""
import cv2
import numpy as np
from pyzbar.pyzbar import decode as pyzbar_decode
from typing import List, Optional, Tuple, Union
from PIL import Image
import logging

logger = logging.getLogger(__name__)


class QRCodeDecoder:
    """二维码解码器"""

    def __init__(self):
        self._last_result: Optional[List[str]] = None

    def decode_image(self, image_path: str) -> List[str]:
        """
        解码图片中的二维码

        Args:
            image_path: 图片路径

        Returns:
            解码出的二维码数据列表
        """
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"无法读取图片: {image_path}")
            return []
        return self.decode_frame(img)

    def decode_frame(self, frame: np.ndarray) -> List[str]:
        """
        解码视频帧中的二维码

        Args:
            frame: OpenCV图像数组 (BGR格式)

        Returns:
            解码出的二维码数据列表
        """
        barcodes = pyzbar_decode(frame)
        results = []
        for barcode in barcodes:
            try:
                data = barcode.data.decode("utf-8")
                results.append(data)
                logger.debug(f"解码二维码: {data}")
            except UnicodeDecodeError:
                logger.warning(f"二维码无法UTF-8解码: {barcode.data}")
        self._last_result = results
        return results

    def decode_bytes(self, image_bytes: bytes) -> List[str]:
        """
        解码字节数据中的二维码

        Args:
            image_bytes: 图片字节数据

        Returns:
            解码出的二维码数据列表
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            logger.error("无法解码图像字节")
            return []
        return self.decode_frame(img)

    def detect_and_decode(self, frame: np.ndarray) -> List[Tuple[List[Tuple]], List[str]]:
        """
        检测并解码二维码，返回位置和内容

        Args:
            frame: OpenCV图像数组

        Returns:
            [(二维码位置点列表, 解码数据), ...]
        """
        barcodes = pyzbar_decode(frame)
        results = []
        for barcode in barcodes:
            points = [(pt.x, pt.y) for pt in barcode.polygon]
            try:
                data = barcode.data.decode("utf-8")
                results.append((points, data))
            except UnicodeDecodeError:
                logger.warning(f"二维码无法UTF-8解码: {barcode.data}")
        return results

    @property
    def last_result(self) -> Optional[List[str]]:
        return self._last_result


class QRCodeDetector:
    """二维码检测器（不解码）"""

    def detect(self, frame: np.ndarray) -> List[Tuple[List[Tuple[int, int]], str]]:
        """
        检测二维码位置

        Args:
            frame: OpenCV图像数组

        Returns:
            [(角点列表, 类型), ...]
        """
        barcodes = pyzbar_decode(frame)
        results = []
        for barcode in barcodes:
            points = [(pt.x, pt.y) for pt in barcode.polygon]
            results.append((points, barcode.type))
        return results


def preprocess_image(image: Union[str, np.ndarray],
                     grayscale: bool = True,
                     denoise: bool = True,
                     contrast: float = 1.0) -> np.ndarray:
    """
    图像预处理

    Args:
        image: 图片路径或OpenCV图像
        grayscale: 是否转为灰度图
        denoise: 是否去噪
        contrast: 对比度增益

    Returns:
        处理后的图像
    """
    if isinstance(image, str):
        img = cv2.imread(image)
    else:
        img = image.copy()

    if img is None:
        raise ValueError("无法读取图像")

    if grayscale:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    if denoise:
        img = cv2.fastNlMeansDenoisingColored(img, None, 10, 10, 7, 21)

    if contrast != 1.0:
        img = np.clip(img * contrast, 0, 255).astype(np.uint8)

    return img
