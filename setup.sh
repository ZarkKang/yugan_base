#!/bin/bash
# ========================================
#   域感智能 - 环境初始化脚本 (setup.sh)
#   用途: 一次性环境检查与初始化
#   用法:
#     ./setup.sh           交互式引导菜单
#     ./setup.sh check     检查环境依赖
#     ./setup.sh init      初始化配置文件
#     ./setup.sh fix       尝试自动修复缺失依赖
# ========================================

set -o pipefail

# ═══════════════════════════════════════════
#  颜色与日志函数
# ═══════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[信息]${NC} $*"; }
ok()    { echo -e "${GREEN}[完成]${NC} $*"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $*"; }
error() { echo -e "${RED}[错误]${NC} $*"; }

confirm() {
    local msg="$1" default="${2:-N}"
    local prompt="[y/N]"
    [ "$default" = "Y" ] && prompt="[Y/n]"
    echo -e "${YELLOW}${msg} ${prompt}${NC}"
    read -r answer
    if [ "$default" = "Y" ]; then
        [[ ! "$answer" =~ ^[Nn]$ ]]
    else
        [[ "$answer" =~ ^[Yy]$ ]]
    fi
}

press_enter() {
    echo -e "\n${YELLOW}按回车键继续...${NC}"
    read -r
}

menu_select() {
    local prompt="$1"
    shift
    PS3="$prompt"
    select choice in "$@"; do
        PS3=""
        if [ -n "$choice" ]; then
            echo "$choice"
            return 0
        else
            error "无效选择"
            return 1
        fi
    done
}

# ═══════════════════════════════════════════
#  全局配置
# ═══════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
COMPOSE_WRAPPER="$SCRIPT_DIR/docker-compose-wrapper.sh"

# ═══════════════════════════════════════════
#  Docker Compose 包装器
# ═══════════════════════════════════════════
dc() {
    if [ -x "$COMPOSE_WRAPPER" ]; then
        "$COMPOSE_WRAPPER" "$@"
    elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose &>/dev/null; then
        docker-compose "$@"
    else
        error "Docker Compose 不可用，请先运行: ./setup.sh fix"
        return 1
    fi
}

# ═══════════════════════════════════════════
#  1. 环境检查
# ═══════════════════════════════════════════
check_environment() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 环境依赖检查 ━━━${NC}"
    echo ""

    local all_ok=true

    # ── Docker ──
    echo -e "${CYAN}── Docker ──${NC}"
    if command -v docker &>/dev/null; then
        ok "Docker: $(docker --version 2>&1)"
        if docker ps &>/dev/null 2>&1; then
            ok "Docker 守护进程: 运行中"
        else
            warn "Docker 守护进程: 未运行（需 sudo systemctl start docker 或将用户加入 docker 组）"
            all_ok=false
        fi
    else
        error "Docker: 未安装"
        all_ok=false
    fi

    # ── Docker Compose ──
    if command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
        ok "Docker Compose v2: $(docker compose version 2>&1 | head -1)"
    elif [ -x "$COMPOSE_WRAPPER" ]; then
        ok "Docker Compose: wrapper 可用"
    elif command -v docker-compose &>/dev/null; then
        ok "Docker Compose v1: $(docker-compose --version 2>&1)"
    else
        warn "Docker Compose: 未安装（运行 ./setup.sh fix 可自动下载）"
        all_ok=false
    fi

    # ── 用户组 ──
    echo ""
    echo -e "${CYAN}── 用户权限 ──${NC}"
    if groups "$USER" 2>/dev/null | grep -q docker; then
        ok "用户已在 docker 组"
    else
        warn "用户不在 docker 组（需 sudo usermod -aG docker \$USER 然后重新登录）"
        all_ok=false
    fi

    if groups "$USER" 2>/dev/null | grep -q dialout; then
        ok "用户已在 dialout 组（串口权限）"
    else
        warn "用户不在 dialout 组（RFID 串口可能无法访问）"
        all_ok=false
    fi

    # ── 配置文件 ──
    echo ""
    echo -e "${CYAN}── 配置文件 ──${NC}"
    if [ -f "$ENV_FILE" ]; then
        ok ".env: 存在"
        if grep -q "^JWT_SECRET_KEY=" "$ENV_FILE" && [ -n "$(grep "^JWT_SECRET_KEY=" "$ENV_FILE" | cut -d= -f2)" ]; then
            ok "JWT_SECRET_KEY: 已配置"
        else
            warn "JWT_SECRET_KEY: 未配置（运行 ./setup.sh init 自动生成）"
            all_ok=false
        fi
        if grep -q "^APP_MODE=" "$ENV_FILE"; then
            local mode
            mode=$(grep "^APP_MODE=" "$ENV_FILE" | cut -d= -f2)
            ok "APP_MODE: $mode"
        else
            warn "APP_MODE: 未设置（默认 dev，运行 ./option.sh 设置）"
            all_ok=false
        fi
    else
        error ".env: 不存在（运行 ./setup.sh init 创建）"
        all_ok=false
    fi

    # ── docker-compose.yml ──
    if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        ok "docker-compose.yml: 存在"
    else
        error "docker-compose.yml: 不存在"
        all_ok=false
    fi

    # ── 目录结构 ──
    echo ""
    echo -e "${CYAN}── 项目目录 ──${NC}"
    local dirs=(
        "station/warehouse-inspection-system/backend"
        "drone/drone-db-prototype/backend"
        "app/api-gateway"
        "app/scripts"
        "logs"
    )
    for d in "${dirs[@]}"; do
        if [ -d "$SCRIPT_DIR/$d" ]; then
            ok "$d"
        else
            warn "$d: 不存在"
        fi
    done

    # ── 串口设备 ──
    echo ""
    echo -e "${CYAN}── 串口设备 ──${NC}"
    local found_serial=false
    for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
        if [ -e "$dev" ]; then
            if [ -r "$dev" ] && [ -w "$dev" ]; then
                ok "$dev (可读写)"
            else
                warn "$dev (权限不足，需 chmod 666 或加入 dialout 组)"
            fi
            found_serial=true
        fi
    done
    $found_serial || info "未检测到串口设备（RFID 功能不可用）"

    echo ""
    $all_ok && ok "环境检查通过" || warn "环境检查发现缺失项，请运行 ./setup.sh fix 或 ./setup.sh init"

    return 0
}

