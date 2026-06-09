from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from .core.database import engine, Base
from .routers import (
    auth_router,
    users_router,
    skus_router,
    drones_router,
    videos_router,
    images_router,
    rfid_router,
    admin_router,
)
from .services.websocket_service import websocket_endpoint
from .services.tracing_service import tracing_middleware
from .init_data import init_default_data
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 初始化默认数据
init_default_data()

app = FastAPI(
    title="域感智能 - 无人机数据管理系统",
    description="管理无人机图传视频、图片、RFID数据和多SKU管理",
    version="2.0.0",
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全链路追踪中间件
app.middleware("http")(tracing_middleware)

# 注册路由
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(skus_router)
app.include_router(drones_router)
app.include_router(videos_router)
app.include_router(images_router)
app.include_router(rfid_router)
app.include_router(admin_router)


@app.websocket("/api/ws")
async def websocket_route(websocket: WebSocket):
    """WebSocket端点"""
    await websocket_endpoint(websocket)


@app.get("/")
def root():
    return {"message": "域感智能 - 无人机数据管理系统 API", "version": "2.0.0"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/status")
def api_status():
    """API状态信息"""
    from .services.websocket_service import manager
    from .services.tracing_service import tracing_service
    
    return {
        "status": "ok",
        "active_clients": len(manager.active_connections),
        "services": {
            "qr_code": "ready",
            "backup": "ready",
            "tracing": "ready",
            "websocket": "ready"
        }
    }
