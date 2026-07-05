"""
FastAPI 应用主入口
"""
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import logging
import os
import json
from pathlib import Path

from .core.config import settings
from .db.database import init_db, engine
from .db.redis import redis_client
from .db.seed import seed_data
from .api import auth, inspection, drones, gateway, images, rfid, system, dashboard, shelves, skus, videos, inbound, drone_integration
from .api import drone_api
from .api import ws as ws_api
from .api import ws_video as ws_video_api
from .api.auth import get_current_user
from .api.ws import get_broadcaster
from .core.exceptions import (
    validation_exception_handler,
    http_exception_handler,
    global_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException

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

    # 设置事件循环给 WebSocket 广播器 (跨线程 publish 用)
    import asyncio as _asyncio
    get_broadcaster().set_loop(_asyncio.get_running_loop())
    logger.info("[WS] EventBroadcaster 事件循环已绑定")

    # 初始化数据库
    init_db()
    logger.info("数据库初始化完成")

    # 初始化默认管理员用户
    seed_data()

    # 连接Redis
    if redis_client.connect():
        logger.info("Redis连接成功")
    else:
        logger.warning("Redis连接失败，将使用本地队列")

    # 启动自动化任务调度器
    try:
        from .services.automated_task import get_scheduler
        get_scheduler().start()
        logger.info("自动化任务调度器已启动")
    except Exception as e:
        logger.warning(f"自动化任务调度器启动失败: {e}")

    # RFID 自动连接 / 自动扫描（受配置项控制，默认关闭）
    try:
        from .hardware.rfid_reader import get_rfid_reader
        reader = get_rfid_reader()
        if settings.RFID_AUTO_CONNECT_ON_START:
            if reader.connect():
                logger.info("[RFID] 启动时自动连接成功")
                if settings.RFID_AUTO_SCAN_ON_START:
                    reader.start_continuous_scan()
                    logger.info("[RFID] 启动时自动连续扫描已开启")
            else:
                logger.warning("[RFID] 启动时自动连接失败，跳过自动扫描")
        elif settings.RFID_AUTO_SCAN_ON_START:
            # 仅开启自动扫描但未开启自动连接 → 也尝试连接一次
            if reader.connect():
                reader.start_continuous_scan()
                logger.info("[RFID] 启动时自动连续扫描已开启")
            else:
                logger.warning("[RFID] 自动扫描启用但连接失败，跳过")
    except Exception as e:
        logger.warning(f"[RFID] 启动时自动扫描初始化失败: {e}")

    yield

    # 关闭时 — 优雅停止入库服务
    try:
        from .services.inbound_service import get_inbound_service
        get_inbound_service().stop()
    except Exception:
        pass
    # 关闭时 — 停止 RFID 连续扫描（纯扫描模式，独立于入库服务）
    try:
        from .hardware.rfid_reader import get_rfid_reader
        get_rfid_reader().stop_continuous_scan()
    except Exception:
        pass
    # 停止自动化任务调度器
    try:
        from .services.automated_task import get_scheduler
        get_scheduler().stop()
    except Exception:
        pass
    # 关闭所有未关闭的 WS 视频流会话
    try:
        from .services.video_stream_aggregator import VideoStreamAggregator
        VideoStreamAggregator.get_instance().shutdown_all()
    except Exception:
        pass
    redis_client.disconnect()
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于无人机与基站的高效化仓库巡检联合系统 - 数据库接收与处理基站",
    lifespan=lifespan
)

# 注册全局异常处理器
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)


# CORS配置 - 从环境变量读取白名单
_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
try:
    _cors_origins = json.loads(settings.CORS_ORIGINS)
except (json.JSONDecodeError, TypeError):
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PathAliasMiddleware(BaseHTTPMiddleware):
    """路径别名中间件 — 将网关风格路径 /api/warehouse/* 和 /api/drone/* 重写为 /api/v1/*"""
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        for prefix in ("/api/warehouse/", "/api/drone/"):
            if path.startswith(prefix):
                new_path = "/api/v1/" + path[len(prefix):]
                request.scope["path"] = new_path
                request.scope["raw_path"] = new_path.encode()
                break
        return await call_next(request)


