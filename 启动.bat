@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ========================================
::      域感智能 - Windows 快速启动/管理
:: ========================================

:: ── 默认配置 ──────────────────────────
set DRONE_PORT=8000
set WAREHOUSE_PORT=8001
set GATEWAY_PORT=8080

:: ── 获取项目根目录 ──────────────────────
cd /d "%~dp0"
set ROOT_DIR=%CD%

:: ── 检查 Python ──────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    goto end
)

:: ── 设置虚拟环境 ──────────────────────────
:setup_venv
set VENV_DIR=%~1
set REQ_FILE=%~2
cd /d "%VENV_DIR%"
if not exist "venv" (
    echo [信息] 创建虚拟环境...
    python -m venv venv
)
echo [信息] 激活虚拟环境...
call venv\Scripts\activate.bat
if exist "%REQ_FILE%" (
    echo [信息] 安装依赖 (%REQ_FILE%)...
    pip install -q -r "%REQ_FILE%" 2>nul || pip install -r "%REQ_FILE%"
)
cd /d "%ROOT_DIR%"
exit /b 0

:: ── 检查端口占用 (netstat) ────────────────
:check_port
netstat -ano | findstr /C:":%~1 " | findstr LISTENING >nul 2>&1
if errorlevel 1 (
    exit /b 0
) else (
    exit /b 1
)

:: ── 获取占用端口的 PID ─────────────────────
:get_port_pid
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr LISTENING') do (
    set PORT_PID=%%a
    goto :eof
)
set PORT_PID=

:: ── 停止指定端口进程 ───────────────────────
:stop_port
echo [信息] 正在停止占用端口 %~1 的进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /C:":%~1 " ^| findstr LISTENING') do (
    echo   终止 PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
exit /b 0

:: ── 后台启动后端服务 ───────────────────────
:start_backend
set SVC_NAME=%~1
set SVC_DIR=%~2
set SVC_MODULE=%~3
set SVC_PORT=%~4
set SVC_REQ=%~5

if exist "logs" (
    mkdir logs 2>nul
)

:: 检查端口占用
call :check_port %SVC_PORT%
if errorlevel 1 (
    echo [警告] 端口 %SVC_PORT% 已被占用，尝试停止旧进程...
    call :stop_port %SVC_PORT%
    timeout /t 2 /nobreak >nul
)

echo [信息] 启动 %SVC_NAME% (端口 %SVC_PORT%)...
cd /d "%ROOT_DIR%\%SVC_DIR%"
if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat
if exist "%SVC_REQ%" (
    pip install -q -r "%SVC_REQ%" 2>nul
)

start "%SVC_NAME%" /MIN cmd /c "uvicorn %SVC_MODULE% --host 0.0.0.0 --port %SVC_PORT% --reload"
timeout /t 3 /nobreak >nul
echo [完成] %SVC_NAME% 已启动 (端口 %SVC_PORT%)
cd /d "%ROOT_DIR%"
exit /b 0

:: ── 显示帮助 ─────────────────────────────────
:show_help
echo 域感智能 - Windows 系统管理脚本
echo.
echo 用法: 启动.bat [命令] [参数]
echo.
echo 命令:
echo   (无参数)       交互式菜单
echo   start ^<all^|drone^|warehouse^|gateway^>
echo                  启动指定服务
echo   stop ^<all^|drone^|warehouse^|gateway^>
echo                  停止指定服务
echo   status         查看所有服务状态
echo   init           初始化数据库和环境
echo   restart ^<all^|drone^|warehouse^|gateway^>
echo                  重启指定服务
echo   docker-start   启动 Docker Compose
echo   docker-stop    停止 Docker Compose
echo   help           显示此帮助信息
echo.
echo 示例:
echo   启动.bat start all      启动所有后端服务
echo   启动.bat status         查看服务状态
echo   启动.bat restart drone  重启无人机系统
echo.
exit /b 0

