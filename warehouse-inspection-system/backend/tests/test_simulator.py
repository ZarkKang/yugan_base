"""
模拟器全流程测试
================
模拟无人机端完整巡检流程：健康检查 → 心跳 → 获取任务 → 接收任务 →
获取航点 → 执行巡检 → 完成任务 → 查看报告。
"""
import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.database import Base, get_db
from models.models import (
    Drone, Task, Waypoint, InspectionRecord, ImageRecord,
    InspectionStatus, TaskStatus
)
from main import app


# ── 测试数据库 ──────────────────────────────────

@pytest.fixture(scope="module")
def test_engine():
    engine = create_engine("sqlite:///./test_simulator.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    os.remove("test_simulator.db") if os.path.exists("test_simulator.db") else None


@pytest.fixture
def db_session(test_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def client(db_session, test_engine):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_test_fixtures(db_session):
    """创建测试所需的基础数据：无人机、任务、航点"""
    # 无人机
    drone = Drone(
        drone_code="SIM-DRONE",
        drone_name="模拟测试无人机",
        model="DJI-M300",
        status="idle",
        battery_level=100.0,
    )
    db_session.add(drone)
    db_session.commit()
    db_session.refresh(drone)

    # 任务
    task = Task(
        task_code="SIM-TASK-001",
        task_name="模拟测试任务",
        task_type="routine",
        drone_id=drone.id,
        status=TaskStatus.CREATED,
        altitude=5.0,
        speed=2.0,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)

    # 航点
    for i in range(3):
        wp = Waypoint(
            task_id=task.id,
            waypoint_id=f"WP-{i+1:03d}",
            position_x=i * 2.0 + 1.0,
            position_y=2.0,
            position_z=3.0,
            expected_sku=f"SKU-TEST-{i+1:03d}",
            expected_location=f"货架-{i+1:02d}",
            camera_angle=45.0,
            sort_order=i + 1,
        )
        db_session.add(wp)
    db_session.commit()

    return drone, task


# ── 全流程测试 ──────────────────────────────────

class TestSimulatorFullFlow:
    """模拟器全流程测试"""

    def test_health_check(self, client, db_session):
        """步骤 1: 健康检查"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_heartbeat(self, client, db_session):
        """步骤 2: 心跳上报"""
        drone, _ = _create_test_fixtures(db_session)

        response = client.post(f"/api/v1/drones/{drone.drone_code}/heartbeat", json={
            "status": "flying",
            "battery": 90,
            "position": {"x": 1.0, "y": 0.0, "z": 5.0},
        })
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

    def test_fetch_available_tasks(self, client, db_session):
        """步骤 3: 获取可用任务"""
        drone, task = _create_test_fixtures(db_session)

        response = client.get(f"/api/v1/drones/{drone.drone_code}/tasks/available")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        items = data.get("data", {}).get("items", [])
        assert len(items) >= 1
        assert any(t["task_code"] == task.task_code for t in items)

    def test_accept_task(self, client, db_session):
        """步骤 4: 接收任务"""
        drone, task = _create_test_fixtures(db_session)

        response = client.post(
            f"/api/v1/drones/{drone.drone_code}/tasks/{task.task_code}/accept"
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

        # 验证任务状态已变为 running
        db_session.refresh(task)
        assert task.status == TaskStatus.RUNNING

    def test_fetch_waypoints(self, client, db_session):
        """步骤 5: 获取航点列表"""
        drone, task = _create_test_fixtures(db_session)

        response = client.get(f"/api/v1/inspection/tasks/{task.task_code}/waypoints")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        waypoints = data.get("data", {}).get("items", [])
        assert len(waypoints) == 3
        assert waypoints[0]["waypoint_id"] == "WP-001"
        assert waypoints[2]["waypoint_id"] == "WP-003"

    def test_upload_image(self, client, db_session):
        """步骤 6a: 上传图像"""
        drone, task = _create_test_fixtures(db_session)

        # 创建测试图像文件
        test_img = "test_upload.jpg"
        with open(test_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24\x2e\x27\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c\x30\x31\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32\xff\xdb\x00C\x01\x09\x09\x09\x0c\x0b\x0c\x18\x0d\x0d\x18\x32\x21\x1c\x21\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01\x7d\x01\x02\x03\x00\x04\x11\x05\x12\x21\x31\x41\x06\x13\x51\x61\x07\x22\x71\x14\x32\x81\x91\xa1\x08\x23\x42\xb1\xc1\x15\x52\xd1\xf0\x24\x33\x62\x72\x82\x09\x0a\x16\x17\x18\x19\x1a\x25\x26\x27\x28\x29\x2a\x34\x35\x36\x37\x38\x39\x3a\x3b\x3c\x3d\x3e\x3f\x43\x44\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79\x7a\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02\x77\x00\x01\x02\x03\x11\x04\x05\x21\x31\x06\x12\x41\x51\x07\x61\x71\x13\x22\x32\x81\x08\x14\x42\x91\xa1\xb1\xc1\x09\x23\x33\x52\xf0\x15\x62\x72\xd1\x0a\x16\x24\x34\xe1\x25\xf1\x17\x18\x19\x1a\x26\x27\x28\x29\x2a\x35\x36\x37\x38\x39\x3a\x3b\x3c\x3d\x3e\x3f\x43\x44\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79\x7a\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xf9\xfe\x8a\x28\xa0\x0f\xff\xd9")

        with open(test_img, "rb") as f:
            response = client.post(
                "/api/v1/images/upload",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={
                    "drone_code": "SIM-DRONE",
                    "task_code": "SIM-TASK-001",
                    "waypoint_id": "WP-001",
                    "position_x": "1.0",
                    "position_y": "2.0",
                    "position_z": "3.0",
                    "camera_angle": "45",
                    "capture_index": "0",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        assert data.get("data", {}).get("image_id") is not None

        os.remove(test_img)

    def test_complete_task(self, client, db_session):
        """步骤 7: 完成任务"""
        drone, task = _create_test_fixtures(db_session)

        # 先接受任务
        client.post(f"/api/v1/drones/{drone.drone_code}/tasks/{task.task_code}/accept")

        response = client.post(
            f"/api/v1/inspection/tasks/{task.task_code}/complete",
            json={"total_scanned": 3, "recognized": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True

        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

    def test_view_task_detail(self, client, db_session):
        """步骤 8: 查看任务详情"""
        drone, task = _create_test_fixtures(db_session)

        response = client.get(f"/api/v1/inspection/tasks/{task.task_code}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("success") is True
        task_data = data.get("data", {})
        assert task_data.get("task_code") == task.task_code
        assert task_data.get("task_name") == task.task_name

    def test_full_flow(self, client, db_session):
        """完整流程：从创建到完成的端到端测试"""
        drone, task = _create_test_fixtures(db_session)

        # 1. 健康检查
        r = client.get("/health")
        assert r.json()["status"] == "healthy"

        # 2. 心跳
        r = client.post(f"/api/v1/drones/{drone.drone_code}/heartbeat", json={
            "status": "idle", "battery": 95,
            "position": {"x": 0, "y": 0, "z": 0},
        })
        assert r.json().get("success") is True

        # 3. 获取可用任务
        r = client.get(f"/api/v1/drones/{drone.drone_code}/tasks/available")
        assert r.json().get("success") is True
        items = r.json()["data"]["items"]
        assert len(items) >= 1

        # 4. 接收任务
        r = client.post(f"/api/v1/drones/{drone.drone_code}/tasks/{task.task_code}/accept")
        assert r.json().get("success") is True
        db_session.refresh(task)
        assert task.status == TaskStatus.RUNNING

        # 5. 获取航点
        r = client.get(f"/api/v1/inspection/tasks/{task.task_code}/waypoints")
        assert r.json().get("success") is True
        waypoints = r.json()["data"]["items"]
        assert len(waypoints) == 3

        # 6. 上传图像
        test_img = "test_flow.jpg"
        with open(test_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\x09\x09\x08\x0a\x0c\x14\x0d\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c\x20\x24\x2e\x27\x20\x22\x2c\x23\x1c\x1c\x28\x37\x29\x2c\x30\x31\x34\x34\x34\x1f\x27\x39\x3d\x38\x32\x3c\x2e\x33\x34\x32\xff\xdb\x00C\x01\x09\x09\x09\x0c\x0b\x0c\x18\x0d\x0d\x18\x32\x21\x1c\x21\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\x32\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01\x7d\x01\x02\x03\x00\x04\x11\x05\x12\x21\x31\x41\x06\x13\x51\x61\x07\x22\x71\x14\x32\x81\x91\xa1\x08\x23\x42\xb1\xc1\x15\x52\xd1\xf0\x24\x33\x62\x72\x82\x09\x0a\x16\x17\x18\x19\x1a\x25\x26\x27\x28\x29\x2a\x34\x35\x36\x37\x38\x39\x3a\x3b\x3c\x3d\x3e\x3f\x43\x44\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79\x7a\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02\x77\x00\x01\x02\x03\x11\x04\x05\x21\x31\x06\x12\x41\x51\x07\x61\x71\x13\x22\x32\x81\x08\x14\x42\x91\xa1\xb1\xc1\x09\x23\x33\x52\xf0\x15\x62\x72\xd1\x0a\x16\x24\x34\xe1\x25\xf1\x17\x18\x19\x1a\x26\x27\x28\x29\x2a\x35\x36\x37\x38\x39\x3a\x3b\x3c\x3d\x3e\x3f\x43\x44\x45\x46\x47\x48\x49\x4a\x53\x54\x55\x56\x57\x58\x59\x5a\x63\x64\x65\x66\x67\x68\x69\x6a\x73\x74\x75\x76\x77\x78\x79\x7a\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\xf9\xfe\x8a\x28\xa0\x0f\xff\xd9")

        with open(test_img, "rb") as f:
            r = client.post(
                "/api/v1/images/upload",
                files={"image": ("test.jpg", f, "image/jpeg")},
                data={
                    "drone_code": "SIM-DRONE",
                    "task_code": "SIM-TASK-001",
                    "waypoint_id": "WP-001",
                    "position_x": "1.0",
                    "position_y": "2.0",
                    "position_z": "3.0",
                    "camera_angle": "45",
                    "capture_index": "0",
                },
            )
        assert r.json().get("success") is True
        os.remove(test_img)

        # 7. 完成任务
        r = client.post(
            f"/api/v1/inspection/tasks/{task.task_code}/complete",
            json={"total_scanned": 3, "recognized": 1},
        )
        assert r.json().get("success") is True
        db_session.refresh(task)
        assert task.status == TaskStatus.COMPLETED

        # 8. 查看任务详情
        r = client.get(f"/api/v1/inspection/tasks/{task.task_code}")
        assert r.json().get("success") is True
        assert r.json()["data"]["task_code"] == task.task_code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])