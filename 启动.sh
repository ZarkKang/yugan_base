
#!/bin/bash
# ========================================
#      域感智能 - Linux 快速启动
# ========================================

# 函数：检查端口是否被占用
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null ; then
        echo "端口 $port 已被占用"
        echo "请先关闭占用该端口的进程，或选择其他端口"
        return 1
    fi
    return 0
}

# 函数：设置虚拟环境
setup_venv() {
    local dir=$1
    cd "$dir" || return 1
    
    if [ ! -d "venv" ]; then
        echo "创建虚拟环境..."
        python3 -m venv venv
    fi
    
    echo "激活虚拟环境..."
    source venv/bin/activate
    
    echo "安装依赖..."
    pip install -r requirements.txt
    
    return 0
}

echo "========================================"
echo "      域感智能 - Linux 快速启动"
echo "========================================"
echo ""
echo "[1] 启动无人机数据系统 (端口 8000)"
echo "[2] 启动仓库巡检系统 (端口 8001)"
echo "[3] 启动 API 网关 (端口 8080)"
echo "[4] 启动桌面应用 (开发模式)"
echo "[5] 使用 Docker Compose 启动全部"
echo "[0] 退出"
echo ""
read -p "请选择: " choice

case $choice in
    1)
        echo "启动无人机数据系统..."
        if ! check_port 8000; then
            exit 1
        fi
        setup_venv "drone-db-prototype/backend"
        uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
        ;;
    2)
        echo "启动仓库巡检系统..."
        if ! check_port 8001; then
            exit 1
        fi
        setup_venv "warehouse-inspection-system/backend"
        uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
        ;;
    3)
        echo "启动 API 网关..."
        if ! check_port 8080; then
            exit 1
        fi
        setup_venv "api-gateway"
        uvicorn main:app --host 0.0.0.0 --port 8080 --reload
        ;;
    4)
        echo "启动桌面应用..."
        cd "desktop-app"
        npm run dev
        ;;
    5)
        echo "启动 Docker Compose..."
        docker-compose up -d
        ;;
    0)
        echo "退出"
        ;;
    *)
        echo "无效选择"
        ;;
esac
