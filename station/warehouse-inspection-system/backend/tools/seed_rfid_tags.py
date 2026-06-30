"""
EPC→商品映射种子数据填充
===========================
为 RFIDTag 表填充测试用 EPC 标签与商品映射数据，
使入库服务能够正确识别扫描到的 RFID 标签。
"""
import sys
import os
import json
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy.orm import Session
from db.database import SessionLocal
from models.models import RFIDTag, Shelf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 种子数据定义 ──────────────────────────────────

# 格式: (tag_id, tag_type, goods_name, goods_quantity, shelf_code)
DEFAULT_TAGS = [
    # 电子产品
    ("E20000123456789012345678", "UHF-GEN2",  "笔记本电脑 ThinkPad X1", 10,  "A-01"),
    ("E20000123456789012345679", "UHF-GEN2",  "笔记本电脑 ThinkPad X1", 10,  "A-01"),
    ("E20000123456789012345680", "UHF-GEN2",  "笔记本电脑 MacBook Pro", 8,   "A-02"),
    ("E20000123456789012345681", "UHF-GEN2",  "笔记本电脑 MacBook Pro", 8,   "A-02"),
    ("E20000123456789012345682", "UHF-GEN2",  "显示器 Dell 27寸 4K",    15,  "A-03"),
    ("E20000123456789012345683", "UHF-GEN2",  "显示器 Dell 27寸 4K",    15,  "A-03"),
    ("E20000123456789012345684", "UHF-GEN2",  "键盘机械 RK987",         50,  "A-04"),
    ("E20000123456789012345685", "UHF-GEN2",  "鼠标无线 Logitech MX",   60,  "A-04"),

    # 日用品
    ("E20000200000000000000001", "UHF-GEN2",  "洗发水 500ml",           100, "B-01"),
    ("E20000200000000000000002", "UHF-GEN2",  "沐浴露 500ml",           100, "B-01"),
    ("E20000200000000000000003", "UHF-GEN2",  "牙膏 120g",              200, "B-02"),
    ("E20000200000000000000004", "UHF-GEN2",  "毛巾纯棉 34x76cm",       80,  "B-02"),
    ("E20000200000000000000005", "UHF-GEN2",  "洗衣液 2kg",             60,  "B-03"),
    ("E20000200000000000000006", "UHF-GEN2",  "纸巾抽纸 3层120抽",      120, "B-03"),

    # 食品饮料
    ("E20000300000000000000001", "UHF-GEN2",  "矿泉水 550ml",           500, "C-01"),
    ("E20000300000000000000002", "UHF-GEN2",  "可乐 330ml",             300, "C-01"),
    ("E20000300000000000000003", "UHF-GEN2",  "方便面红烧牛肉味",       200, "C-02"),
    ("E20000300000000000000004", "UHF-GEN2",  "饼干苏打 200g",          150, "C-02"),
    ("E20000300000000000000005", "UHF-GEN2",  "咖啡速溶 100条",         80,  "C-03"),
    ("E20000300000000000000006", "UHF-GEN2",  "茶叶绿茶 250g",          60,  "C-03"),

    # 办公用品
    ("E20000400000000000000001", "UHF-GEN2",  "A4打印纸 500张",         200, "D-01"),
    ("E20000400000000000000002", "UHF-GEN2",  "签字笔黑色 0.5mm",       500, "D-01"),
    ("E20000400000000000000003", "UHF-GEN2",  "文件夹 A4",              100, "D-02"),
    ("E20000400000000000000004", "UHF-GEN2",  "订书机",                 50,  "D-02"),
    ("E20000400000000000000005", "UHF-GEN2",  "胶带48mmx50m",           80,  "D-03"),
    ("E20000400000000000000006", "UHF-GEN2",  "便签纸 76x76mm",         300, "D-03"),

    # 服装
    ("E20000500000000000000001", "UHF-GEN2",  "T恤纯棉白色 M码",        40,  "E-01"),
    ("E20000500000000000000002", "UHF-GEN2",  "T恤纯棉白色 L码",        40,  "E-01"),
    ("E20000500000000000000003", "UHF-GEN2",  "牛仔裤蓝色 32码",        30,  "E-02"),
    ("E20000500000000000000004", "UHF-GEN2",  "运动鞋白色 42码",        25,  "E-02"),
    ("E20000500000000000000005", "UHF-GEN2",  "帽子棒球帽黑色",         60,  "E-03"),
    ("E20000500000000000000006", "UHF-GEN2",  "围巾羊毛 180cm",         35,  "E-03"),
]


