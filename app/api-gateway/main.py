from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="域感智能 - API网关",
    description="统一API网关，整合无人机数据系统和仓库巡检系统；提供WebSocket实时监控代理与子页面路由",
    version="1.1.0"
)

# CORS配置 - 从环境变量读取白名单
_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_env_cors = os.environ.get("CORS_ORIGINS")
if _env_cors:
    try:
        _cors_origins = json.loads(_env_cors)
    except (json.JSONDecodeError, TypeError):
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 检测运行环境：Docker 或 本地
IS_DOCKER = os.environ.get('IS_DOCKER', 'false').lower() == 'true'

# 服务配置
SERVICES = {
    "drone-db": {
        "name": "无人机数据系统",
        "base_url": "http://drone-db:8000" if IS_DOCKER else "http://localhost:8000",
        "ws_url": "ws://drone-db:8000" if IS_DOCKER else "ws://localhost:8000",
        "healthy": False
    },
    "warehouse": {
        "name": "仓库巡检系统",
        "base_url": "http://warehouse:8000" if IS_DOCKER else "http://localhost:8001",
        "ws_url": "ws://warehouse:8000" if IS_DOCKER else "ws://localhost:8001",
        "healthy": False
    }
}

# HTTP客户端
client: Optional[httpx.AsyncClient] = None

# 静态文件根目录 (子页面路由用)
# Docker: /app 同级有 /app, /drone, /station 挂载点 (见 docker-compose.yml frontend 服务)
# 本地: 仓库根目录
if IS_DOCKER:
    STATIC_ROOT = Path("/station/warehouse-inspection-system/frontend")
    DRONE_FRONTEND_DIR = Path("/drone/drone-db-prototype/frontend")
    APP_FRONTEND_DIR = Path("/app_root")
