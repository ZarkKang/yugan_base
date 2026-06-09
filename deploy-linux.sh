
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
    if command -v apt &amp;&gt; /dev/null; then
        sudo apt update
    elif command -v dnf &amp;&gt; /dev/null; then
        sudo dnf check-update
    elif command -v pacman &amp;&gt; /dev/null; then
        sudo pacman -Sy
    fi
fi

# 安装基础依赖
echo ""
echo "正在安装基础依赖..."
if command -v apt &amp;&gt; /dev/null; then
    sudo apt install -y python3 python3-pip python3-venv nodejs npm git curl
elif command -v dnf &amp;&gt; /dev/null; then
    sudo dnf install -y python3 python3-pip python3-venv nodejs npm git curl
elif command -v pacman &amp;&gt; /dev/null; then
    sudo pacman -S --noconfirm python python-pip nodejs npm git curl
fi

# 安装 Docker（可选）
echo ""
read -p "是否安装 Docker 和 Docker Compose？(y/n): " docker_choice
if [ "$docker_choice" = "y" ]; then
    echo "正在安装 Docker..."
    if command -v apt &amp;&gt; /dev/null; then
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
    cd "$(dirname "$0")"
fi

# 创建数据目录
echo ""
echo "正在创建数据目录..."
mkdir -p drone-db-prototype/backend/uploads
mkdir -p drone-db-prototype/backend/backups
mkdir -p drone-db-prototype/backend/traces

# 安装 Python 依赖
echo ""
echo "正在安装 Python 依赖..."
cd drone-db-prototype/backend &amp;&amp; pip install -r requirements.txt
cd ../../warehouse-inspection-system/backend &amp;&amp; pip install -r requirements.txt
cd ../../api-gateway &amp;&amp; pip install -r requirements.txt

# 安装 Node.js 依赖
echo ""
echo "正在安装 Node.js 依赖..."
cd ../desktop-app &amp;&amp; npm install

# 配置 systemd 服务（可选）
echo ""
read -p "是否配置 systemd 服务？(需要 root 权限) (y/n): " service_choice
if [ "$service_choice" = "y" ]; then
    cd ..
    sudo cp systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    echo "systemd 服务已安装！"
    echo "使用以下命令管理服务："
    echo "  sudo systemctl start yugan-drone"
    echo "  sudo systemctl enable yugan-drone"
    echo "  sudo systemctl start yugan-warehouse"
    echo "  sudo systemctl enable yugan-warehouse"
fi

# 设置权限
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