:: ── 交互式菜单 ───────────────────────────────
:menu
echo.
echo ========================================
echo       域感智能 - Windows 快速启动
echo ========================================
echo.
echo   启动服务:
echo     [1] 启动无人机数据系统 (端口 %DRONE_PORT%)
echo     [2] 启动仓库巡检系统 (端口 %WAREHOUSE_PORT%)
echo     [3] 启动 API 网关 (端口 %GATEWAY_PORT%)
echo     [4] 启动所有后端服务
echo     [5] 启动桌面应用 (开发模式)
echo     [6] 启动 Docker Compose
echo.
echo   管理:
echo     [7] 查看服务状态
echo     [8] 停止所有服务
echo     [9] 查看日志
echo     [a] 初始化数据库
echo     [b] 初始化桌面应用
echo.
echo   其他:
echo     [0] 退出
echo.
set /p choice=请选择: 
if "%choice%"=="1" goto start_drone
if "%choice%"=="2" goto start_warehouse
if "%choice%"=="3" goto start_gateway
if "%choice%"=="4" goto start_all
if "%choice%"=="5" goto start_desktop
if "%choice%"=="6" goto docker_start
if "%choice%"=="7" goto show_status
if "%choice%"=="8" goto stop_all
if "%choice%"=="9" goto show_logs
if "%choice%"=="a" goto init_db
if "%choice%"=="b" goto init_desktop
if "%choice%"=="0" goto end
echo 无效选择
timeout /t 1 /nobreak >nul
goto menu

:: ── 参数命令入口 ─────────────────────────────
if "%1"=="start" goto cmd_start
if "%1"=="stop" goto cmd_stop
if "%1"=="restart" goto cmd_restart
if "%1"=="status" goto show_status
if "%1"=="init" goto init_db
if "%1"=="logs" goto show_logs
if "%1"=="docker-start" goto docker_start
if "%1"=="docker-stop" goto docker_stop
if "%1"=="help" goto show_help
if "%1"=="--help" goto show_help
if "%1"=="-h" goto show_help

:: 无参数 → 交互式菜单
goto menu

:: ── 启动命令 ────────────────────────────────
:cmd_start
if "%2"=="all" goto start_all
if "%2"=="drone" goto start_drone
if "%2"=="warehouse" goto start_warehouse
if "%2"=="gateway" goto start_gateway
echo [错误] 未知服务: %2 (可选: all^|drone^|warehouse^|gateway)
goto end

:start_drone
call :start_backend "无人机数据系统" "drone-db-prototype\backend" "app.main:app" "%DRONE_PORT%" "requirements.txt"
goto end

:start_warehouse
call :start_backend "仓库巡检系统" "warehouse-inspection-system\backend" "src.main:app" "%WAREHOUSE_PORT%" "requirements.txt"
goto end

:start_gateway
call :start_backend "API网关" "api-gateway" "main:app" "%GATEWAY_PORT%" "requirements.txt"
goto end

:start_all
call :start_backend "无人机数据系统" "drone-db-prototype\backend" "app.main:app" "%DRONE_PORT%" "requirements.txt"
call :start_backend "仓库巡检系统" "warehouse-inspection-system\backend" "src.main:app" "%WAREHOUSE_PORT%" "requirements.txt"
call :start_backend "API网关" "api-gateway" "main:app" "%GATEWAY_PORT%" "requirements.txt"
echo.
echo [完成] 所有服务已启动！
echo.
echo   无人机数据:  http://localhost:%DRONE_PORT%
echo   仓库巡检:    http://localhost:%WAREHOUSE_PORT%
echo   API网关:     http://localhost:%GATEWAY_PORT%
echo   仓库前端:    file:///%ROOT_DIR:\=/%/warehouse-inspection-system/frontend/index.html
echo.
goto end

:start_desktop
echo [信息] 初始化桌面应用...
cd /d "%ROOT_DIR%\desktop-app"
if not exist "node_modules" (
    echo [信息] 安装依赖...
    call npm install
)
echo [信息] 启动桌面应用...
call npm run dev
goto end

:: ── 停止命令 ────────────────────────────────
:cmd_stop
if "%2"=="all" goto stop_all
if "%2"=="drone" (
    call :stop_port %DRONE_PORT%
    echo [完成] 无人机数据系统已停止
)
if "%2"=="warehouse" (
    call :stop_port %WAREHOUSE_PORT%
    echo [完成] 仓库巡检系统已停止
)
if "%2"=="gateway" (
    call :stop_port %GATEWAY_PORT%
    echo [完成] API网关已停止
)
goto end

:stop_all
echo [信息] 正在停止所有服务...
call :stop_port %DRONE_PORT%
call :stop_port %WAREHOUSE_PORT%
call :stop_port %GATEWAY_PORT%

:: 停止 Electron 进程
tasklist | findstr /I "electron" >nul 2>&1
if not errorlevel 1 (
    echo [信息] 停止桌面应用...
    taskkill /F /IM electron.exe >nul 2>&1 || true
)

:: 停止 Docker
if exist "docker-compose.yml" (
    echo [信息] 停止 Docker Compose...
    docker-compose down 2>nul || true
)