# ═══════════════════════════════════════════
#  2. 初始化配置文件
# ═══════════════════════════════════════════
init_config() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 初始化配置文件 ━━━${NC}"
    echo ""

    # 生成 JWT_SECRET_KEY
    local jwt_key
    jwt_key=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "CHANGE_ME_TO_RANDOM_KEY")

    # 检测局域网 IP 段
    local lan_ip
    lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    local lan_origin=""
    if [ -n "$lan_ip" ]; then
        # 提取 IP 前三段作为局域网段
        lan_origin=$(echo "$lan_ip" | sed 's/\.[0-9]*$//')
        lan_origin="http://${lan_origin}.0:3000"
    fi

    if [ -f "$ENV_FILE" ]; then
        warn ".env 已存在"
        if ! confirm "是否覆盖现有 .env？（原有内容会备份为 .env.bak）"; then
            info "已取消"; return
        fi
        cp "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
        ok "已备份原 .env"
    fi

    # 构造 CORS 白名单（开发模式包含局域网段）
    local cors_dev="[\"http://localhost:3000\",\"http://127.0.0.1:3000\""
    if [ -n "$lan_origin" ]; then
        # 局域网段：http://192.168.x.0:3000 不准确，应放具体 IP
        cors_dev="$cors_dev,\"http://$lan_ip:3000\""
    fi
    cors_dev="$cors_dev]"

    cat > "$ENV_FILE" <<EOF
# 域感智能 - 环境配置文件
# 由 setup.sh 生成: $(date '+%Y-%m-%d %H:%M:%S')
# 修改后请运行: ./start.sh restart

# ── 运行模式 ──
# dev: 开发模式（DEBUG日志、Swagger开放、CORS宽松）
# prod: 生产模式（INFO日志、Swagger关闭、CORS严格、restart=always）
APP_MODE=dev

# ── JWT 认证 ──
JWT_SECRET_KEY=$jwt_key

# ── 数据库（Docker 容器内网络）──
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/warehouse_inspection

# ── Redis（Docker 容器内网络）──
REDIS_URL=redis://redis:6379/0

