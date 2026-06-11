@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM 模拟无人机 - 一键启动脚本 (Windows)
REM ============================================================
REM 功能:
REM   1. 自动创建/激活 Python 虚拟环境
REM   2. 安装依赖 (requests, Pillow, qrcode)
REM   3. 启动模拟无人机测试程序
REM ============================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "PYTHON_BIN=%VENV_DIR%\Scripts\python.exe"
set "PIP_BIN=%VENV_DIR%\Scripts\pip.exe"

echo ╔══════════════════════════════════════════════╗
echo ║     模拟无人机 - 虚拟环境自动启动             ║
echo ╚══════════════════════════════════════════════╝
echo.

REM ── 1. 检查 Python ───────────────────────────
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 python，请先安装 Python 3.10+
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set "PY_VER=%%i"
echo [OK] Python 版本: %PY_VER%

REM ── 2. 创建虚拟环境 ────────────────────────────
if not exist "%VENV_DIR%" (
    echo [创建] 虚拟环境: %VENV_DIR%
    python -m venv "%VENV_DIR%"
    if %ERRORLEVEL% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境已创建
) else (
    echo [OK] 虚拟环境已存在
)

REM ── 3. 安装依赖 ──────────────────────────────
echo [安装] 依赖...
call "%PIP_BIN%" install --quiet --upgrade pip >nul 2>&1

echo   安装 requests...
call "%PIP_BIN%" install --quiet requests >nul 2>&1

echo   安装 Pillow...
call "%PIP_BIN%" install --quiet Pillow >nul 2>&1

echo   安装 qrcode...
call "%PIP_BIN%" install --quiet "qrcode[pil]" >nul 2>&1

echo [OK] 依赖安装完成!
echo.

REM ── 4. 运行模拟程序 ────────────────────────────
echo 启动模拟无人机测试程序...
echo 提示: 使用 --help 查看所有选项
echo 提示: 使用 --auto 一键执行完整测试流程
echo.

call "%PYTHON_BIN%" "%SCRIPT_DIR%simulate_drone.py" %*

echo.
echo 测试完成!
pause