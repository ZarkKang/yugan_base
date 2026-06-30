from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import httpx
from typing import Optional
import logging
import os

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="域感智能 - API网关",
    description="统一API网关，整合无人机数据系统和仓库巡检系统",
    version="1.0.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        # Docker 环境使用服务名，本地环境使用 localhost
        "base_url": "http://drone-db:8000" if IS_DOCKER else "http://localhost:8000",
        "healthy": False
    },
    "warehouse": {
        "name": "仓库巡检系统",
        "base_url": "http://warehouse:8000" if IS_DOCKER else "http://localhost:8001",
        "healthy": False
    }
}

# HTTP客户端
client: Optional[httpx.AsyncClient] = None


@app.on_event("startup")
async def startup_event():
    """启动时初始化"""
    global client
    client = httpx.AsyncClient(timeout=30.0)
    logger.info("API Gateway started")
    logger.info(f"Running in {'Docker' if IS_DOCKER else 'local'} mode")
    logger.info(f"Services: {SERVICES}")


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
    # 检查所有服务健康状态
    for service_name in SERVICES.keys():
        await check_service_health(service_name)
    
    return {
        "status": "ok",
        "mode": "docker" if IS_DOCKER else "local",
        "services": SERVICES
    }


@app.api_route("/api/drone/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_to_drone_db(path: str, request: Request):
    """代理到无人机数据系统"""
    service = SERVICES.get("drone-db")
    if not service['healthy']:
        # 尝试重新检查健康状态
        await check_service_health("drone-db")
        if not service['healthy']:
            raise HTTPException(status_code=503, detail="Drone DB service unavailable")
    
    url = f"{service['base_url']}/api/v1/{path}"
    
    # 转发请求
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
        
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )
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
    
    # 转发请求
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
        
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail="Bad gateway")


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "api-gateway"}
