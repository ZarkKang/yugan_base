"""
Gateway 端到端测试
==================
覆盖数据接收、后台处理、错误处理等核心流程。
使用 SQLite 内存数据库 + FastAPI TestClient。
"""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

# 将 src 加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, get_db
from models.models import Drone, InspectionRecord, InspectionStatus
from main import app


# ── 测试数据库 ──────────────────────────────────

@pytest.fixture(scope="module")
def test_engine():
    """SQLite 内存数据库引擎"""
    engine = create_engine("sqlite:///./test_gateway.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    os.remove("test_gateway.db") if os.path.exists("test_gateway.db") else None


@pytest.fixture
def db_session(test_engine):
    """每个测试独立数据库会话"""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def client(db_session, test_engine):
    """FastAPI TestClient，注入测试数据库"""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def test_drone(db_session):
    """创建测试用无人机"""
    drone = Drone(
        drone_code="GW-TEST-001",
        drone_name="Gateway测试无人机",
        model="DJI-M300",
        status="idle",
        battery_level=85.0,
    )
    db_session.add(drone)
    db_session.commit()
    db_session.refresh(drone)
    return drone


# ── 测试用例 ────────────────────────────────────

class TestGatewayReceive:
    """Gateway 数据接收端点测试"""

    def test_receive_rfid_data(self, client, test_drone):
        """接收 RFID 数据 → 创建 InspectionRecord 并更新无人机位置"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "rfid",
            "payload": '["E20000123456789012345678", "E20000876543210987654321"]',
            "position_x": 1.5,
            "position_y": 2.0,
            "position_z": 3.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "RFID" in data["message"] or "rfid" in data["message"]
        assert data["record_id"] is not None

    def test_receive_qr_code_data(self, client, test_drone):
        """接收二维码数据 → 创建 InspectionRecord"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "qr_code",
            "payload": "SKU-TEST-001|A-01-02",
            "position_x": 2.0,
            "position_y": 3.0,
            "position_z": 4.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["record_id"] is not None

    def test_receive_sbus_data(self, client, test_drone, db_session):
        """接收 SBUS 数据 → 更新无人机位置"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "sbus",
            "payload": '{"channels": [1500, 1500, 1500, 1000, 2000, 1500, 1500, 1500]}',
            "position_x": 10.0,
            "position_y": 20.0,
            "position_z": 5.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # 验证无人机位置已更新
        drone = db_session.query(Drone).filter(Drone.drone_code == "GW-TEST-001").first()
        assert drone.last_position_x == 10.0
        assert drone.last_position_y == 20.0
        assert drone.last_position_z == 5.0
        assert drone.last_seen is not None

    def test_receive_video_data(self, client, test_drone):
        """接收视频帧元数据 → 创建 InspectionRecord"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "video",
            "payload": '{"frame": 1234, "format": "h264"}',
            "position_x": 1.0,
            "position_y": 1.0,
            "position_z": 5.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["record_id"] is not None

    def test_receive_image_data_queued(self, client, test_drone):
        """接收图像数据（Base64）→ 入队列后台处理"""
        # 1x1 白色像素 JPEG 的 Base64
        tiny_jpeg = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYI0RVNmJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwA="
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "image",
            "payload": tiny_jpeg,
            "position_x": 3.0,
            "position_y": 3.0,
            "position_z": 5.0,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "后台" in data["message"] or "图像" in data["message"]

    def test_receive_drone_not_found(self, client):
        """不存在的无人机 → 404"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "NONEXISTENT",
            "data_type": "rfid",
            "payload": '["TAG001"]',
        })
        assert response.status_code == 404

    def test_receive_invalid_data_type(self, client, test_drone):
        """不支持的数据类型 → 400"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "unknown_type",
            "payload": "test",
        })
        assert response.status_code == 400

    def test_receive_updates_drone_last_seen(self, client, test_drone, db_session):
        """每次数据接收后更新无人机 last_seen"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "rfid",
            "payload": '["TAG_TIMESTAMP"]',
            "position_x": 0.0,
            "position_y": 0.0,
            "position_z": 0.0,
        })
        assert response.status_code == 200

        drone = db_session.query(Drone).filter(Drone.drone_code == "GW-TEST-001").first()
        assert drone.last_seen is not None

    def test_receive_rfid_single_tag(self, client, test_drone):
        """单个 RFID 标签（非 JSON 数组）"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "rfid",
            "payload": "E20000555555555555555555",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["record_id"] is not None

    def test_inspection_record_created_with_correct_data(self, client, test_drone, db_session):
        """验证 InspectionRecord 字段正确写入"""
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "rfid",
            "payload": '["TAG_A", "TAG_B", "TAG_C"]',
            "position_x": 11.0,
            "position_y": 22.0,
            "position_z": 33.0,
        })
        assert response.status_code == 200
        record_id = response.json()["record_id"]

        record = db_session.query(InspectionRecord).filter(
            InspectionRecord.id == record_id
        ).first()
        assert record is not None
        assert record.drone_id == test_drone.id
        assert record.status == InspectionStatus.PENDING
        assert record.drone_position_x == 11.0
        assert record.drone_position_y == 22.0
        assert record.drone_position_z == 33.0
        assert "TAG_A" in record.rfid_data
        assert "TAG_C" in record.rfid_data
        assert record.record_code.startswith("RFID_")