# ── CORS 白名单 ──
# 开发模式自动包含局域网 IP；生产模式应改为固定域名
CORS_ORIGINS=$cors_dev

# ── 调试模式（由 APP_MODE 控制，此处仅作备份）──
DEBUG=false

# ── RFID 硬件 ──
RFID_DEVICE=/dev/ttyUSB0
RFID_BAUD_RATE=115200

# ── JWT 配置 ──
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# ── 上传限制 ──
UPLOAD_DIR=./uploads
MAX_VIDEO_SIZE=500000000
MAX_IMAGE_SIZE=50000000

# ── 守护进程（默认关闭，使用 Docker restart 策略）──
DAEMON_ENABLED=false
DAEMON_CHECK_INTERVAL=30
EOF

    ok ".env 已创建: $ENV_FILE"
    info "JWT_SECRET_KEY: 已随机生成"
    info "APP_MODE: dev（运行 ./option.sh 切换生产模式）"
    info "CORS: $cors_dev"
    echo ""
    warn "如需局域网其他电脑访问，请将具体 IP 加入 CORS_ORIGINS"
    warn "或运行 ./option.sh 自动检测并添加局域网 IP"
}

# ═══════════════════════════════════════════
#  3. 自动修复
# ═══════════════════════════════════════════
fix_dependencies() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 自动修复缺失依赖 ━━━${NC}"
    echo ""

    local fixed=true

    # ── Docker Compose v2 wrapper ──
    if ! command -v docker &>/dev/null; then
        error "Docker 未安装，请手动安装: sudo apt install docker.io"
        fixed=false
    elif ! docker compose version &>/dev/null 2>&1 && [ ! -x "$COMPOSE_WRAPPER" ]; then
        info "尝试下载 docker-compose-v2 wrapper..."
        if [ -x "$COMPOSE_WRAPPER" ]; then
            ok "wrapper 已存在"
        else
            # 创建 wrapper 脚本
            cat > "$COMPOSE_WRAPPER" <<'WRAPPER'
#!/bin/bash
COMPOSE_PLUGIN="/tmp/docker-compose/usr/libexec/docker/cli-plugins/docker-compose"
if [ ! -f "$COMPOSE_PLUGIN" ]; then
    echo "[docker-compose-wrapper] 插件不存在，正在下载..."
    mkdir -p /tmp/docker-compose
    cd /tmp
    apt-get download docker-compose-v2 2>/dev/null || {
        echo "[docker-compose-wrapper] 下载失败，请手动执行: apt-get download docker-compose-v2"
        exit 1
    }
    DEB_FILE=$(ls -t docker-compose-v2*.deb 2>/dev/null | head -1)
    if [ -n "$DEB_FILE" ]; then
        dpkg-deb -x "$DEB_FILE" /tmp/docker-compose
        echo "[docker-compose-wrapper] 解压完成"
    else
        echo "[docker-compose-wrapper] 未找到deb文件"
        exit 1
    fi
    cd -
fi
exec "$COMPOSE_PLUGIN" "$@"
WRAPPER
            chmod +x "$COMPOSE_WRAPPER"
            ok "docker-compose-wrapper.sh 已创建"
        fi
    fi

    # ── .env 文件 ──
    if [ ! -f "$ENV_FILE" ]; then
        info ".env 不存在，自动初始化..."
        init_config
    fi

    # ── dialout 组 ──
    if ! groups "$USER" 2>/dev/null | grep -q dialout; then
        warn "用户不在 dialout 组（串口权限）"
        if sudo -n true 2>/dev/null; then
            sudo usermod -aG dialout "$USER" 2>/dev/null && ok "已加入 dialout 组（重新登录后生效）"
        else
            warn "无 sudo 权限，请手动执行: sudo usermod -aG dialout \$USER"
            fixed=false
        fi
    fi

    # ── docker 组 ──
    if ! groups "$USER" 2>/dev/null | grep -q docker; then
        warn "用户不在 docker 组"
        if sudo -n true 2>/dev/null; then
            sudo usermod -aG docker "$USER" 2>/dev/null && ok "已加入 docker 组（重新登录后生效）"
        else
            warn "无 sudo 权限，请手动执行: sudo usermod -aG docker \$USER"
            fixed=false
        fi
    fi

    # ── logs 目录 ──
    mkdir -p "$SCRIPT_DIR/logs"
    ok "logs 目录已确保存在"

    echo ""
    $fixed && ok "修复完成" || warn "部分项目需手动处理（见上方提示）"
}