app.add_middleware(PathAliasMiddleware)

# 静态文件 - 前端资源
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    logger.info(f"前端静态文件目录: {FRONTEND_DIR}")
else:
    logger.warning(f"前端静态文件目录不存在: {FRONTEND_DIR}")

# 注册路由
# auth 路由: 登录/注册等公开端点，不需全局认证
app.include_router(auth.router, prefix="/api/v1")

# 纯前端路由: 需要 JWT 认证
app.include_router(rfid.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(system.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(dashboard.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(shelves.router, prefix="/api/v1")  # shelves端点自带认证
app.include_router(skus.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(inbound.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])
app.include_router(drone_integration.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])

# 混合路由: 部分端点供无人机调用(无认证)，部分供前端调用(需认证)
# 这些路由在端点级别添加认证
app.include_router(inspection.router, prefix="/api/v1")
app.include_router(drones.router, prefix="/api/v1")
app.include_router(gateway.router, prefix="/api/v1")
app.include_router(images.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")

# 系统配置 API（暂未启用 — system_config 依赖不完整）
# app.include_router(system_config.router, prefix="/api/v1", dependencies=[Depends(get_current_user)])

# WebSocket + 实时监控 (无前缀, WS 路径为 /ws/monitor; /system/workers 由 system.py 提供)
app.include_router(ws_api.router)
# WebSocket 视频流端点 (无前缀, WS 路径为 /ws/video/{drone_id})
app.include_router(ws_video_api.router)

# 无人机端 API 路由（无 JWT 认证，无人机直接调用）
app.include_router(drone_api.router, prefix="/api/drones")
app.include_router(drone_api.waypoints_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def root():
    """根路径 - 服务前端页面或返回 API 信息"""
    index_file = FRONTEND_DIR / "index.html" if FRONTEND_DIR.exists() else None
    if index_file and index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return JSONResponse(content={
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    })


@app.get("/health")
def health_check():
    """健康检查"""
    try:
        if redis_client.client:
            redis_client.client.ping()
            redis_status = True
        else:
            redis_status = False
    except Exception:
        redis_status = False
    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected" if redis_status else "disconnected"
    }


@app.get("/select", response_class=HTMLResponse)
async def system_selection():
    """系统选择页面"""
    select_file = Path(__file__).resolve().parent.parent.parent.parent / "index.html"
    if select_file.exists():
        return select_file.read_text(encoding="utf-8")
    return JSONResponse(content={"message": "系统选择页面不可用"})


@app.get("/api/status")
def system_status():
    """系统状态 - 包含数据库、Redis、服务列表等信息"""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    try:
        if redis_client.client:
            redis_client.client.ping()
            redis_status = "connected"
        else:
            redis_status = "disconnected"
    except Exception:
        redis_status = "disconnected"

    routers = [
        {"prefix": "/api/v1/auth", "description": "认证与用户管理"},
        {"prefix": "/api/v1/inspections", "description": "巡检任务管理"},
        {"prefix": "/api/v1/drones", "description": "无人机管理"},
        {"prefix": "/api/v1/gateway", "description": "数据网关"},
        {"prefix": "/api/v1/images", "description": "图像管理"},
        {"prefix": "/api/v1/rfid", "description": "RFID数据"},
        {"prefix": "/api/v1/system", "description": "系统管理"},
        {"prefix": "/api/v1/dashboard", "description": "仪表板"},
        {"prefix": "/api/v1/shelves", "description": "货架管理"},
        {"prefix": "/api/v1/skus", "description": "SKU管理"},
        {"prefix": "/api/v1/videos", "description": "视频管理"},
    ]

    return {
        "success": True,
        "data": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "database": db_status,
            "redis": redis_status,
            "services": routers,
            "docs": "/docs",
            "health": "/health",
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG
    )