:: 清理 PID 文件
if exist "logs" del /q /s logs\*.pid 2>nul
echo [完成] 所有服务已停止
goto end

:: ── 重启命令 ────────────────────────────────
:cmd_restart
if "%2"=="all" (
    call :stop_all
    timeout /t 2 /nobreak >nul
    goto start_all
)
if "%2"=="drone" (
    call :stop_port %DRONE_PORT%
    timeout /t 2 /nobreak >nul
    goto start_drone
)
if "%2"=="warehouse" (
    call :stop_port %WAREHOUSE_PORT%
    timeout /t 2 /nobreak >nul
    goto start_warehouse
)
if "%2"=="gateway" (
    call :stop_port %GATEWAY_PORT%
    timeout /t 2 /nobreak >nul
    goto start_gateway
)
echo [错误] 未知服务: %2
goto end

:: ── 状态检查 ─────────────────────────────────
:show_status
echo.
echo ========================================
echo          服务状态检查
echo ========================================

call :check_port %DRONE_PORT%
if errorlevel 1 (
    echo   无人机数据系统  [已停止]
) else (
    echo   无人机数据系统  [运行中]  端口 %DRONE_PORT%
)

call :check_port %WAREHOUSE_PORT%
if errorlevel 1 (
    echo   仓库巡检系统    [已停止]
) else (
    echo   仓库巡检系统    [运行中]  端口 %WAREHOUSE_PORT%
)

call :check_port %GATEWAY_PORT%
if errorlevel 1 (
    echo   API网关         [已停止]
) else (
    echo   API网关         [运行中]  端口 %GATEWAY_PORT%
)

:: Electron
tasklist | findstr /I "electron" >nul 2>&1
if not errorlevel 1 (
    echo   桌面应用        [运行中]
) else (
    echo   桌面应用        [已停止]
)

:: Docker
docker ps --format "  - {{.Names}}: {{.Status}}" --filter "name=yugan" 2>nul
if not errorlevel 1 (
    echo   Docker容器      [运行中]
) else (
    echo   Docker容器      [已停止]
)

:: 图传模块
ping -n 1 -w 1000 192.168.1.200 >nul 2>&1
if not errorlevel 1 (
    echo   图传模块(200)   [在线]
) else (
    echo   图传模块(200)   [离线]
)

echo.
goto end

:: ── 日志查看 ─────────────────────────────────
:show_logs
if exist "logs" (
    echo ========================================
    echo          系统日志
    echo ========================================
    dir /b logs\*.log 2>nul
    if errorlevel 1 (
        echo 暂无日志文件
    ) else (
        for %%f in (logs\*.log) do (
            echo.
            echo === %%~nf (最近 50 行) ===
            more +0 "%%f" | more -50
        )
    )
) else (
    echo 暂无日志文件
)
goto end

:: ── 初始化数据库 ──────────────────────────────
:init_db
echo [信息] 初始化数据库...

if exist "drone-db-prototype\database\migrations\init.sql" (
    echo [完成] 无人机数据库迁移文件已就绪
)

cd /d "%ROOT_DIR%\warehouse-inspection-system\backend"
if not exist "venv" (
    python -m venv venv
)
call venv\Scripts\activate.bat
pip install -q -r requirements.txt 2>nul

echo [信息] 检查数据库表结构...
python -c "import sys; sys.path.insert(0, 'src'); from db.database import engine, Base; Base.metadata.create_all(bind=engine); print('数据库表已创建/验证')" 2>nul
if not errorlevel 1 (
    echo [完成] 仓库巡检系统数据库表已就绪
) else (
    echo [警告] 数据库连接不可用，将在后端启动时自动创建
)
cd /d "%ROOT_DIR%"
goto end

:: ── 初始化桌面应用 ─────────────────────────────
:init_desktop
cd /d "%ROOT_DIR%\desktop-app"
if not exist "node_modules" (
    echo [信息] 安装桌面应用依赖...
    call npm install
)
echo [完成] 桌面应用已就绪
cd /d "%ROOT_DIR%"
goto end

:: ── Docker ──────────────────────────────────────
:docker_start
echo [信息] 启动 Docker Compose...
docker-compose up -d
echo [完成] Docker Compose 已启动
docker ps --filter "name=yugan" --format "  - {{.Names}}: {{.Status}}" 2>nul
goto end

:docker_stop
echo [信息] 停止 Docker Compose...
docker-compose down
echo [完成] Docker Compose 已停止
goto end

:: ── 退出 ──────────────────────────────────────────
:end
endlocal