# ── 后台处理器测试 ──────────────────────────────

class TestGatewayBackgroundProcessor:
    """后台 Worker 和队列测试"""

    def test_processor_starts_on_image(self, client, test_drone):
        """首次图像上传时自动启动后台处理器"""
        tiny_jpeg = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYI0RVNmJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwA="
        response = client.post("/api/v1/gateway/receive", json={
            "drone_code": "GW-TEST-001",
            "data_type": "image",
            "payload": tiny_jpeg,
        })
        assert response.status_code == 200
        assert response.json()["success"] is True


# ── 二维码处理测试 ──────────────────────────────

class TestGatewayQRCode:
    """二维码识别端点测试"""

    def test_qrcode_no_input(self, client):
        """无输入参数 → 返回错误"""
        response = client.post("/api/v1/gateway/qrcode/process", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False

    def test_qrcode_file_not_found(self, client):
        """文件路径不存在 → 返回错误"""
        response = client.post("/api/v1/gateway/qrcode/process", json={
            "image_path": "/nonexistent/path/image.jpg"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "不存在" in data["message"]


# ── RFID 读取测试 ───────────────────────────────

class TestGatewayRFID:
    """RFID 硬件读取端点测试"""

    def test_rfid_read_drone_not_found(self, client):
        """不存在的无人机 → 404"""
        response = client.post("/api/v1/gateway/rfid/read?drone_code=NONEXISTENT")
        assert response.status_code == 404

    @patch("src.api.gateway.get_rfid_reader")
    def test_rfid_read_not_connected(self, mock_reader, client, test_drone):
        """RFID 读卡器未连接 → 返回 false"""
        mock_reader_instance = MagicMock()
        mock_reader_instance.is_connected.return_value = False
        mock_reader_instance.connect.return_value = False
        mock_reader.return_value = mock_reader_instance

        response = client.post("/api/v1/gateway/rfid/read?drone_code=GW-TEST-001")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "未连接" in data["message"]

    @patch("src.api.gateway.get_rfid_reader")
    def test_rfid_read_no_tags(self, mock_reader, client, test_drone):
        """RFID 读卡器已连接但无标签 → 返回 success=True"""
        mock_reader_instance = MagicMock()
        mock_reader_instance.is_connected.return_value = True
        mock_reader_instance.read_multiple_tags.return_value = []
        mock_reader.return_value = mock_reader_instance

        response = client.post("/api/v1/gateway/rfid/read?drone_code=GW-TEST-001")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "未检测到" in data["message"]

    @patch("src.api.gateway.get_rfid_reader")
    def test_rfid_read_with_tags(self, mock_reader, client, test_drone):
        """RFID 读卡器读取到标签 → 创建 InspectionRecord"""
        from hardware.rfid_reader import RFIDTag as HWTag

        mock_reader_instance = MagicMock()
        mock_reader_instance.is_connected.return_value = True
        mock_reader_instance.read_multiple_tags.return_value = [
            HWTag(tag_id="E20000AAAA", rssi=-45, pc=0, read_time=1234567890),
            HWTag(tag_id="E20000BBBB", rssi=-55, pc=0, read_time=1234567891),
        ]
        mock_reader.return_value = mock_reader_instance

        response = client.post("/api/v1/gateway/rfid/read?drone_code=GW-TEST-001")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["record_id"] is not None
        assert "2" in data["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])