"""验证心跳自动维护 DroneDevice 记录"""
import sys
sys.path.insert(0, '/mnt/e/A0.software/The computer files/桌面/域感智能/warehouse-inspection-system/backend')
sys.path.insert(0, '/mnt/e/A0.software/The computer files/桌面/域感智能/warehouse-inspection-system/backend/src')

from src.db.database import SessionLocal
from src.models.models import Drone, DroneDevice
from datetime import datetime

db = SessionLocal()
try:
    drone = db.query(Drone).filter(Drone.drone_code == "DRONE001").first()
    print(f"Drone: id={drone.id}, code={drone.drone_code}, model={drone.model}, last_seen={drone.last_seen}")

    devices = db.query(DroneDevice).filter(DroneDevice.drone_id == drone.id).all()
    print(f"\nDroneDevice 记录数: {len(devices)} (心跳应自动创建1条)")
    for d in devices:
        age = (datetime.utcnow() - d.last_connected_at).total_seconds() if d.last_connected_at else None
        print(f"  id={d.id}, name={d.device_name}, model={d.device_model}, "
              f"ip={d.ip_address}, protocol={d.protocol}, status={d.status}, "
              f"last_connected={d.last_connected_at}, age={age:.1f}s")
finally:
    db.close()
