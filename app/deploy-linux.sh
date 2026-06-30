
#!/bin/bash
# ========================================
#      域感智能 - 一键部署脚本
# ========================================

set -e

echo "========================================"
echo "      域感智能 - 一键部署"
echo "========================================"
echo ""

# 检查是否为 root 用户
if [ "$EUID" -eq 0 ]; then 
    echo "请不要使用 root 用户运行此脚本"
    echo "请使用普通用户运行，并在需要时使用 sudo"
    exit 1
fi

# 检查系统
if [ ! -f /etc/os-release ]; then
    echo "无法检测操作系统，退出"
    exit 1
fi

source /etc/os-release
echo "检测到操作系统: $PRETTY_NAME"
echo ""

# 更新软件包
read -p "是否更新系统软件包？(y/n): " update_choice
if [ "$update_choice" = "y" ]; then
    echo "正在更新软件包..."
    if command -v apt &> /dev/null; then
        sudo apt update
    elif command -v dnf &> /dev/null; then
        sudo dnf check-update
    elif command -v pacman &> /dev/null; then
        sudo pacman -Sy
    fi
fi

# 安装基础依赖
echo ""
echo "正在安装基础依赖..."
if command -v apt &> /dev/null; then
    sudo apt install -y python3 python3-pip python3-venv nodejs npm git curl
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip python3-venv nodejs npm git curl
elif command -v pacman &> /dev/null; then
    sudo pacman -S --noconfirm python python-pip nodejs npm git curl
fi

# 安装 Docker（可选）
echo ""
read -p "是否安装 Docker 和 Docker Compose？(y/n): " docker_choice
if [ "$docker_choice" = "y" ]; then
    echo "正在安装 Docker..."
    if command -v apt &> /dev/null; then
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
        rm get-docker.sh
    fi
fi

# 克隆项目（如果需要）
echo ""
read -p "是否需要克隆项目到 /opt/yugan-intelligence？(y/n): " clone_choice
if [ "$clone_choice" = "y" ]; then
    sudo mkdir -p /opt
    sudo chown $USER:$USER /opt
    if [ ! -d "/opt/yugan-intelligence" ]; then
        cd /opt
        git clone https://github.com/yourusername/yugan-intelligence.git
        cd yugan-intelligence
    else
        echo "目录已存在，跳过克隆"
        cd /opt/yugan-intelligence
    fi
else
    cd "$(dirname "$0")/.."
fi

# 创建数据目录
echo ""
echo "正在创建数据目录..."
mkdir -p drone/drone-db-prototype/backend/uploads
mkdir -p drone/drone-db-prototype/backend/backups
mkdir -p drone/drone-db-prototype/backend/traces

# 安装 Python 依赖
echo ""
echo "正在安装 Python 依赖..."
cd drone/drone-db-prototype/backend && pip install -r requirements.txt
cd ../../station/warehouse-inspection-system/backend && pip install -r requirements.txt
cd ../../app/api-gateway && pip install -r requirements.txt

# 安装 Node.js 依赖
echo ""
echo "正在安装 Node.js 依赖..."
cd ../app/desktop-app && npm install

# 配置 systemd 服务（可选）
echo ""
read -p "是否配置 systemd 服务？(需要 root 权限) (y/n): " service_choice
if [ "$service_choice" = "y" ]; then
    cd ..
    sudo cp app/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    echo "systemd 服务已安装！"
    echo "使用以下命令管理服务："
    echo "  sudo systemctl start yugan-drone"
    echo "  sudo systemctl enable yugan-drone"
    echo "  sudo systemctl start yugan-warehouse"
    echo "  sudo systemctl enable yugan-warehouse"
fi

# ── RFID 串口权限自动配置 ──────────────────────
echo ""
echo "========================================"
echo "  配置 RFID 串口设备权限"
echo "========================================"

# 检测 RFID 设备
DETECTED_DEVICE=""
for dev in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$dev" ] && DETECTED_DEVICE="$dev" && break
done

if [ -n "$DETECTED_DEVICE" ]; then
    echo "检测到串口设备: $DETECTED_DEVICE"

    # 修复设备权限
    if [ -r "$DETECTED_DEVICE" ] && [ -w "$DETECTED_DEVICE" ]; then
        echo "[OK] 设备权限正常: $DETECTED_DEVICE"
    else
        echo "[WARN] 设备权限不足，尝试修复..."
        if sudo chmod 666 "$DETECTED_DEVICE" 2>/dev/null; then
            echo "[OK] 设备权限已修复: $DETECTED_DEVICE"
        else
            echo "[WARN] 无法修复设备权限，请手动执行: sudo chmod 666 $DETECTED_DEVICE"
        fi
    fi

    # 将用户加入 dialout 组（Linux 串口访问权限）
    if [ "$(uname -s)" = "Linux" ]; then
        if groups "$USER" 2>/dev/null | grep -q dialout; then
            echo "[OK] 用户已在 dialout 组"
        else
            echo "[WARN] 用户不在 dialout 组，尝试加入..."
            if sudo usermod -aG dialout "$USER" 2>/dev/null; then
                echo "[OK] 已将用户加入 dialout 组"
                echo "[INFO] 组变更将在重新登录后生效"
            else
                echo "[WARN] 加入 dialout 组失败，请手动执行: sudo usermod -aG dialout \$USER"
            fi
        fi
    fi

    # 将用户加入 docker 组（如果使用 Docker）
    if command -v docker &>/dev/null; then
        if groups "$USER" 2>/dev/null | grep -q docker; then
            echo "[OK] 用户已在 docker 组"
        else
            echo "[WARN] 用户不在 docker 组，尝试加入..."
            if sudo usermod -aG docker "$USER" 2>/dev/null; then
                echo "[OK] 已将用户加入 docker 组"
                echo "[INFO] 组变更将在重新登录后生效"
            else
                echo "[WARN] 加入 docker 组失败，请手动执行: sudo usermod -aG docker \$USER"
            fi
        fi
    fi
else
    echo "[INFO] 未检测到 RFID 串口设备，跳过权限配置"
    echo "  连接 RFID 设备后，请手动执行:"
    echo "    sudo chmod 666 /dev/ttyUSB0"
    echo "    sudo usermod -aG dialout \$USER"
fi

# 设置文件权限
echo ""
echo "正在设置文件权限..."
chmod +x 启动.sh

echo ""
echo "========================================"
echo "      部署完成！"
echo "========================================"
echo ""
echo "快速启动命令："
echo "  ./启动.sh                 # 菜单选择"
echo "  make drone                # 启动无人机数据系统"
echo "  make warehouse            # 启动仓库巡检系统"
echo "  make gateway              # 启动 API 网关"
echo "  make desktop              # 启动桌面应用"
echo "  make docker               # Docker 启动全部"
echo ""
echo "查看 LINUX_DEPLOYMENT.md 获取更多详情"
echo ""
