"""初始化数据脚本：创建默认用户和测试数据"""
from .core.database import SessionLocal
from .core.security import get_password_hash, verify_password
from .models.user import User
from .models.drone import Drone
from .models.sku import SKU
import logging

logger = logging.getLogger(__name__)


def ensure_admin(db):
    """确保 admin 用户存在且密码可用
    
    统一认证：密码为 admin
    """
    admin = db.query(User).filter(User.username == "admin").first()
    if admin is None:
        admin = User(
            username="admin",
            email="admin@yugan.com",
            hashed_password=get_password_hash("admin"),
            is_active=True,
            role="admin"
        )
        db.add(admin)
        logger.info("✅ admin 用户已创建（密码：admin）")
    else:
        # 验证密码是否可验证（防止bcrypt版本变更导致hash不兼容）
        try:
            if not verify_password("admin", admin.hashed_password):
                admin.hashed_password = get_password_hash("admin")
                logger.info("🔄 admin 密码已刷新为统一密码（admin）")
            if not admin.is_active:
                admin.is_active = True
                logger.info("🔄 admin 账户已重新激活")
        except Exception as e:
            admin.hashed_password = get_password_hash("admin")
            logger.warning(f"🔄 admin 密码重置（验证异常: {e}）")
    db.flush()
    return admin


def init_default_data():
    """初始化默认数据"""
    db = SessionLocal()
    try:
        # 确保 admin 始终可用
        ensure_admin(db)

        # 创建默认用户（如果不存在）
        user_count = db.query(User).count()
        if user_count <= 1:
            defaults = [
                ("operator", "operator@yugan.com", "operator123", "operator"),
                ("viewer", "viewer@yugan.com", "viewer123", "viewer"),
            ]
            for uname, email, pwd, role in defaults:
                if not db.query(User).filter(User.username == uname).first():
                    db.add(User(username=uname, email=email,
                        hashed_password=get_password_hash(pwd),
                        is_active=True, role=role))
            logger.info("✅ 默认用户已创建（operator / viewer）")
        
        # 检查是否有无人机数据
        drone_count = db.query(Drone).count()
        if drone_count == 0:
            logger.info("创建测试无人机数据...")
            drones = [
                Drone(drone_code="DR-001", name="巡逻无人机A", model="M300",
                      manufacturer="DJI", latitude=30.5728, longitude=104.0668, status="idle"),
                Drone(drone_code="DR-002", name="巡检无人机B", model="Mavic 3",
                      manufacturer="DJI", latitude=30.6728, longitude=104.1668, status="idle")
            ]
            for drone in drones:
                db.add(drone)
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
            logger.info("✅ 测试SKU数据创建成功！")

        db.commit()
        logger.info("✅ 数据初始化完成！")
        
    except Exception as e:
        logger.error(f"❌ 数据初始化失败: {e}")
        db.rollback()
    finally:
        db.close()
