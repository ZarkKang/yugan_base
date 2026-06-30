import cv2
import numpy as np
from typing import Optional, Tuple
from PIL import Image
import io
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# 尝试导入 pyzbar，如果失败则记录警告（需要安装 libzbar0 系统库）
try:
    from pyzbar import pyzbar
    _ZBAR_AVAILABLE = True
except ImportError:
    _ZBAR_AVAILABLE = False
    logger.warning(
        "pyzbar 无法加载 - 缺少 libzbar0 系统库。二维码识别功能将不可用。\n"
        "  - Linux/Debian: sudo apt-get install libzbar0\n"
        "  - macOS: brew install zbar\n"
        "  - Windows: 下载 zbar DLL 并放到系统 PATH 中\n"
        "    https://github.com/NaturalHistoryMuseum/pyzbar#windows"
    )


class QRCodeService:
    """二维码识别服务"""
    
    @staticmethod
    def detect_qr_codes(image_data: bytes) -> list:
        """检测图像中的所有二维码并返回位置和内容"""
        if not _ZBAR_AVAILABLE:
            logger.error("二维码识别不可用: 未安装 libzbar0 系统库")
            return []
        
        # 转换图像
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 使用pyzbar检测
        barcodes = pyzbar.decode(img)
        
        results = []
        for barcode in barcodes:
            if barcode.type == 'QRCODE':
                # 提取位置
                (x, y, w, h) = barcode.rect
                
                # 解码内容
                qr_data = barcode.data.decode("utf-8")
                
                results.append({
                    'data': qr_data,
                    'type': barcode.type,
                    'rect': {'x': x, 'y': y, 'width': w, 'height': h},
                    'polygon': [(p.x, p.y) for p in barcode.polygon]
                })
        
        return results
    
    @staticmethod
    def crop_qr_region(image_data: bytes, qr_rect: dict) -> bytes:
        """根据二维码区域裁切"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        x = qr_rect['x']
        y = qr_rect['y']
        w = qr_rect['width']
        h = qr_rect['height']
        
        # 添加一些边距
        padding = 20
        x = max(0, x - padding)
        y = max(0, y - padding)
        w = min(img.shape[1] - x, w + padding * 2)
        h = min(img.shape[0] - y, h + padding * 2)
        
        # 裁切
        cropped = img[y:y+h, x:x+w]
        
        # 编码回PNG
        _, buffer = cv2.imencode('.png', cropped)
        return buffer.tobytes()
    
    @staticmethod
    def enhance_qr_image(image_data: bytes) -> bytes:
        """增强二维码图像以提高识别率"""
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 灰度化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 自适应阈值二值化
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )
        
        # 形态学操作去噪
        kernel = np.ones((2, 2), np.uint8)
        processed = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        
        _, buffer = cv2.imencode('.png', processed)
        return buffer.tobytes()
    
    @staticmethod
    def process_image_for_database(image_data: bytes, image_id: int = None) -> dict:
        """处理图像并返回可存储到数据库的结果"""
        result = {
            'processed_at': datetime.now().isoformat(),
            'qr_codes': [],
            'has_qr': False,
            'cropped_images': []
        }
        
        # 检测二维码
        qr_codes = QRCodeService.detect_qr_codes(image_data)
        
        if qr_codes:
            result['has_qr'] = True
            
            for i, qr in enumerate(qr_codes):
                # 裁切每个二维码区域
                cropped = QRCodeService.crop_qr_region(image_data, qr['rect'])
                
                result['qr_codes'].append({
                    'index': i,
                    'data': qr['data'],
                    'rect': qr['rect'],
                    'polygon': qr['polygon']
                })
                
                result['cropped_images'].append({
                    'index': i,
                    'data': cropped
                })
        
        return result