else:
    _repo_root = Path(__file__).resolve().parent.parent.parent
    STATIC_ROOT = _repo_root / "station" / "warehouse-inspection-system" / "frontend"
    DRONE_FRONTEND_DIR = _repo_root / "drone" / "drone-db-prototype" / "frontend"
    APP_FRONTEND_DIR = _repo_root / "app"


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    global client
    client = httpx.AsyncClient(timeout=30.0)
    logger.info("API Gateway started")
    logger.info(f"Running in {'Docker' if IS_DOCKER else 'local'} mode")
    logger.info(f"Services: {SERVICES}")
    logger.info(f"Static root: {STATIC_ROOT}")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时清理"""
    global client
    if client:
        await client.aclose()
        logger.info("API Gateway shutdown")


async def check_service_health(service_name: str) -> bool:
    """检查服务健康状态"""
    service = SERVICES.get(service_name)
    if not service:
        return False

    try:
        response = await client.get(f"{service['base_url']}/health", timeout=5.0)
        service['healthy'] = response.status_code == 200
        return service['healthy']
    except Exception as e:
        logger.warning(f"Health check failed for {service_name}: {e}")
        service['healthy'] = False
        return False


@app.get("/gateway/status")
async def gateway_status():
    """获取网关状态"""
    for service_name in SERVICES.keys():
        await check_service_health(service_name)

    return {
        "status": "ok",
        "mode": "docker" if IS_DOCKER else "local",
        "services": SERVICES
    }


def _build_proxy_response(response: httpx.Response) -> Response:
    """构造代理响应 - 小响应直接读取 body 返回 Response (避免 StreamingResponse 提前关闭连接)"""
    # 过滤 hop-by-hop 头 (避免 content-length/content-encoding 冲突)
    skip_headers = {
        'content-encoding', 'transfer-encoding', 'content-length',
        'connection', 'keep-alive',
    }
    safe_headers = {
        k: v for k, v in response.headers.items()
        if k.lower() not in skip_headers
    }
    body = response.content  # 已解压
    safe_headers['content-length'] = str(len(body))
    return Response(
        content=body,
        status_code=response.status_code,
        headers=safe_headers,
        media_type=response.headers.get('content-type'),
    )


@app.api_route("/api/drone/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_drone_db(path: str, request: Request):
    """代理到无人机数据系统"""
    service = SERVICES.get("drone-db")
    if not service['healthy']:
        await check_service_health("drone-db")
        if not service['healthy']:
            raise HTTPException(status_code=503, detail="Drone DB service unavailable")

    # drone-db 后端路由前缀为 /api/（无 /v1 段），直接拼接
    url = f"{service['base_url']}/api/{path}"

    body = await request.body() if request.method != "GET" else None
    headers = dict(request.headers)
    headers.pop('host', None)

    try:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.query_params,
            content=body,
            follow_redirects=True
        )
        return _build_proxy_response(response)
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail="Bad gateway")


@app.api_route("/api/warehouse/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_warehouse(path: str, request: Request):
    """代理到仓库巡检系统"""
    service = SERVICES.get("warehouse")
    if not service['healthy']:
        await check_service_health("warehouse")
        if not service['healthy']:
            raise HTTPException(status_code=503, detail="Warehouse service unavailable")

    url = f"{service['base_url']}/api/v1/{path}"

    body = await request.body() if request.method != "GET" else None
    headers = dict(request.headers)
    headers.pop('host', None)

    try:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.query_params,
            content=body,
            follow_redirects=True
        )
        return _build_proxy_response(response)
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail="Bad gateway")


# ── WebSocket 代理: /ws/monitor → warehouse /ws/monitor ──────────

@app.websocket("/ws/monitor")
async def ws_proxy_to_warehouse(websocket: WebSocket):
    """
    WebSocket 代理: 前端 → api-gateway → warehouse /ws/monitor
    双向转发消息；任一端断开则关闭另一端。
    """
    service = SERVICES.get("warehouse")
    target_url = f"{service['ws_url']}/ws/monitor"

    # 透传 query 参数 (含 token)
    query_string = websocket.url.query
    if query_string:
        target_url = f"{target_url}?{query_string}"

    await websocket.accept()

    import websockets
    try:
        async with websockets.connect(target_url, ping_interval=20, ping_timeout=10) as upstream_ws:
            logger.info(f"[WS-Proxy] 已连接到上游: {target_url.split('?')[0]}")

            async def forward_client_to_upstream():
                """前端 → 上游"""
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await upstream_ws.send(msg)
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    logger.debug(f"[WS-Proxy] client→upstream 异常: {e}")

            async def forward_upstream_to_client():
                """上游 → 前端"""
                try:
                    while True:
                        msg = await upstream_ws.recv()
                        if isinstance(msg, bytes):
                            await websocket.send_text(msg.decode("utf-8", errors="ignore"))
                        else:
                            await websocket.send_text(msg)
                except Exception as e:
                    logger.debug(f"[WS-Proxy] upstream→client 异常: {e}")

            # 并行转发
            await asyncio.gather(
                forward_client_to_upstream(),
                forward_upstream_to_client(),
            )
    except Exception as e:
        logger.warning(f"[WS-Proxy] 上游连接失败: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "payload": {"message": f"网关无法连接到上游服务: {e}"},
                "timestamp": None,
            })
            await websocket.close(code=1011, reason="upstream unavailable")
        except Exception:
            pass


# ── 静态文件服务 (前端 SPA) ──────────────────────────────

# 挂载前端静态目录 (子路径访问静态资源)
if STATIC_ROOT.exists():
    app.mount("/station/static", StaticFiles(directory=str(STATIC_ROOT)), name="station-static")
    logger.info(f"[Static] /station/static → {STATIC_ROOT}")
if DRONE_FRONTEND_DIR.exists():
    app.mount("/drone/static", StaticFiles(directory=str(DRONE_FRONTEND_DIR)), name="drone-static")
    logger.info(f"[Static] /drone/static → {DRONE_FRONTEND_DIR}")
if APP_FRONTEND_DIR.exists():
    app.mount("/app/static", StaticFiles(directory=str(APP_FRONTEND_DIR)), name="app-static")
    logger.info(f"[Static] /app/static → {APP_FRONTEND_DIR}")


# ── 子页面路由 ─────────────────────────────────────────

@app.get("/station/{rest:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_station_page(rest: str):
    """基站前端子页面路由: /station/ → station/warehouse-inspection-system/frontend/index.html"""
    # 若请求的是具体静态文件 → 直接返回
    if rest and "." in rest.split("/")[-1]:
        file_path = STATIC_ROOT / rest
        if file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="文件不存在")

    # 否则返回 SPA 入口 index.html
    index_file = STATIC_ROOT / "index.html"
    if index_file.is_file():
        return index_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="基站前端未部署")


@app.get("/drone/{rest:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_drone_page(rest: str):
    """无人机前端子页面路由"""
    if rest and "." in rest.split("/")[-1]:
        file_path = DRONE_FRONTEND_DIR / rest
        if file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="文件不存在")

    index_file = DRONE_FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return index_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="无人机前端未部署")


@app.get("/app/{rest:path}", response_class=HTMLResponse, include_in_schema=False)
async def serve_app_page(rest: str):
    """应用前端子页面路由"""
    if rest and "." in rest.split("/")[-1]:
        file_path = APP_FRONTEND_DIR / rest
        if file_path.is_file():
            return FileResponse(file_path)
        raise HTTPException(status_code=404, detail="文件不存在")

    index_file = APP_FRONTEND_DIR / "index.html"
    if index_file.is_file():
        return index_file.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail="应用前端未部署")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_page():
    """根路径 - 系统选择页"""
    select_file = APP_FRONTEND_DIR / "index.html"
    if select_file.is_file():
        return select_file.read_text(encoding="utf-8")
    return HTMLResponse(content="<h1>域感智能 API网关</h1><p>前端未部署</p>", status_code=200)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "api-gateway", "version": "1.1.0"}