def seed_rfid_tags(db: Session = None):
    """向 RFIDTag 表填充种子数据"""
    own_session = db is None
    if own_session:
        db = SessionLocal()

    try:
        # 先确保货架存在
        shelf_codes = set(tag[4] for tag in DEFAULT_TAGS)
        shelf_map = {}
        for code in sorted(shelf_codes):
            shelf = db.query(Shelf).filter(Shelf.shelf_code == code).first()
            if not shelf:
                shelf = Shelf(
                    shelf_code=code,
                    shelf_name=f"货架 {code}",
                    location=f"区域{code[0]}-排{code[1:]}",
                    capacity=200,
                )
                db.add(shelf)
                db.flush()
                logger.info(f"  创建货架: {code}")
            shelf_map[code] = shelf.id

        # 填充 RFID 标签
        created = 0
        updated = 0
        skipped = 0

        for tag_id, tag_type, goods_name, quantity, shelf_code in DEFAULT_TAGS:
            existing = db.query(RFIDTag).filter(RFIDTag.tag_id == tag_id).first()
            if existing:
                # 更新已有记录
                existing.tag_type = tag_type
                existing.goods_name = goods_name
                existing.goods_quantity = quantity
                existing.shelf_id = shelf_map.get(shelf_code)
                updated += 1
            else:
                new_tag = RFIDTag(
                    tag_id=tag_id,
                    tag_type=tag_type,
                    goods_name=goods_name,
                    goods_quantity=quantity,
                    shelf_id=shelf_map.get(shelf_code),
                )
                db.add(new_tag)
                created += 1

        db.commit()
        logger.info(f"RFID 标签种子数据: 新增 {created}, 更新 {updated}, 跳过 {skipped}")

        # 打印摘要
        total = db.query(RFIDTag).count()
        logger.info(f"RFIDTag 表总计: {total} 条记录")

    except Exception as e:
        db.rollback()
        logger.error(f"种子数据填充失败: {e}")
        raise
    finally:
        if own_session:
            db.close()


def export_tags_to_json(filepath: str = "rfid_tags_seed.json"):
    """将种子数据导出为 JSON 文件（便于手动编辑）"""
    data = [
        {
            "tag_id": t[0],
            "tag_type": t[1],
            "goods_name": t[2],
            "goods_quantity": t[3],
            "shelf_code": t[4],
        }
        for t in DEFAULT_TAGS
    ]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"种子数据已导出到: {filepath}")


def import_tags_from_json(filepath: str, db: Session = None):
    """从 JSON 文件导入 RFID 标签数据"""
    own_session = db is None
    if own_session:
        db = SessionLocal()

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        for item in data:
            existing = db.query(RFIDTag).filter(RFIDTag.tag_id == item["tag_id"]).first()
            if existing:
                existing.goods_name = item.get("goods_name")
                existing.goods_quantity = item.get("goods_quantity", 0)
                existing.tag_type = item.get("tag_type", "UHF-GEN2")
            else:
                new_tag = RFIDTag(
                    tag_id=item["tag_id"],
                    tag_type=item.get("tag_type", "UHF-GEN2"),
                    goods_name=item.get("goods_name"),
                    goods_quantity=item.get("goods_quantity", 0),
                )
                db.add(new_tag)
        db.commit()
        logger.info(f"从 JSON 导入完成: {len(data)} 条")
    except Exception as e:
        db.rollback()
        logger.error(f"导入失败: {e}")
        raise
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RFID EPC→商品映射种子数据工具")
    parser.add_argument("--export", action="store_true", help="导出种子数据到 JSON 文件")
    parser.add_argument("--import-file", type=str, help="从 JSON 文件导入数据")
    parser.add_argument("--seed", action="store_true", default=True, help="填充默认种子数据到数据库")
    args = parser.parse_args()

    if args.export:
        export_tags_to_json()
    elif args.import_file:
        import_tags_from_json(args.import_file)
    else:
        logger.info("=" * 50)
        logger.info("EPC→商品映射种子数据填充")
        logger.info("=" * 50)
        seed_rfid_tags()
        logger.info("完成!")