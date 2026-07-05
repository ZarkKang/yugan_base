"""
数据库模块 - 数据库连接
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator, Optional
import logging
from ..core.config import settings
from .migrations import run_migrations

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.DEBUG
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话的依赖项

    用法:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """初始化数据库（创建所有表 + 执行幂等迁移）

    注意：Base.metadata.create_all 只建新表，不为已有表加列。
    新增字段的迁移通过 db/migrations.py 的 run_migrations 执行，
    使用 PostgreSQL 原生 `ALTER TABLE ADD COLUMN IF NOT EXISTS`，幂等安全。
    """
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成")
    # 执行幂等迁移（新增字段、索引）
    try:
        run_migrations(engine)
    except Exception as e:
        logger.error("[init_db] 迁移执行失败（不阻塞启动）: %s", e, exc_info=True)


def drop_db() -> None:
    """删除所有数据库表（慎用）"""
    Base.metadata.drop_all(bind=engine)
    logger.warning("数据库表已删除")
