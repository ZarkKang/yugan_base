@echo off
chcp 65001 >nul
echo ========================================
echo       域感智能 - Windows 快速启动
echo ========================================
echo.
echo [1] 启动无人机数据系统 (端口 8000)
echo [2] 启动仓库巡检系统 (端口 8001)
echo [3] 启动 API 网关 (端口 8080)
echo [4] 启动桌面应用 (开发模式)
echo [5] 使用 Docker Compose 启动全部
echo [0] 退出
echo.
set /p choice=请选择: 

if "%choice%"=="1" goto drone
if "%choice%"=="2" goto warehouse
if "%choice%"=="3" goto gateway
if "%choice%"=="4" goto desktop
if "%choice%"=="5" goto docker
if "%choice%"=="0" goto end
echo 无效选择
goto end

:drone
echo 启动无人机数据系统...
cd drone-db-prototype\backend
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)
echo 激活虚拟环境...
call venv\Scripts\activate.bat
echo 安装依赖...
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
goto end

:warehouse
echo 启动仓库巡检系统...
cd warehouse-inspection-system\backend
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)
echo 激活虚拟环境...
call venv\Scripts\activate.bat
echo 安装依赖...
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
goto end

:gateway
echo 启动 API 网关...
cd api-gateway
if not exist "venv" (
    echo 创建虚拟环境...
    python -m venv venv
)
echo 激活虚拟环境...
call venv\Scripts\activate.bat
echo 安装依赖...
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
goto end

:desktop
echo 启动桌面应用...
cd desktop-app
npm run dev
goto end

:docker
echo 启动 Docker Compose...
docker-compose up -d
goto end

:end
