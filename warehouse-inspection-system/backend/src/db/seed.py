"""
数据库种子数据 - 创建默认管理员用户和测试无人机
"""
import logging
from datetime import datetime
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import SessionLocal
from ..models.models import User, Drone

logger = logging.getLogger(__name__)

# 密码加密上下文
# bcrypt__truncate_error=False: 静默截断超过72字节的密码，避免报错
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__truncate_error=False)

# 默认管理员账户
DEFAULT_ADMIN = {
    "username": "admin",
    "email": "admin@yugan.local",
    "password": "admin123",
    "full_name": "系统管理员",
    "role": "admin",
}

# 默认测试无人机
DEFAULT_DRONE = {
    "drone_code": "DRONE001",
    "drone_name": "测试无人机",
    "model": "DJI-M300",
    "status": "offline",
    "battery_level": 100.0,
}


def _user_exists(db: Session, username: str) -> bool:
    """检查用户是否已存在"""
    return db.query(User).filter(User.username == username).first() is not None


def _drone_exists(db: Session, drone_code: str) -> bool:
    """检查无人机是否已存在"""
    return db.query(Drone).filter(Drone.drone_code == drone_code).first() is not None


def seed_data() -> None:
    """初始化默认管理员用户和测试无人机"""
    db = SessionLocal()
    try:
        # 创建管理员
        if _user_exists(db, DEFAULT_ADMIN["username"]):
            logger.info("默认管理员用户已存在，跳过创建")
        else:
            hashed = pwd_context.hash(DEFAULT_ADMIN["password"])
            admin = User(
                username=DEFAULT_ADMIN["username"],
                email=DEFAULT_ADMIN["email"],
                hashed_password=hashed,
                full_name=DEFAULT_ADMIN["full_name"],
                role=DEFAULT_ADMIN["role"],
                is_active=True,
            )
            db.add(admin)
            logger.info(f"✅ 默认管理员创建成功: {DEFAULT_ADMIN['username']}")

        # 创建测试无人机
        if _drone_exists(db, DEFAULT_DRONE["drone_code"]):
            logger.info("测试无人机已存在，跳过创建")
        else:
            drone = Drone(
                drone_code=DEFAULT_DRONE["drone_code"],
                drone_name=DEFAULT_DRONE["drone_name"],
                model=DEFAULT_DRONE["model"],
                status=DEFAULT_DRONE["status"],
                battery_level=DEFAULT_DRONE.get("battery_level", 100.0),
            )
            db.add(drone)
            logger.info(f"✅ 测试无人机创建成功: {DEFAULT_DRONE['drone_code']}")

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"种子数据创建失败: {e}")
    finally:
        db.close()