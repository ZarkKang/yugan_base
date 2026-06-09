"""初始化数据脚本：创建默认用户和测试数据"""
from .core.database import SessionLocal
from .core.security import get_password_hash
from .models.user import User
from .models.drone import Drone
from .models.sku import SKU
import logging

logger = logging.getLogger(__name__)


def init_default_data():
    """初始化默认数据"""
    db = SessionLocal()
    try:
        # 检查是否已有用户
        user_count = db.query(User).count()
        if user_count == 0:
            logger.info("创建默认用户...")
            # 创建管理员用户
            admin = User(
                username="admin",
                email="admin@yugan.com",
                hashed_password=get_password_hash("admin123"),
                is_active=True,
                role="admin"
            )
            db.add(admin)
            
            # 创建普通用户
            operator = User(
                username="operator",
                email="operator@yugan.com",
                hashed_password=get_password_hash("operator123"),
                is_active=True,
                role="operator"
            )
            db.add(operator)
            
            # 创建访客用户
            guest = User(
                username="guest",
                email="guest@yugan.com",
                hashed_password=get_password_hash("guest123"),
                is_active=True,
                role="guest"
            )
            db.add(guest)
            
            db.commit()
            logger.info("✅ 默认用户创建成功！")
            logger.info("   管理员: admin / admin123")
            logger.info("   操作员: operator / operator123")
            logger.info("   访客: guest / guest123")
        else:
            logger.info(f"✅ 用户已存在 ({user_count} 个)，跳过创建")
        
        # 检查是否有无人机数据
        drone_count = db.query(Drone).count()
        if drone_count == 0:
            logger.info("创建测试无人机数据...")
            drones = [
                Drone(
                    drone_code="DR-001",
                    name="巡逻无人机A",
                    model="M300",
                    manufacturer="DJI",
                    latitude=30.5728,
                    longitude=104.0668,
                    status="idle"
                ),
                Drone(
                    drone_code="DR-002",
                    name="巡检无人机B",
                    model="Mavic 3",
                    manufacturer="DJI",
                    latitude=30.6728,
                    longitude=104.1668,
                    status="idle"
                )
            ]
            for drone in drones:
                db.add(drone)
            db.commit()
            logger.info("✅ 测试无人机数据创建成功！")
        
        # 检查是否有SKU数据
        sku_count = db.query(SKU).count()
        if sku_count == 0:
            logger.info("创建测试SKU数据...")
            skus = [
                SKU(sku_code="SKU-001", name="传感器组件A", category="电子", unit="个"),
                SKU(sku_code="SKU-002", name="电池模块", category="配件", unit="块"),
                SKU(sku_code="SKU-003", name="摄像头模组", category="电子", unit="个"),
            ]
            for sku in skus:
                db.add(sku)
            db.commit()
            logger.info("✅ 测试SKU数据创建成功！")
        
        logger.info("✅ 数据初始化完成！")
        
    except Exception as e:
        logger.error(f"❌ 数据初始化失败: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    init_default_data()
