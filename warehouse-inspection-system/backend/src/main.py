"""
FastAPI 应用主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from .core.config import settings
from .db.database import init_db, engine
from .db.redis import redis_client
from .api import inspection, drones, gateway

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION}")

    # 初始化数据库
    init_db()
    logger.info("数据库初始化完成")

    # 连接Redis
    if redis_client.connect():
        logger.info("Redis连接成功")
    else:
        logger.warning("Redis连接失败，将使用本地队列")

    yield

    # 关闭时
    redis_client.disconnect()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于无人机与基站的高效化仓库巡检联合系统 - 数据库接收与处理基站",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(inspection.router, prefix="/api/v1")
app.include_router(drones.router, prefix="/api/v1")
app.include_router(gateway.router, prefix="/api/v1")


@app.get("/")
def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
def health_check():
    """健康检查"""
    redis_status = redis_client.is_connected if redis_client else False
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected" if redis_status else "disconnected"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
