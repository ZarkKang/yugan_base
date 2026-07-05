from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pathlib import Path
import traceback
import logging
import os

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
    inspections_router,
)
from .services.websocket_service import websocket_endpoint
from .services.tracing_service import tracing_middleware
from .init_data import init_default_data

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建数据库表（仓库巡检系统为主Schema持有者，此处仅确保共享表存在）
try:
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表检查完成（共享 PostgreSQL）")
except Exception as e:
    logger.warning(f"数据库表检查失败（可能已由仓库巡检系统创建）: {e}")

# 初始化默认数据（模块级执行一次）
try:
    init_default_data()
except Exception as e:
    logger.warning(f"模块初始化时 init_default_data 失败: {e}")

app = FastAPI(
    title="域感智能 - 无人机数据管理系统",
    description="管理无人机图传视频、图片、RFID数据和多SKU管理",
    version="2.0.0",
)

# ── 全局异常处理器 ──
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(e) for e in err["loc"]), "message": err["msg"], "type": err["type"]} for err in exc.errors()]
    return JSONResponse(status_code=422, content={"success": False, "message": "请求参数验证失败", "errors": errors})

async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": exc.detail})

async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕获异常 [{request.method} {request.url.path}]: {exc}\n{traceback.format_exc()}")
    return JSONResponse(status_code=500, content={"success": False, "message": "服务器内部错误"})

app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# CORS配置 - 从环境变量读取白名单
import json as _json
_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_env_cors = os.environ.get("CORS_ORIGINS")
if _env_cors:
    try:
        _cors_origins = _json.loads(_env_cors)
    except (_json.JSONDecodeError, TypeError):
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全链路追踪中间件
app.middleware("http")(tracing_middleware)

# 静态文件 - 前端资源
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    logger.info(f"前端静态文件目录: {FRONTEND_DIR}")
else:
    logger.warning(f"前端静态文件目录不存在: {FRONTEND_DIR}")

# 注册路由
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(skus_router)
app.include_router(drones_router)
app.include_router(videos_router)
app.include_router(images_router)
app.include_router(rfid_router)
app.include_router(admin_router)
app.include_router(inspections_router)


@app.websocket("/api/ws")
async def websocket_route(websocket: WebSocket):
    """WebSocket端点"""
    await websocket_endpoint(websocket)


@app.get("/", response_class=HTMLResponse)
async def root():
    """根路径 - 服务前端页面"""
    index_file = FRONTEND_DIR / "index.html" if FRONTEND_DIR.exists() else None
    if index_file and index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return JSONResponse(content={
        "name": "域感智能 - 基站数据库",
        "version": "2.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health"
    })


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """应用启动时确保默认数据存在"""
    logger.info("启动检查：确保默认数据已初始化...")
    try:
        init_default_data()
    except Exception as e:
        logger.error(f"startup init_default_data 失败: {e}")


@app.get("/select", response_class=HTMLResponse)
async def system_selection():
    """系统选择页面"""
    # 返回项目根目录下的系统选择页面
    select_file = FRONTEND_DIR.parent.parent / "index.html"
    if select_file.exists():
        return select_file.read_text(encoding="utf-8")
    # Fallback: inline 系统选择页
    return HTMLResponse(content='''<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>域感智能 - 系统选择</title>
<style>:root{--bg:#0a0f18;--surface:#111827;--border:#1e2d3d;--text:#e2e8f0;--text2:#b0bec5;--muted:#5f7d94;--blue:#3b82f6;--purple:#8b5cf6;--radius:10px;--font:'Inter','Segoe UI',system-ui,sans-serif}*{margin:0;padding:0;box-sizing:border-box}body{font-family:var(--font);background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 20% 30%,rgba(59,130,246,.06) 0%,transparent 50%),radial-gradient(ellipse at 80% 60%,rgba(139,92,246,.06) 0%,transparent 50%),var(--bg)}.container{text-align:center;max-width:640px;padding:24px}.brand{margin-bottom:48px}.brand h1{font-size:36px;font-weight:700;letter-spacing:-1px}.brand .sub{display:block;color:var(--muted);font-size:13px;letter-spacing:3px;text-transform:uppercase;margin-top:8px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:20px}@media(max-width:560px){.cards{grid-template-columns:1fr}}.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:32px 24px;cursor:pointer;transition:.2s;text-align:left;position:relative;overflow:hidden;text-decoration:none;color:var(--text);display:block}.card:hover{border-color:var(--blue);transform:translateY(-2px);box-shadow:0 8px 32px rgba(0,0,0,.3)}.card.card-purple:hover{border-color:var(--purple)}.card .card-icon{font-size:28px;margin-bottom:16px}.card .card-title{font-size:18px;font-weight:600;margin-bottom:8px}.card .card-desc{font-size:13px;color:var(--text2);line-height:1.5}.card .card-path{display:inline-block;margin-top:16px;font-size:11px;color:var(--muted);font-family:monospace;background:rgba(255,255,255,.05);padding:4px 10px;border-radius:4px}.card .card-accent{position:absolute;top:0;left:0;width:100%;height:3px;background:var(--blue)}.card.card-purple .card-accent{background:var(--purple)}.footer{margin-top:48px;font-size:11px;color:var(--muted)}</style></head>
<body><div class="container"><div class="brand"><h1>域感智能</h1><span class="sub">Yugan Intelligence Platform</span></div><div class="cards"><a href="http://localhost:8000" class="card card-purple"><div class="card-accent"></div><div class="card-icon">✈</div><div class="card-title">无人机数据管理系统</div><div class="card-desc">管理无人机图传视频、图片、RFID数据和多SKU管理</div><span class="card-path">端口 8000</span></a><a href="http://localhost:8001" class="card"><div class="card-accent"></div><div class="card-icon">◈</div><div class="card-title">仓库巡检系统</div><div class="card-desc">基于无人机与基站的高效化仓库巡检联合系统</div><span class="card-path">端口 8001</span></a></div><div class="footer">&copy; 2026 域感智能 - 仓库巡检与无人机数据管理平台</div></div></body></html>''')


@app.get("/api/status")
def api_status():
    """API状态信息"""
    from .services.websocket_service import manager
    from .services.tracing_service import tracing_service

    from .services.qr_service import _ZBAR_AVAILABLE

    return {
        "success": True,
        "data": {
            "status": "ok",
            "active_clients": len(manager.active_connections),
            "services": {
                "qr_code": "ready" if _ZBAR_AVAILABLE else "unavailable (libzbar0 not installed)",
                "backup": "ready",
                "tracing": "ready",
                "websocket": "ready"
            },
            "routers": [
                {"prefix": "/api/auth", "description": "认证与用户管理"},
                {"prefix": "/api/users", "description": "用户管理"},
                {"prefix": "/api/skus", "description": "SKU管理"},
                {"prefix": "/api/drones", "description": "无人机管理"},
                {"prefix": "/api/videos", "description": "视频管理"},
                {"prefix": "/api/images", "description": "图片管理"},
                {"prefix": "/api/rfid", "description": "RFID数据"},
                {"prefix": "/api/inspections", "description": "巡检查询(树状结构)"},
            ]
        }
    }