# ═══════════════════════════════════════════
#  4. 构建镜像
# ═══════════════════════════════════════════
build_images() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 构建 Docker 镜像 ━━━${NC}"
    echo ""
    if ! confirm "将构建所有服务的 Docker 镜像（首次构建较慢）。继续？"; then
        info "已取消"; return
    fi
    info "开始构建..."
    dc build --parallel 2>&1 | tail -30
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        ok "镜像构建完成"
    else
        error "镜像构建失败"
    fi
}

# ═══════════════════════════════════════════
#  5. 重置数据卷
# ═══════════════════════════════════════════
reset_volumes() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 重置数据卷 ━━━${NC}"
    echo ""
    warn "此操作将删除所有数据（数据库、Redis、上传文件）！"
    if ! confirm "确定要重置吗？此操作不可恢复！"; then
        info "已取消"; return
    fi
    if ! confirm "再次确认：真的要删除所有数据吗？"; then
        info "已取消"; return
    fi
    info "停止服务并删除数据卷..."
    dc down -v 2>&1 | tail -10
    ok "数据卷已重置，运行 ./start.sh start 重新初始化"
}

# ═══════════════════════════════════════════
#  6. 主菜单
# ═══════════════════════════════════════════
main_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
        echo -e "${BOLD}${CYAN}║   域感智能 - 环境初始化              ║${NC}"
        echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-7]: " \
            "环境检查" \
            "初始化配置文件(.env)" \
            "自动修复缺失依赖" \
            "构建Docker镜像" \
            "重置数据卷(危险)" \
            "查看系统信息" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "环境检查")               check_environment; press_enter ;;
            "初始化配置文件(.env)")   init_config; press_enter ;;
            "自动修复缺失依赖")       fix_dependencies; press_enter ;;
            "构建Docker镜像")         build_images; press_enter ;;
            "重置数据卷(危险)")       reset_volumes; press_enter ;;
            "查看系统信息")           show_system_info; press_enter ;;
            "退出")                   echo -e "${GREEN}再见!${NC}"; exit 0 ;;
        esac
    done
}

show_system_info() {
    echo ""
    echo -e "${BOLD}系统信息${NC}"
    echo ""
    echo -e "${CYAN}── 系统 ──${NC}"
    echo "  主机名: $(hostname)"
    echo "  内核: $(uname -r)"
    echo "  架构: $(uname -m)"
    echo "  局域网IP: $(hostname -I 2>/dev/null | awk '{print $1}')"
    echo ""
    echo -e "${CYAN}── Docker ──${NC}"
    command -v docker &>/dev/null && echo "  版本: $(docker --version 2>&1)" || echo "  未安装"
    docker ps &>/dev/null 2>&1 && echo "  守护进程: 运行中 (容器数: $(docker ps -q 2>/dev/null | wc -l))" || echo "  守护进程: 已停止"
    echo ""
    echo -e "${CYAN}── 磁盘 ──${NC}"
    df -h "$SCRIPT_DIR" 2>/dev/null | tail -1 | awk '{printf "  总: %s  已用: %s  可用: %s (%s)\n", $2, $3, $4, $5}'
    echo ""
    echo -e "${CYAN}── 项目路径 ──${NC}"
    echo "  $SCRIPT_DIR"
}

# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT

case "${1:-menu}" in
    menu)       main_menu ;;
    check)      check_environment ;;
    init)       init_config ;;
    fix)        fix_dependencies ;;
    build)      build_images ;;
    info)       show_system_info ;;
    help|--help|-h)
        echo "用法: $0 [check|init|fix|build|info|menu]"
        echo ""
        echo "  check  - 检查环境依赖"
        echo "  init   - 初始化 .env 配置文件"
        echo "  fix    - 自动修复缺失依赖"
        echo "  build  - 构建 Docker 镜像"
        echo "  info   - 查看系统信息"
        echo "  menu   - 交互式菜单（默认）"
        ;;
    *)
        error "未知命令: $1"
        exit 1
        ;;
esac
