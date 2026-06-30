"""验证 RFID 修改: 查询数据库确认数据入库、幂等性、EPC校验"""
import sys
sys.path.insert(0, '/mnt/e/A0.software/The computer files/桌面/域感智能/warehouse-inspection-system/backend')
sys.path.insert(0, '/mnt/e/A0.software/The computer files/桌面/域感智能/warehouse-inspection-system/backend/src')

import json
from src.db.database import SessionLocal
from src.models.models import InspectionRecord, Drone

db = SessionLocal()
try:
    # 查 DRONE001 的 id
    drone = db.query(Drone).filter(Drone.drone_code == "DRONE001").first()
    if not drone:
        print("ERROR: DRONE001 not found")
        sys.exit(1)
    print(f"DRONE001 -> drone.id={drone.id}")

    # 查最近5条 RFID 记录 (幂等键格式 RFID_{id}_TASK001_...)
    records = db.query(InspectionRecord).filter(
        InspectionRecord.record_code.like(f"RFID_{drone.id}_TASK001_%")
    ).order_by(InspectionRecord.id.desc()).limit(5).all()

    print(f"\n=== 幂等记录数: {len(records)} (应为1,第二次上传被跳过) ===")
    for r in records:
        print(f"\nid={r.id}")
        print(f"  record_code={r.record_code}")
        print(f"  rfid_data={r.rfid_data}")
        # 解析 detected_rfid_tags
        tags = json.loads(r.detected_rfid_tags)
        print(f"  detected_tags_count={len(tags)} (应为2,INVALID被跳过)")
        for t in tags:
            print(f"    epc={t['epc']} rssi={t.get('rssi_dbm')} sku_id={t.get('sku_id')}")
        print(f"  position=({r.drone_position_x},{r.drone_position_y},{r.drone_position_z})")
finally:
    db.close()
