"""
RFID入库服务单元测试
使用 pytest + unittest.mock，mock RFID驱动和数据库
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone

# 将 src 加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.inbound_service import InboundService
from hardware.rfid_reader import RFIDTag as HWTag


def make_tag(epc: str, rssi: int = -50) -> HWTag:
    return HWTag(tag_id=epc, rssi=rssi, pc=49152, read_time=datetime.now(timezone.utc).timestamp())


class TestInboundService:
    """入库服务单元测试"""

    @pytest.fixture
    def mock_db_session(self):
        """mock 数据库 session"""
        session = MagicMock()
        return session

    @pytest.fixture
    def mock_reader(self):
        """mock RFID读卡器"""
        reader = MagicMock()
        reader.is_connected.return_value = True
        reader.connect.return_value = True
        reader.on_tag_detected = None
        return reader

    @pytest.fixture
    def service(self, mock_reader, monkeypatch):
        """创建 InboundService 实例，注入 mock reader"""
        monkeypatch.setattr(
            "services.inbound_service.get_rfid_reader",
            lambda: mock_reader
        )
        # 确保每次测试获取新实例
        import services.inbound_service as mod
        mod._inbound_service = None
        return mod.get_inbound_service()

    def test_start_sets_running_and_registers_callback(self, service, mock_reader):
        """start 应设为 running 状态并注册 on_tag_detected 回调"""
        result = service.start()
        assert result["success"] is True
        assert service._running is True
        assert mock_reader.on_tag_detected is not None
        mock_reader.start_continuous_scan.assert_called_once()

    def test_start_when_already_running(self, service):
        """重复 start 应返回失败"""
        service._running = True
        result = service.start()
        assert result["success"] is False
        assert "已在运行" in result["message"]

    def test_stop_cleans_up(self, service, mock_reader):
        """stop 应停止扫描并重置状态"""
        service._running = True
        result = service.stop()
        assert result["success"] is True
        assert service._running is False
        mock_reader.stop_continuous_scan.assert_called_once()

    def test_stop_when_not_running(self, service):
        """未运行时 stop 应返回失败"""
        result = service.stop()
        assert result["success"] is False

    def test_status_returns_correct_state(self, service):
        """status 应返回准确的状态信息"""
        service._running = True
        service._tags_scanned = 42
        service._records_created = 10
        service._errors = 3

        result = service.status()
        data = result["data"]
        assert data["running"] is True
        assert data["tags_scanned"] == 42
        assert data["records_created"] == 10
        assert data["errors"] == 3

    def test_process_tag_registered_rfid(self, service, mock_db_session):
        """已注册 EPC: 应创建 Inventory + InboundRecord(success)"""
        # Mock RFIDTag 查询
        mock_rfid_tag = MagicMock()
        mock_rfid_tag.id = 1
        mock_rfid_tag.goods_name = "测试商品A"
        mock_rfid_tag.shelf_id = 5

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_rfid_tag

        # Mock Inventory 查询 — 首次入库，返回 None
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_rfid_tag,  # RFIDTag 查询
            None,           # Inventory 查询 (首次)
        ]

        service._process_tag(mock_db_session, "ABC123456789", -45)

        # 验证 Insert: Inventory + InboundRecord
        assert mock_db_session.add.call_count >= 2

        # 提取所有 add 调用中的 InboundRecord
        records = [c[0][0] for c in mock_db_session.add.call_args_list if hasattr(c[0][0], 'status')]
        assert len(records) >= 1
        assert records[0].status == "success"
        assert records[0].epc == "ABC123456789"
        assert records[0].goods_name == "测试商品A"

    def test_process_tag_unregistered_epc(self, service, mock_db_session):
        """未注册 EPC: 仅创建 InboundRecord(failed)"""
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        service._process_tag(mock_db_session, "UNKNOWN_EPC_00", -60)

        # 应有一个 failed 记录，没有 Inventory 插入
        records = [c[0][0] for c in mock_db_session.add.call_args_list if hasattr(c[0][0], 'status')]
        assert len(records) == 1
        assert records[0].status == "failed"
        assert "未注册" in records[0].message
        assert records[0].epc == "UNKNOWN_EPC_00"

    def test_on_tag_detected_commits_and_increments(self, service, mock_db_session, monkeypatch):
        """检测到标签后应 commit 并更新计数"""
        service._running = True

        # Mock 整个 _process_tag 避免真实 DB 操作
        monkeypatch.setattr(service, "_process_tag", MagicMock())

        # Mock SessionLocal
        mock_session = MagicMock()
        monkeypatch.setattr("services.inbound_service.SessionLocal", lambda: mock_session)

        tag = make_tag("TAG001", rssi=-40)
        service._on_tag_detected(tag)

        assert mock_session.commit.called
        assert mock_session.close.called
        assert service._records_created == 1
        assert service._tags_scanned == 1

    def test_on_tag_detected_rollback_on_error(self, service, monkeypatch):
        """处理异常时应 rollback"""
        service._running = True

        # _process_tag 抛出异常
        monkeypatch.setattr(service, "_process_tag", MagicMock(side_effect=RuntimeError("DB error")))

        mock_session = MagicMock()
        monkeypatch.setattr("services.inbound_service.SessionLocal", lambda: mock_session)

        tag = make_tag("TAG_ERR", rssi=-30)
        service._on_tag_detected(tag)

        assert mock_session.rollback.called
        assert mock_session.close.called
        assert service._errors == 1

    def test_on_tag_detected_ignores_when_stopped(self, service, monkeypatch):
        """服务已停止时忽略标签"""
        service._running = False
        cb = MagicMock()
        monkeypatch.setattr(service, "_process_tag", cb)

        tag = make_tag("TAG_STOPPED")
        service._on_tag_detected(tag)

        cb.assert_not_called()

    def test_start_to_stop_lifecycle(self, service, mock_reader):
        """完整的 start → stop 生命周期"""
        # Start
        result = service.start()
        assert result["success"] is True
        assert mock_reader.on_tag_detected is not None

        # Status
        s = service.status()
        assert s["data"]["running"] is True

        # Stop
        result = service.stop()
        assert result["success"] is True
        assert service._running is False
        mock_reader.stop_continuous_scan.assert_called_once()

        # Status after stop
        s = service.status()
        assert s["data"]["running"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])