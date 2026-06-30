#!/bin/bash
# ========================================
#   域感智能 - 统一启动管理脚本
#   用法:
#     ./启动.sh             一键启动所有服务（默认）
#     ./启动.sh menu        交互式引导菜单
#     ./启动.sh start|stop|status|restart|app/logs|daemon|help
# ========================================

set -o pipefail

# ═══════════════════════════════════════════
#  1. 颜色输出与日志函数
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
debug() { echo -e "${BLUE}[调试]${NC} $*"; }

# 阶段标题
phase() { echo -e "\n${BOLD}${CYAN}━━━ 阶段 $1: $2 ━━━${NC}"; }

# ═══════════════════════════════════════════
#  2. 全局配置
# ═══════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE_FILE="$SCRIPT_DIR/.mode.conf"

DRONE_PORT=${DRONE_PORT:-8000}
WAREHOUSE_PORT=${WAREHOUSE_PORT:-8001}
GATEWAY_PORT=${GATEWAY_PORT:-8080}
HTTP_PORT=${HTTP_PORT:-3000}
PG_PORT=${PG_PORT:-5432}
REDIS_PORT=${REDIS_PORT:-6379}

PIP_MIRROR=${PIP_MIRROR:-""}
VENV_DIR=${VENV_DIR:-""}
MAX_LOG_SIZE=${MAX_LOG_SIZE:-10485760}
MAX_LOG_FILES=${MAX_LOG_FILES:-5}

PIP_EXTRA=""
if [ -n "$PIP_MIRROR" ]; then
    PIP_EXTRA="-i $PIP_MIRROR --trusted-host $(echo "$PIP_MIRROR" | sed -E 's|https?://||' | sed 's|/.*||')"
fi

# ═══════════════════════════════════════════
#  3. 工具函数
# ═══════════════════════════════════════════
require_cmd() {
    command -v "$1" &>/dev/null || { error "未找到命令: $1"; return 1; }
}

abs_path() {
    local rel="$1"
    local full="$SCRIPT_DIR/$rel"
    [ -d "$full" ] && echo "$full" || echo ""
}

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
#  6. 环境依赖诊断与修复函数（新增）
# ═══════════════════════════════════════════
# 本节整合启动过程中常见环境依赖错误的诊断与自动修复机制
# 错误类型: ensurepip缺失、pip缺失、版本冲突、PostgreSQL权限、Redis启动失败

# ── 诊断: ensurepip 不可用 ──
diagnose_ensurepip() {
    local venv_dir="$1"
    info "检测 ensurepip 可用性..."
    if python3 -c "import ensurepip" 2>/dev/null; then
        ok "ensurepip: 可用"
        return 0
    else
        warn "ensurepip: 不可用 (常见原因: python3-venv 未安装或受限环境)"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 有 sudo 权限时:"
        echo "     sudo apt install python3-venv python3-pip"
        echo ""
        echo "  2) 无 sudo 权限时 (降级方案):"
        echo "     mkdir -p /tmp/pip_bootstrap"
        echo "     cd /tmp/pip_bootstrap"
        echo "     curl -sS https://bootstrap.pypa.io/get-pip.py -o get-pip.py"
        echo "     python3 get-pip.py --target /tmp/pip_bootstrap/pip_packages"
        echo "     PYTHONPATH=/tmp/pip_bootstrap/pip_packages python3 -m pip install --target \$venv_dir/lib/python*/site-packages pip setuptools wheel"
        echo ""
        return 1
    fi
}

# ── 诊断: venv 中 pip 缺失 ──
diagnose_pip_in_venv() {
    local venv_dir="$1"
    local pip_bin="$venv_dir/bin/pip"
    info "检测 venv 中的 pip..."
    if [ -f "$pip_bin" ] && [ -x "$pip_bin" ]; then
        ok "pip: 已安装于 $venv_dir"
        "$pip_bin" --version 2>/dev/null || warn "pip 版本检测失败"
        return 0
    else
        warn "pip: 缺失于 $venv_dir"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 手动安装 pip 到 venv:"
        echo "     curl -sS https://bootstrap.pypa.io/get-pip.py | $venv_dir/bin/python3"
        echo ""
        echo "  2) 从系统 deb 包解压 pip (无网络时):"
        echo "     cd /tmp && apt-get download python3-pip"
        echo "     dpkg-deb -x python3-pip*.deb /tmp/pip_extract"
        echo "     cp -r /tmp/pip_extract/usr/lib/python*/dist-packages/pip \$venv_dir/lib/python*/site-packages/"
        echo "     cp /tmp/pip_extract/usr/bin/pip3 \$venv_dir/bin/pip"
        echo ""
        return 1
    fi
}

# ── 诊断: pip install 版本冲突 ──
diagnose_pip_version_conflict() {
    local log_content="$1"
    info "检测 pip 依赖版本冲突..."
    
    # 检测 numpy >= 2 与 opencv 不兼容
    if echo "$log_content" | grep -qiE "numpy.*2\.|opencv.*error|AttributeError.*numpy"; then
        warn "检测到 numpy>=2 与 opencv 版本冲突"
        echo ""
        echo "  ${CYAN}问题说明:${NC} OpenCV 4.x 不兼容 numpy 2.x，需降级 numpy"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  pip install 'numpy<2.0' --force-reinstall"
        echo ""
        return 1
    fi
    
    # 检测 pyzbar/libzbar 缺失
    if echo "$log_content" | grep -qiE "pyzbar.*ImportError|libzbar.*not found"; then
        warn "检测到 pyzbar 导入失败 (libzbar0 系统包缺失)"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  sudo apt install libzbar0"
        echo ""
        return 1
    fi
    
    # 检测 psycopg2 编译失败
    if echo "$log_content" | grep -qiE "psycopg2.*build|pg_config.*not found"; then
        warn "检测到 psycopg2 编译失败 (postgresql-dev 缺失)"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 安装系统依赖: sudo apt install libpq-dev postgresql-server-dev-all"
        echo "  2) 使用预编译二进制: pip install psycopg2-binary"
        echo ""
        return 1
    fi
    
    ok "无常见版本冲突"
    return 0
}

# ── 诊断: PostgreSQL 权限/认证失败 ──
diagnose_postgres_auth() {
    local pg_port="${1:-5432}"
    info "检测 PostgreSQL 认证状态..."
    
    # 检测 pg_isready
    if ! command -v pg_isready &>/dev/null; then
        warn "pg_isready: 未安装 (postgresql-client 缺失)"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  sudo apt install postgresql-client"
        return 1
    fi
    
    # 检测 PostgreSQL 运行状态
    if ! pg_isready -h localhost -p "$pg_port" &>/dev/null; then
        warn "PostgreSQL: 未运行于端口 $pg_port"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 启动服务: sudo service postgresql start"
        echo "  2) 或使用 Docker: docker compose up -d postgres"
        return 1
    fi
    
    # 检测密码认证 (尝试连接)
    if ! PGPASSWORD=postgres psql -h localhost -p "$pg_port" -U postgres -c "SELECT 1" &>/dev/null; then
        warn "PostgreSQL: 密码认证失败 (pg_hba.conf 配置或密码不匹配)"
        echo ""
        echo "  ${CYAN}常见原因:${NC}"
        echo "  1) pg_hba.conf 要求 peer 认证 (仅 UNIX socket)"
        echo "  2) postgres 用户密码未设置为 'postgres'"
        echo "  3) 无 sudo 权限修改 pg_hba.conf"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  方案A - 有 sudo 权限:"
        echo "    sudo -u postgres psql -c \"ALTER USER postgres WITH PASSWORD 'postgres';\""
        echo "    sudo sed -i 's|ident|md5|' /etc/postgresql/*/main/pg_hba.conf"
        echo "    sudo service postgresql restart"
        echo ""
        echo "  方案B - 无 sudo 权限 (自建 PostgreSQL 实例):"
        echo "    # 下载 postgresql-16 deb 包"
        echo "    cd /tmp && apt-get download postgresql-16 postgresql-client-16"
        echo "    dpkg-deb -x postgresql-16*.deb /tmp/pginst"
        echo "    dpkg-deb -x postgresql-client-16*.deb /tmp/pginst"
        echo "    # 初始化 trust 模式数据库"
        echo "    mkdir -p /tmp/pgdata"
        echo "    /tmp/pginst/usr/lib/postgresql/16/bin/initdb -D /tmp/pgdata -U postgres --auth=trust"
        echo "    # 启动于非标准端口"
        echo "    /tmp/pginst/usr/lib/postgresql/16/bin/pg_ctl -D /tmp/pgdata -o '-p 5433 -k /tmp' start"
        echo "    # 创建数据库"
        echo "    psql -h localhost -p 5433 -U postgres -c 'CREATE DATABASE warehouse_inspection;'"
        echo "    # 然后在项目 config.py 中将 POSTGRES_PORT 改为 5433"
        echo ""
        return 1
    fi
    
    ok "PostgreSQL: 认证正常 (端口 $pg_port)"
    return 0
}

# ── 诊断: Redis 启动失败 ──
diagnose_redis() {
    info "检测 Redis 状态..."
    
    if ! command -v redis-cli &>/dev/null; then
        warn "redis-cli: 未安装"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  sudo apt install redis-server"
        return 1
    fi
    
    if ! redis-cli ping 2>/dev/null | grep -q PONG; then
        warn "Redis: 未运行或无响应"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 启动服务: sudo service redis-server start"
        echo "  2) 或使用 Docker: docker compose up -d redis"
        echo "  3) 或手动启动: redis-server --daemonize yes"
        return 1
    fi
    
    ok "Redis: 运行正常"
    return 0
}

# ── 诊断: 网络连接/镜像源问题 ──
diagnose_network() {
    info "检测网络与 pip 镜像源..."
    
    # 测试默认镜像源（优先使用 wget，无 wget 时使用 curl）
    local test_url="${PIP_MIRROR:-https://pypi.org/simple}"
    local download_cmd=""
    
    if command -v wget &>/dev/null; then
        download_cmd="wget -q --timeout=5 --spider $test_url"
    elif command -v curl &>/dev/null; then
        download_cmd="curl -sS --connect-timeout 5 $test_url -o /dev/null"
    else
        warn "wget/curl: 未安装，无法测试网络连接"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  sudo apt install wget curl"
        return 1
    fi
    
    if eval "$download_cmd" 2>&1; then
        ok "网络: 可访问 $test_url"
        return 0
    else
        warn "网络: 无法访问 $test_url"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  1) 切换国内镜像源:"
        echo "     export PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
        echo ""
        echo "  2) 或使用阿里云源:"
        echo "     export PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/"
        echo ""
        return 1
    fi
}

# ── 自动修复: ensurepip 缺失时降级安装 pip ──
fix_ensurepip_fallback() {
    local venv_dir="$1"
    info "尝试降级方案: 手动安装 pip..."
    
    local bootstrap_dir="/tmp/pip_bootstrap_$(date +%s)"
    mkdir -p "$bootstrap_dir"
    
    # 检查 venv 是否有 python
    local venv_python="$venv_dir/bin/python3"
    if [ ! -f "$venv_python" ]; then
        venv_python="$venv_dir/bin/python"
    fi
    
    if [ ! -f "$venv_python" ]; then
        warn "venv 中无 python 解释器"
        return 1
    fi
    
    # 尝试下载 get-pip.py（使用 wget 或 curl）
    local get_pip_url="https://bootstrap.pypa.io/get-pip.py"
    local downloaded=false
    
    if command -v wget &>/dev/null; then
        info "使用 wget 下载 get-pip.py..."
        wget -q "$get_pip_url" -O "$bootstrap_dir/get-pip.py" 2>&1 && downloaded=true
    elif command -v curl &>/dev/null; then
        info "使用 curl 下载 get-pip.py..."
        curl -sS "$get_pip_url" -o "$bootstrap_dir/get-pip.py" 2>&1 && downloaded=true
    else
        warn "wget/curl: 未安装，无法下载 get-pip.py"
        echo ""
        echo "  ${CYAN}解决方案:${NC}"
        echo "  sudo apt install wget curl"
        return 1
    fi
    
    if [ "$downloaded" = true ] && [ -f "$bootstrap_dir/get-pip.py" ]; then
        ok "get-pip.py: 已下载"
        
        info "使用 venv 的 python 安装 pip..."
        "$venv_python" "$bootstrap_dir/get-pip.py" --no-wheel --no-setuptools 2>&1 | tail -3
        
        if [ -f "$venv_dir/bin/pip" ] || [ -f "$venv_dir/bin/pip3" ]; then
            ok "pip 已成功安装到 $venv_dir"
            rm -rf "$bootstrap_dir"
            return 0
        else
            warn "pip 安装可能失败，检查 venv/bin 目录"
        fi
    else
        warn "get-pip.py: 下载失败"
    fi
    
    rm -rf "$bootstrap_dir"
    return 1
}

# ── 自动修复: PostgreSQL 无 sudo 时自建实例 ──
fix_postgres_no_sudo() {
    local alt_port="${1:-5433}"
    info "尝试无 sudo 降级方案: 自建 PostgreSQL (端口 $alt_port)..."
    
    local pginst_dir="/tmp/pginst"
    local pgdata_dir="/tmp/pgdata_$alt_port"
    
    # 清理旧实例
    if [ -d "$pgdata_dir" ]; then
        warn "发现旧实例数据，停止并清理..."
        "$pginst_dir/usr/lib/postgresql/16/bin/pg_ctl" -D "$pgdata_dir" stop 2>/dev/null || true
        rm -rf "$pgdata_dir"
    fi
    
    # 下载并解压 postgresql-16 deb 包
    if [ ! -d "$pginst_dir" ] || [ ! -f "$pginst_dir/usr/lib/postgresql/16/bin/initdb" ]; then
        info "下载 PostgreSQL 16 deb 包..."
        mkdir -p "$pginst_dir"
        cd /tmp
        apt-get download postgresql-16 postgresql-client-16 2>&1 | grep -E "已下载|获取" | tail -2
        
        for deb in postgresql-16*.deb postgresql-client-16*.deb; do
            [ -f "$deb" ] && dpkg-deb -x "$deb" "$pginst_dir" 2>/dev/null && ok "已解压: $deb"
        done
        cd "$SCRIPT_DIR"
    fi
    
    local initdb_bin="$pginst_dir/usr/lib/postgresql/16/bin/initdb"
    local pg_ctl_bin="$pginst_dir/usr/lib/postgresql/16/bin/pg_ctl"
    
    if [ ! -f "$initdb_bin" ]; then
        error "initdb 不存在，降级方案失败"
        echo ""
        echo "  ${CYAN}手动方案:${NC}"
        echo "  请在有 sudo 权限的环境中配置 PostgreSQL，或联系管理员"
        return 1
    fi
    
    # 初始化数据库 (trust 模式)
    info "初始化 PostgreSQL 数据目录 (trust 认证)..."
    mkdir -p "$pgdata_dir"
    "$initdb_bin" -D "$pgdata_dir" -U postgres --auth=trust 2>&1 | tail -5
    
    # 配置 pg_hba.conf 为 trust
    cat > "$pgdata_dir/pg_hba.conf" <<'PGHBA'
local   all             all                                     trust
host    all             all             127.0.0.1/32            trust
host    all             all             ::1/128                 trust
PGHBA
    
    # 启动 PostgreSQL (使用非标准端口和 socket 目录)
    info "启动 PostgreSQL 于端口 $alt_port..."
    "$pg_ctl_bin" -D "$pgdata_dir" -o "-p $alt_port -k /tmp" -l "$pgdata_dir/pg.log" start 2>&1
    sleep 3
    
    # 检测是否启动成功
    if psql -h localhost -p "$alt_port" -U postgres -c "SELECT 1" &>/dev/null; then
        ok "自建 PostgreSQL 已启动 (端口 $alt_port)"
        
        # 创建数据库
        psql -h localhost -p "$alt_port" -U postgres -c "CREATE DATABASE warehouse_inspection;" 2>&1 | grep -E "CREATE|已存在" || warn "数据库创建可能已存在"
        
        # 提示用户修改配置
        echo ""
        echo -e "${YELLOW}════════════════════════════════════════${NC}"
        echo -e "${YELLOW}  重要: 需修改项目配置以使用自建实例${NC}"
        echo -e "${YELLOW}════════════════════════════════════════${NC}"
        echo ""
        echo "  请修改以下文件中的 POSTGRES_PORT:"
        echo "    station/warehouse-inspection-system/backend/src/core/config.py"
        echo "    将 POSTGRES_PORT: int = 5432 改为 POSTGRES_PORT: int = $alt_port"
        echo ""
        echo "  或设置环境变量:"
        echo "    export PG_PORT=$alt_port"
        echo ""
        
        # 自动修改 config.py (如果存在)
        local config_file="$SCRIPT_DIR/station/warehouse-inspection-system/backend/src/core/config.py"
        if [ -f "$config_file" ] && grep -q "POSTGRES_PORT.*5432" "$config_file"; then
            info "尝试自动修改 config.py..."
            sed -i "s|POSTGRES_PORT.*5432|POSTGRES_PORT: int = $alt_port|" "$config_file" 2>/dev/null && \
                ok "已修改 config.py: POSTGRES_PORT = $alt_port" || \
                warn "自动修改失败，请手动修改"
        fi
        
        # 导出环境变量供后续服务使用
        export PG_PORT="$alt_port"
        
        return 0
    else
        error "自建 PostgreSQL 启动失败"
        [ -f "$pgdata_dir/pg.log" ] && tail -10 "$pgdata_dir/pg.log"
        return 1
    fi
}

# ── 自动修复: pip install 失败时的版本降级 ──
fix_pip_numpy_opencv_conflict() {
    local venv_dir="$1"
    local pip_bin="$venv_dir/bin/pip"
    
    if [ ! -f "$pip_bin" ]; then
        pip_bin="$venv_dir/bin/pip3"
    fi
    
    if [ ! -f "$pip_bin" ]; then
        error "venv 中无 pip，无法执行版本降级"
        return 1
    fi
    
    info "尝试修复 numpy/opencv 版本冲突..."
    "$pip_bin" install 'numpy<2.0' --force-reinstall 2>&1 | tail -5
    
    if "$pip_bin" show numpy 2>/dev/null | grep -q "Version:"; then
        ok "numpy 已降级到 <2.0"
        return 0
    else
        warn "numpy 降级可能失败"
        return 1
    fi
}

# ═══════════════════════════════════════════
#  4. 端口统一管理（核心改进）
# ═══════════════════════════════════════════
check_port() {
    local port=$1
    ss -tlnp 2>/dev/null | grep -q ":${port} "
}

check_docker_port() {
    docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE "0\.0\.0\.0:${1}->|:${1}->"
}

get_port_pid() {
    local port=$1
    ss -tlnp sport = ":$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1
}

# 释放端口：安全停止占用端口的进程
release_port() {
    local port=$1 name="${2:-}"
    local label="${name:-端口 $port}"

    if check_docker_port "$port"; then
        warn "${label} 由 Docker 管理，跳过本地释放"
        return 1
    fi

    if ! check_port "$port"; then
        return 0  # 端口空闲
    fi

    local pid
    pid=$(get_port_pid "$port")
    if [ -n "$pid" ]; then
        info "释放 ${label} (PID: $pid)..."
        kill "$pid" 2>/dev/null
        sleep 0.5
        if kill -0 "$pid" 2>/dev/null; then
            warn "进程未响应，强制终止..."
            kill -9 "$pid" 2>/dev/null
            sleep 0.5
        fi
        if ! check_port "$port"; then
            ok "${label} 已释放"
            return 0
        fi
    fi

    # 兜底：pkill 匹配 uvicorn 进程
    pkill -f "uvicorn.*:${port}" 2>/dev/null
    sleep 0.5
    if ! check_port "$port"; then
        ok "${label} 已释放 (pkill)"
        return 0
    fi

    error "无法释放 ${label}，端口 $port 仍被占用"
    return 1
}

# 批量释放所有应用端口
release_all_ports() {
    info "释放所有应用端口..."
    local all_ok=true
    release_port "$DRONE_PORT" "无人机数据系统" || all_ok=false
    release_port "$WAREHOUSE_PORT" "仓库巡检系统" || all_ok=false
    release_port "$GATEWAY_PORT" "API网关" || all_ok=false
    $all_ok && ok "所有端口已释放" || warn "部分端口释放失败"
}

# 检查服务是否就绪
check_service_ready() {
    local name="$1" port="$2" max_wait="${3:-15}"
    info "等待 ${name} 就绪 (最多 ${max_wait}s)..."
    local i=0
    while [ $i -lt $max_wait ]; do
        if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$port/health" 2>/dev/null | grep -q "200"; then
            ok "${name} 已就绪 (端口 $port)"
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    error "${name} 未在 ${max_wait}s 内就绪"
    return 1
}

# ═══════════════════════════════════════════
#  5. 运行模式管理
# ═══════════════════════════════════════════
get_mode() {
    if [ -f "$MODE_FILE" ]; then
        source "$MODE_FILE"
    fi
    echo "${MODE:-hybrid}"
}

get_mode_label() {
    case "${1:-$(get_mode)}" in
        docker) echo "Docker" ;;
        local)  echo "本地" ;;
        hybrid) echo "混合" ;;
        *)      echo "未知" ;;
    esac
}

set_mode() {
    local mode="$1"
    echo "MODE=$mode" > "$MODE_FILE"
    export MODE="$mode"
    ok "运行模式已设置为: $(get_mode_label "$mode")"
}

select_mode() {
    echo -e "${BOLD}设置运行模式${NC}"
    echo ""
    echo "  当前模式: $(get_mode_label)"
    echo ""
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "Docker模式" \
        "本地模式" \
        "混合模式(推荐)" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "Docker模式")       set_mode "docker" ;;
        "本地模式")         set_mode "local" ;;
        "混合模式(推荐)")   set_mode "hybrid" ;;
        "返回")             ;;
    esac
}

# ═══════════════════════════════════════════
#  6. 环境检测与部署
# ═══════════════════════════════════════════
check_environment() {
    echo -e "${BOLD}环境检测${NC}"
    echo ""

    if command -v python3 &>/dev/null; then
        ok "Python3: $(python3 --version 2>&1)"
    else
        error "Python3 未安装"
    fi

    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        ok "PostgreSQL: 运行中"
    else
        warn "PostgreSQL: 未运行"
    fi

    if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
        ok "Redis: 运行中"
    else
        warn "Redis: 未运行"
    fi

    if command -v docker &>/dev/null; then
        ok "Docker: $(docker --version 2>&1)"
        if docker ps &>/dev/null 2>&1; then
            ok "Docker 守护进程: 运行中"
        else
            warn "Docker 守护进程: 未运行"
        fi
        if docker compose version &>/dev/null 2>&1; then
            ok "Docker Compose: $(docker compose version 2>&1 | head -1)"
        elif command -v docker-compose &>/dev/null; then
            ok "Docker Compose (v1): $(docker-compose --version 2>&1)"
        else
            warn "Docker Compose: 未安装"
        fi
    else
        error "Docker: 未安装"
    fi

    if dpkg -l libzbar0 2>/dev/null | grep -q ^ii; then
        ok "libzbar0: 已安装"
    else
        warn "libzbar0: 未安装 (QR功能需要)"
    fi

    echo ""
    for port in $DRONE_PORT $WAREHOUSE_PORT $GATEWAY_PORT $PG_PORT $REDIS_PORT; do
        if check_port "$port"; then
            warn "端口 $port: 已被占用"
        else
            ok "端口 $port: 空闲"
        fi
    done
}

install_dependencies() {
    echo -e "${BOLD}安装系统依赖${NC}"
    echo ""
    if ! confirm "将安装 PostgreSQL/Redis/libzbar0，需要 sudo 权限。继续？"; then
        warn "已取消"; return
    fi
    info "正在安装系统依赖..."
    sudo apt update && sudo apt install -y postgresql postgresql-contrib redis-server libzbar0
    if [ $? -eq 0 ]; then
        ok "系统依赖安装完成"
        info "启动服务..."
        sudo service postgresql start
        sudo service redis-server start
    else
        error "安装失败"
    fi
}

init_database() {
    echo -e "${BOLD}初始化数据库${NC}"
    echo ""
    if ! pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        error "PostgreSQL 未运行，请先启动数据库服务"; return
    fi
    info "创建共享数据库（两个系统共用 warehouse_inspection）..."
    sudo -u postgres psql -c "CREATE USER postgres WITH PASSWORD 'postgres' CREATEDB;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE warehouse_inspection OWNER postgres;" 2>/dev/null || warn "数据库已存在"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE warehouse_inspection TO postgres;" 2>/dev/null || true
    ok "共享数据库 warehouse_inspection 初始化完成"
    info "提示: 两个系统（$DRONE_PORT 和 $WAREHOUSE_PORT）共用此数据库，数据实时同步"
}

config_pip_mirror() {
    echo -e "${BOLD}配置 PiP 镜像源${NC}"
    echo ""
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "清华源(推荐)" \
        "阿里云源" \
        "官方PyPI" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "清华源(推荐)")  export PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"; ok "已设置为清华源" ;;
        "阿里云源")      export PIP_MIRROR="https://mirrors.aliyun.com/pypi/simple/"; ok "已设置为阿里云源" ;;
        "官方PyPI")      unset PIP_MIRROR; ok "已设置为官方源" ;;
        "返回")          ;;
    esac
}

# ═══════════════════════════════════════════
#  7. RFID 串口设备管理
# ═══════════════════════════════════════════
check_rfid_permissions() {
    local device="$1" auto_fix="${2:-false}"

    if [ -n "$device" ] && [ -e "$device" ]; then
        if [ -r "$device" ] && [ -w "$device" ]; then
            ok "设备权限正常: $device (可读写)"
        else
            warn "设备权限不足: $device"
            if sudo -n true 2>/dev/null; then
                if sudo chmod 666 "$device" 2>/dev/null; then
                    ok "权限已自动修复: $device"
                else
                    warn "自动修复失败，请手动执行: sudo chmod 666 $device"
                fi
            elif [ "$auto_fix" = "true" ]; then
                warn "无 sudo 权限，请手动执行: sudo chmod 666 $device"
            fi
        fi
    fi

    if [ "$(uname -s)" = "Linux" ]; then
        if groups "$USER" 2>/dev/null | grep -q dialout; then
            ok "用户已在 dialout 组"
        else
            warn "用户不在 dialout 组"
            if sudo -n true 2>/dev/null; then
                if sudo usermod -aG dialout "$USER" 2>/dev/null; then
                    ok "已将用户加入 dialout 组 (重新登录后生效)"
                fi
            elif [ "$auto_fix" = "true" ]; then
                warn "无 sudo 权限，请手动执行: sudo usermod -aG dialout \$USER"
            fi
        fi
    fi

    if command -v docker &>/dev/null; then
        if groups "$USER" 2>/dev/null | grep -q docker; then
            ok "用户已在 docker 组"
        else
            warn "用户不在 docker 组"
            if sudo -n true 2>/dev/null; then
                sudo usermod -aG docker "$USER" 2>/dev/null && ok "已将用户加入 docker 组 (重新登录后生效)"
            fi
        fi
    fi
}

setup_rfid_permissions() {
    echo -e "${BOLD}配置 RFID 串口权限${NC}"
    echo ""

    local detected=""
    for dev in /dev/ttyUSB* /dev/ttyACM*; do
        [ -e "$dev" ] && detected="$dev" && break
    done

    if [ -n "$detected" ]; then
        ok "检测到串口设备: $detected"
        check_rfid_permissions "$detected" false
    else
        info "未检测到 RFID 串口设备，跳过权限配置"
        echo "  连接设备后请手动执行:"
        echo "    sudo chmod 666 /dev/ttyUSB0"
        echo "    sudo usermod -aG dialout \$USER"
    fi
}

detect_rfid_device() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    检测 RFID 串口设备${NC}"
    echo -e "${CYAN}========================================${NC}"

    local detected=""

    if [ -n "${RFID_DEVICE:-}" ] && [ -e "$RFID_DEVICE" ]; then
        ok "RFID 设备已配置且存在: $RFID_DEVICE"
        return 0
    elif [ -n "${RFID_DEVICE:-}" ]; then
        warn "RFID_DEVICE 指向的路径不存在: $RFID_DEVICE"
    fi

    local candidates=()
    for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
        [ -e "$dev" ] && candidates+=("$dev")
    done

    if [ ${#candidates[@]} -eq 0 ]; then
        warn "未检测到任何串口设备"
        return 0
    fi

    echo ""
    echo "  检测到以下串口设备:"
    for dev in "${candidates[@]}"; do echo "    $dev"; done
    echo ""

    for dev in "${candidates[@]}"; do
        if [[ "$dev" =~ /dev/ttyUSB|/dev/ttyACM ]]; then
            detected="$dev"; break
        fi
    done
    [ -z "$detected" ] && detected="${candidates[0]}"

    if [ -n "$detected" ]; then
        ok "自动选择 RFID 设备: $detected"
        export RFID_DEVICE="$detected"
        local env_file="$SCRIPT_DIR/station/warehouse-inspection-system/.env"
        if [ -f "$env_file" ]; then
            if grep -q "^RFID_DEVICE=" "$env_file"; then
                sed -i "s|^RFID_DEVICE=.*|RFID_DEVICE=$detected|" "$env_file"
            else
                echo "RFID_DEVICE=$detected" >> "$env_file"
            fi
            ok "已写入 .env: RFID_DEVICE=$detected"
        fi
        check_rfid_permissions "$detected" true
    fi
    return 0
}

# ═══════════════════════════════════════════
#  8. 基础设施 (PostgreSQL + Redis)
# ═══════════════════════════════════════════
start_infra() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    启动基础设施 (PostgreSQL + Redis)${NC}"
    echo -e "${CYAN}========================================${NC}"

    # ── PostgreSQL 启动 ──
    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        ok "本地 PostgreSQL 已运行"
        # 诊断认证状态
        diagnose_postgres_auth "$PG_PORT" || {
            warn "PostgreSQL 认证失败，尝试降级方案..."
            # 检测是否有 sudo 权限
            if sudo -n true 2>/dev/null; then
                info "有 sudo 权限，尝试修复认证..."
                sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';" 2>/dev/null || warn "密码修改失败"
                sudo sed -i 's|ident|md5|' /etc/postgresql/*/main/pg_hba.conf 2>/dev/null || warn "pg_hba.conf 修改失败"
                sudo service postgresql restart 2>/dev/null
                sleep 2
                diagnose_postgres_auth "$PG_PORT" && ok "认证修复成功"
            else
                warn "无 sudo 权限，启用自建 PostgreSQL 实例..."
                fix_postgres_no_sudo "5433" || {
                    error "自建 PostgreSQL 失败，需手动配置"
                    return 1
                }
            fi
        }
    elif check_docker_port "$PG_PORT"; then
        ok "Docker PostgreSQL 已运行"
    else
        info "启动 Docker PostgreSQL + Redis..."
        if ! docker compose up -d postgres redis 2>&1; then
            error "Docker 启动失败，尝试使用本地服务..."
            if command -v pg_isready &>/dev/null; then
                sudo service postgresql start 2>/dev/null || true
                sleep 2
                if pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
                    ok "本地 PostgreSQL 已启动"
                    # 诊断认证
                    diagnose_postgres_auth "$PG_PORT" || fix_postgres_no_sudo "5433"
                else
                    # 无 PostgreSQL 或无法启动，尝试自建
                    warn "PostgreSQL 无法启动，尝试自建实例..."
                    fix_postgres_no_sudo "5433" || {
                        error "PostgreSQL 最终无法可用"
                        return 1
                    }
                fi
            else
                warn "PostgreSQL 未安装，尝试自建实例..."
                fix_postgres_no_sudo "5433" || {
                    error "PostgreSQL 最终无法可用"
                    return 1
                }
            fi
        else
            check_service_ready "PostgreSQL" "$PG_PORT" 15 || {
                warn "Docker PostgreSQL 未就绪，尝试自建..."
                fix_postgres_no_sudo "5433"
            }
            check_service_ready "Redis" "$REDIS_PORT" 10 || warn "Redis 未就绪 (可选)"
        fi
    fi

    # ── Redis 启动 ──
    diagnose_redis || {
        warn "Redis 未运行，尝试启动..."
        # 尝试 Docker
        docker compose up -d redis 2>&1 || {
            # 尝试本地服务
            sudo service redis-server start 2>/dev/null || {
                # 尝试手动启动
                redis-server --daemonize yes 2>/dev/null || warn "Redis 启动失败，部分功能可能受限"
            }
        }
        sleep 2
        diagnose_redis && ok "Redis 已修复" || warn "Redis 最终未启动 (可选)"
    }
}

# ═══════════════════════════════════════════
#  9. 虚拟环境管理
# ═══════════════════════════════════════════
get_venv() {
    local dir="$1" abs
    abs="$(abs_path "$dir")"
    [ -n "$abs" ] && [ -d "$abs/venv" ] && echo "$abs/venv" && return
    if [ -n "$VENV_DIR" ]; then
        [ -d "$VENV_DIR/$(basename "$abs")" ] && echo "$VENV_DIR/$(basename "$abs")"
    fi
}

setup_venv() {
    local dir="$1" req_file="$2"
    local abs_dir="$(abs_path "$dir")"
    [ -z "$abs_dir" ] && { error "目录不存在: $dir"; return 1; }

    local venv_dir
    if [ -n "$VENV_DIR" ]; then
        venv_dir="$VENV_DIR/$(basename "$abs_dir")"
    else
        venv_dir="$abs_dir/venv"
    fi

    # ── 创建虚拟环境 ──
    if [ ! -d "$venv_dir" ]; then
        info "创建虚拟环境 ($dir)..."
        python3 -m venv "$venv_dir" 2>&1
        
        # 检测 venv 创建是否成功，失败时诊断 ensurepip
        if [ ! -d "$venv_dir" ] || [ ! -f "$venv_dir/bin/python3" ]; then
            warn "venv 创建失败，诊断 ensurepip..."
            diagnose_ensurepip "$venv_dir"
            
            # 尝试降级方案: 手动创建 venv 结构并安装 pip
            info "尝试手动创建最小 venv 结构..."
            mkdir -p "$venv_dir/bin" "$venv_dir/lib"
            # 复制系统 python
            cp "$(which python3)" "$venv_dir/bin/python3" 2>/dev/null || \
                ln -sf "$(which python3)" "$venv_dir/bin/python3" 2>/dev/null
            
            # 尝试安装 pip
            fix_ensurepip_fallback "$venv_dir" || warn "pip 安装失败，依赖安装可能失败"
        fi
    fi

    # ── 检测 pip 是否存在 ──
    diagnose_pip_in_venv "$venv_dir" || {
        warn "pip 缺失，尝试修复..."
        fix_ensurepip_fallback "$venv_dir"
    }

    # ── 安装依赖 ──
    if [ -f "$abs_dir/$req_file" ]; then
        info "安装依赖 ($dir/$req_file)..."
        
        local pip_bin="$venv_dir/bin/pip"
        [ ! -f "$pip_bin" ] && pip_bin="$venv_dir/bin/pip3"
        
        # 检测网络
        diagnose_network
        
        # 执行 pip install，捕获错误日志
        local install_log
        install_log=$(mktemp)
        "$pip_bin" install $PIP_EXTRA -r "$abs_dir/$req_file" 2>&1 | tee "$install_log"
        local install_status=${PIPESTATUS[0]}
        
        if [ $install_status -ne 0 ]; then
            warn "pip install 失败，诊断版本冲突..."
            diagnose_pip_version_conflict "$(cat "$install_log")"
            
            # 尝试自动修复常见版本冲突
            if grep -qiE "numpy.*2\.|opencv" "$install_log"; then
                info "尝试自动修复 numpy/opencv 版本冲突..."
                fix_pip_numpy_opencv_conflict "$venv_dir"
                # 重新安装依赖
                info "重新安装依赖..."
                "$pip_bin" install $PIP_EXTRA -r "$abs_dir/$req_file" || {
                    error "依赖安装最终失败，请查看上述诊断信息手动处理"
                    rm -f "$install_log"
                    return 1
                }
            else
                rm -f "$install_log"
                return 1
            fi
        fi
        
        rm -f "$install_log"
        ok "依赖安装完成"
    fi
    return 0
}

# ═══════════════════════════════════════════
#  10. 后端服务管理
# ═══════════════════════════════════════════
start_backend_bg() {
    local name="$1" dir="$2" module="$3" port="$4" req_file="${5:-requirements.txt}"
    local log_file="$SCRIPT_DIR/app/logs/${name}.log"
    local abs_dir="$(abs_path "$dir")"
    local venv_dir

    if [ -n "$VENV_DIR" ]; then
        venv_dir="$VENV_DIR/$(basename "$abs_dir")"
    else
        venv_dir="$abs_dir/venv"
    fi

    mkdir -p "$SCRIPT_DIR/app/logs"

    # 检查 Docker 是否占用
    if check_docker_port "$port"; then
        warn "端口 $port 已被 Docker 占用，跳过 ${name}"
        return 1
    fi

    # 释放旧进程
    if check_port "$port"; then
        release_port "$port" "$name"
    fi

    # ── 设置虚拟环境（内部已集成版本冲突诊断）──
    setup_venv "$dir" "$req_file" || {
        error "${name} 虚拟环境设置失败"
        return 1
    }

    info "启动 ${name} (端口 $port)..."
    cd "$abs_dir" && nohup "$venv_dir/bin/uvicorn" "$module" --host 0.0.0.0 --port "$port" > "$log_file" 2>&1 &
    cd "$SCRIPT_DIR"
    local pid=$!
    echo "$pid" > "$SCRIPT_DIR/app/logs/${name}.pid"
    debug "PID: $pid"

    sleep 4
    if kill -0 "$pid" 2>/dev/null; then
        ok "${name} 启动成功 (PID: $pid, 端口: $port)"
    else
        error "${name} 启动失败"
        error "=== 日志 (最后 20 行) ==="
        [ -f "$log_file" ] && tail -20 "$log_file"
        error "==========================="
        
        # ── 诊断启动失败原因 ──
        echo ""
        info "诊断启动失败原因..."
        local log_content
        log_content=$(cat "$log_file" 2>/dev/null)
        
        # 检测模块导入错误
        if echo "$log_content" | grep -qiE "ModuleNotFoundError|ImportError|No module named"; then
            warn "检测到模块导入错误"
            echo ""
            echo "  ${CYAN}问题说明:${NC} Python 包缺失或路径配置错误"
            echo ""
            echo "  ${CYAN}解决方案:${NC}"
            echo "  1) 检查 venv 是否正确激活:"
            echo "     source $venv_dir/bin/activate"
            echo ""
            echo "  2) 查看缺失的模块名 (从日志中确认)，手动安装:"
            echo "     $venv_dir/bin/pip install <模块名>"
            echo ""
            echo "  3) 若是项目模块缺失，检查 PYTHONPATH:"
            echo "     export PYTHONPATH=$abs_dir/src:\$PYTHONPATH"
            echo ""
        fi
        
        # 检测数据库连接错误
        if echo "$log_content" | grep -qiE "PostgreSQL|connection refused|password authentication|FATAL.*postgres"; then
            warn "检测到数据库连接错误"
            diagnose_postgres_auth "$PG_PORT"
        fi
        
        # 检测 Redis 连接错误
        if echo "$log_content" | grep -qiE "Redis|ConnectionError|redis.*refused"; then
            warn "检测到 Redis 连接错误"
            diagnose_redis
        fi
        
        # 检测端口占用
        if echo "$log_content" | grep -qiE "Address already in use|port.*occupied"; then
            warn "检测到端口占用错误"
            echo ""
            echo "  ${CYAN}解决方案:${NC}"
            echo "  释放端口: $SCRIPT_DIR/启动.sh stop"
            echo "  或手动: pkill -f 'uvicorn.*:$port'"
            echo ""
        fi
        
        return 1
    fi
}

stop_service_by_port() {
    local name="$1" port="$2"
    local pid_file="$SCRIPT_DIR/app/logs/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 0.3
        fi
        rm -f "$pid_file"
    fi
    release_port "$port" "$name" >/dev/null 2>&1
}

stop_all() {
    info "停止所有服务..."
    release_port "$DRONE_PORT" "无人机数据系统" >/dev/null 2>&1
    release_port "$WAREHOUSE_PORT" "仓库巡检系统" >/dev/null 2>&1
    release_port "$GATEWAY_PORT" "API网关" >/dev/null 2>&1
    pkill -f "uvicorn" 2>/dev/null || true
    pkill -f "electron" 2>/dev/null || true
    pkill -f "http.server" 2>/dev/null || true
    sleep 0.5
    rm -f "$SCRIPT_DIR/app/logs/"*.pid 2>/dev/null
    ok "所有服务已停止"
}

# ═══════════════════════════════════════════
#  前端 HTTP 服务器
# ═══════════════════════════════════════════
start_http_server() {
    local port="${HTTP_PORT:-3000}"

    # 检查端口是否被占用
    if check_port "$port"; then
        warn "端口 $port 已被占用，尝试释放..."
        release_port "$port" "前端HTTP服务器" || { warn "无法释放端口 $port"; return 1; }
    fi

    info "启动前端 HTTP 服务器 (端口 $port)..."
    cd "$SCRIPT_DIR" && nohup python3 -m http.server "$port" --bind 0.0.0.0 > "$SCRIPT_DIR/app/logs/前端HTTP服务器.log" 2>&1 &
    cd "$SCRIPT_DIR"
    local pid=$!
    echo "$pid" > "$SCRIPT_DIR/app/logs/前端HTTP服务器.pid"
    sleep 2

    if check_port "$port"; then
        ok "前端 HTTP 服务器启动成功 (PID: $pid, 端口: $port)"
        # 获取本机 IP
        local ip=$(hostname -I | awk '{print $1}')
        echo ""
        echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
        echo -e "${BOLD}${GREEN}  前端访问地址${NC}"
        echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
        echo ""
        echo -e "  ${CYAN}本机访问:${NC}"
        echo -e "    http://localhost:$port/app/index.html"
        echo ""
        echo -e "  ${CYAN}局域网访问 (其他电脑):${NC}"
        echo -e "    http://$ip:$port/app/index.html"
        echo ""
        echo -e "  ${CYAN}直接进入子系统:${NC}"
        echo -e "    http://localhost:$port/station/warehouse-inspection-system/frontend/index.html"
        echo -e "    http://localhost:$port/drone/drone-db-prototype/frontend/src/index.html"
        echo ""
    else
        error "前端 HTTP 服务器启动失败"
        return 1
    fi
}

check_all_status() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}         服务状态总览${NC}"
    echo -e "${CYAN}========================================${NC}"

    local all_ok=true

    # ── 基础设施 ──
    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        echo -e "  PostgreSQL      ${GREEN}[运行中]${NC}  端口 $PG_PORT"
    elif check_docker_port "$PG_PORT"; then
        echo -e "  PostgreSQL      ${GREEN}[Docker]${NC}   端口 $PG_PORT"
    else
        echo -e "  PostgreSQL      ${RED}[已停止]${NC}"
        all_ok=false
    fi

    if command -v redis-cli &>/dev/null && redis-cli ping 2>/dev/null | grep -q PONG; then
        echo -e "  Redis           ${GREEN}[运行中]${NC}  端口 $REDIS_PORT"
    elif check_docker_port "$REDIS_PORT"; then
        echo -e "  Redis           ${GREEN}[Docker]${NC}   端口 $REDIS_PORT"
    else
        echo -e "  Redis           ${YELLOW}[未运行]${NC}  (可选)"
    fi

    # ── 后端服务 ──
    local drone_ok=false warehouse_ok=false
    for svc in "无人机数据系统:${DRONE_PORT}" "仓库巡检系统:${WAREHOUSE_PORT}" "API网关:${GATEWAY_PORT}"; do
        local name="${svc%%:*}" port="${svc##*:}"
        if check_port "$port"; then
            echo -e "  ${name}    ${GREEN}[运行中]${NC}  端口 $port"
            [[ "$name" == "无人机数据系统" ]] && drone_ok=true
            [[ "$name" == "仓库巡检系统" ]] && warehouse_ok=true
        elif check_docker_port "$port"; then
            echo -e "  ${name}    ${GREEN}[Docker]${NC}   端口 $port"
            [[ "$name" == "无人机数据系统" ]] && drone_ok=true
            [[ "$name" == "仓库巡检系统" ]] && warehouse_ok=true
        else
            echo -e "  ${name}    ${RED}[已停止]${NC}"
            all_ok=false
        fi
    done

    # ── 硬件模块 ──
    if ping -c 1 -W 1 192.168.1.200 &>/dev/null; then
        echo -e "  图传模块(200)   ${GREEN}[在线]${NC}"
    else
        echo -e "  图传模块(200)   ${RED}[离线]${NC}"
    fi

    # ── 前端 HTTP 服务器 ──
    echo ""
    echo -e "${CYAN}── 前端服务 ──${NC}"
    if check_port "$HTTP_PORT"; then
        echo -e "  HTTP服务器      ${GREEN}[运行中]${NC}  端口 $HTTP_PORT"
    else
        echo -e "  HTTP服务器      ${RED}[已停止]${NC}"
    fi
    
    local index_page="$SCRIPT_DIR/app/index.html"
    local warehouse_frontend="$SCRIPT_DIR/station/warehouse-inspection-system/frontend/index.html"
    local drone_frontend="$SCRIPT_DIR/drone/drone-db-prototype/frontend/src/index.html"
    
    [ -f "$index_page" ] && echo -e "  系统选择页      ${GREEN}[可用]${NC}" || echo -e "  系统选择页      ${RED}[缺失]${NC}"
    [ -f "$warehouse_frontend" ] && echo -e "  仓库系统前端    ${GREEN}[可用]${NC}" || echo -e "  仓库系统前端    ${RED}[缺失]${NC}"
    [ -f "$drone_frontend" ] && echo -e "  无人机系统前端  ${GREEN}[可用]${NC}" || echo -e "  无人机系统前端  ${RED}[缺失]${NC}"

    echo ""
    $all_ok && ok "所有核心服务运行正常" || warn "部分服务未运行"
    
    # ── 访问指引 ──
    if $drone_ok || $warehouse_ok; then
        local ip=$(hostname -I | awk '{print $1}')
        echo ""
        echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
        echo -e "${BOLD}${GREEN}  系统访问方式${NC}"
        echo -e "${BOLD}${GREEN}════════════════════════════════════════${NC}"
        echo ""
        if check_port "$HTTP_PORT"; then
            echo -e "  ${CYAN}本机浏览器:${NC}"
            echo -e "    http://localhost:$HTTP_PORT/app/index.html"
            echo ""
            echo -e "  ${CYAN}局域网访问 (其他电脑):${NC}"
            echo -e "    http://$ip:$HTTP_PORT/app/index.html"
            echo ""
        else
            echo -e "  ${CYAN}本地文件:${NC}"
            echo -e "    file://$SCRIPT_DIR/app/index.html"
            echo ""
            echo -e "  ${YELLOW}提示: 启动 HTTP 服务器后可通过浏览器访问${NC}"
            echo -e "    运行: python3 -m http.server $HTTP_PORT --bind 0.0.0.0"
            echo ""
        fi
    fi
    
    return 0
}

# ═══════════════════════════════════════════
#  11. 守护进程
# ═══════════════════════════════════════════
auto_restart_monitor() {
    local name="$1" port="$2" module="$3" dir="$4" req_file="${5:-requirements.txt}"
    local pid_file="$SCRIPT_DIR/app/logs/${name}.pid"

    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            warn "${name} 进程已崩溃 (PID: $pid)，尝试重启..."
            rm -f "$pid_file"
            start_backend_bg "$name" "$dir" "$module" "$port" "$req_file" && \
                ok "${name} 自动重启成功" || error "${name} 自动重启失败"
        fi
    fi

    if ! check_port "$port"; then
        warn "${name} 端口 $port 无响应，尝试重启..."
        start_backend_bg "$name" "$dir" "$module" "$port" "$req_file" && \
            ok "${name} 自动重启成功" || error "${name} 自动重启失败"
    fi
}

start_daemon() {
    info "启动自动重启守护进程 (PID: $$)"
    local count=0
    while true; do
        sleep 15
        count=$((count + 1))
        auto_restart_monitor "仓库巡检系统" "$WAREHOUSE_PORT" "src.main:app" "station/warehouse-inspection-system/backend"
        auto_restart_monitor "无人机数据系统" "$DRONE_PORT" "app.main:app" "drone/drone-db-prototype/backend"
        auto_restart_monitor "API网关" "$GATEWAY_PORT" "main:app" "app/api-gateway"
        if [ $((count % 20)) -eq 0 ]; then
            rotate_app/logs
        fi
    done
}

# ═══════════════════════════════════════════
#  12. 日志管理
# ═══════════════════════════════════════════
rotate_app/logs() {
    local log_dir="$SCRIPT_DIR/app/logs"
    [ ! -d "$log_dir" ] && return 0

    for log_file in "$log_dir"/*.log; do
        [ ! -f "$log_file" ] && continue
        local size
        size=$(stat -c%s "$log_file" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            local base="$(basename "$log_file" .log)"
            local date_stamp="$(date +%Y%m%d_%H%M%S)"
            cp "$log_file" "$log_dir/${base}_${date_stamp}.log"
            : > "$log_file"
            info "日志已轮转: ${base}.log (${size} bytes → ${base}_${date_stamp}.log)"

            local count=0
            for old in $(ls -t "$log_dir/${base}_"*.log 2>/dev/null); do
                count=$((count + 1))
                [ $count -gt "$MAX_LOG_FILES" ] && rm -f "$old"
            done
        fi
    done
}

view_app/logs() {
    echo -e "${BOLD}查看日志${NC}"
    echo ""
    echo "输入要查看的行数 (默认50):"
    read -r lines
    lines="${lines:-50}"
    if [ -d "$SCRIPT_DIR/app/logs" ]; then
        tail -"$lines" "$SCRIPT_DIR/app/logs/"*.log 2>/dev/null || warn "无日志文件"
    else
        warn "app/logs 目录不存在"
    fi
}

# ═══════════════════════════════════════════
#  13. 一键启动（核心流程）
# ═══════════════════════════════════════════
start_all() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║     域感智能 - 一键启动             ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"

    # ── 阶段 0: 前置检查 ──
    phase "0/4" "前置检查"
    if ! command -v python3 &>/dev/null; then
        error "Python3 未安装，无法启动服务"; return 1
    fi
    ok "Python3: $(python3 --version 2>&1)"
    if ! command -v docker &>/dev/null; then
        warn "Docker 未安装，基础设施可能需要手动启动"
    fi
    ok "前置检查通过"

    # ── 阶段 1: 启动基础设施 ──
    phase "1/4" "启动基础设施 (PostgreSQL + Redis)"
    start_infra || { error "基础设施启动失败，请检查 Docker 或本地 PostgreSQL"; return 1; }

    # ── 阶段 2: RFID 设备检测 ──
    phase "2/4" "RFID 设备检测"
    detect_rfid_device

    # ── 阶段 3: 启动后端服务 ──
    phase "3/4" "启动后端服务"
    local failed=0

    echo ""
    echo -e "${CYAN}--- 仓库巡检系统 (先启动以创建数据库表结构) ---${NC}"
    start_backend_bg "仓库巡检系统" "station/warehouse-inspection-system/backend" "src.main:app" "$WAREHOUSE_PORT" || failed=$((failed + 1))

    echo ""
    echo -e "${CYAN}--- 无人机数据系统 (共用 PostgreSQL 数据库) ---${NC}"
    start_backend_bg "无人机数据系统" "drone/drone-db-prototype/backend" "app.main:app" "$DRONE_PORT" || failed=$((failed + 1))

    echo ""
    echo -e "${CYAN}--- API 网关 ---${NC}"
    start_backend_bg "API网关" "app/api-gateway" "main:app" "$GATEWAY_PORT" || failed=$((failed + 1))

    # ── 阶段 4: 启动前端 HTTP 服务器 ──
    phase "4/5" "启动前端 HTTP 服务器"
    start_http_server || warn "前端 HTTP 服务器启动失败（可手动启动）"

    # ── 阶段 5: 状态汇总 ──
    phase "5/5" "状态汇总"
    check_all_status

    if [ $failed -gt 0 ]; then
        warn "$failed 个服务启动失败，请查看日志: $SCRIPT_DIR/app/logs/"
        return 1
    fi
    ok "一键启动完成"
    return 0
}

# ═══════════════════════════════════════════
#  14. 快速部署
# ═══════════════════════════════════════════
quick_deploy() {
    echo -e "${BOLD}快速部署（全自动）${NC}"
    echo ""
    if ! confirm "将检测环境、安装依赖、初始化数据库、配置RFID权限。继续？"; then
        warn "已取消"; return
    fi
    check_environment
    echo ""
    install_dependencies
    echo ""
    init_database
    echo ""
    setup_rfid_permissions
    echo ""
    ok "快速部署完成"
}

# ═══════════════════════════════════════════
#  15. 功能测试
# ═══════════════════════════════════════════
run_drone_simulator() {
    echo -e "${BOLD}运行无人机模拟器${NC}"
    echo ""
    local sim_dir="$SCRIPT_DIR/station/warehouse-inspection-system/tools"
    if [ -f "$sim_dir/simulate_drone.py" ]; then
        info "启动模拟器..."
        cd "$sim_dir" && python3 simulate_drone.py
    else
        error "模拟器脚本不存在: $sim_dir/simulate_drone.py"
    fi
}

test_rfid() {
    echo -e "${BOLD}测试 RFID 读卡器${NC}"
    echo ""
    if ! command -v python3 &>/dev/null; then
        error "Python3 未安装"; return
    fi

    echo -e "${CYAN}--- 串口诊断 ---${NC}"
    if [ -d /dev ]; then
        echo "可用串口设备:"
        ls -la /dev/ttyUSB* /dev/ttyACM* /dev/ttyS* 2>/dev/null || echo "  未找到 USB/ACM/COM 映射串口"
        echo ""
        echo "用户组:"
        groups
        echo ""
    fi

    echo -e "${CYAN}--- RFID 测试 ---${NC}"
    info "尝试连接 RFID 读卡器..."
    python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/station/warehouse-inspection-system/backend/src')
try:
    from hardware.rfid_reader import RFIDReader, get_rfid_reader
    from hardware.serial import list_available_ports
    print(f'可用串口: {list_available_ports()}')
    reader = get_rfid_reader()
    print(f'尝试连接...')
    if reader.connect():
        print('RFID 连接成功')
        print(f'端口: {reader._auto_detected_port}')
        tag = reader.read_single_tag(timeout=3.0)
        if tag:
            print(f'读取到标签: {tag.tag_id}')
        else:
            print('未读取到标签（请将标签放在读卡器附近）')
        reader.disconnect()
    else:
        print('RFID 连接失败')
        print()
        print('建议:')
        print('1. 确认 RFID 设备已连接')
        print('2. WSL 中 COM7 映射为 /dev/ttyS6')
        print('3. 尝试: ls -la /dev/ttyS6')
        print('4. 可能需要: sudo chmod 666 /dev/ttyS6')
except Exception as e:
    print(f'错误: {e}')
    import traceback
    traceback.print_exc()
"
}

test_qr() {
    echo -e "${BOLD}测试 QR 码识别${NC}"
    echo ""
    if [ -f "$SCRIPT_DIR/station/warehouse-inspection-system/backend/src/image/qr_worker.py" ]; then
        info "QR 模块存在，检查依赖..."
        python3 -c "
try:
    from pyzbar import pyzbar
    print('pyzbar: 可用')
except ImportError:
    print('pyzbar: 不可用，需安装 libzbar0')
    print('安装命令: sudo apt install libzbar0')
"
    else
        error "QR 模块不存在"
    fi
}

test_api_connectivity() {
    echo -e "${BOLD}API 连通性测试${NC}"
    echo ""

    local targets=(
        "无人机数据系统|http://localhost:$DRONE_PORT/health"
        "仓库巡检系统|http://localhost:$WAREHOUSE_PORT/health"
        "API网关|http://localhost:$GATEWAY_PORT/health"
        "看板API|http://localhost:$WAREHOUSE_PORT/api/v1/dashboard/overview"
    )

    for entry in "${targets[@]}"; do
        local name="${entry%%|*}" url="${entry#*|}"
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 "$url" 2>/dev/null)
        if [ "$http_code" = "200" ]; then
            ok "$name ($url) -> $http_code"
        elif [ -z "$http_code" ] || [ "$http_code" = "000" ]; then
            error "$name ($url) -> 无法连接"
        else
            warn "$name ($url) -> $http_code"
        fi
    done
}

test_database() {
    echo -e "${BOLD}数据库连通性测试${NC}"
    echo ""
    echo -e "${CYAN}连接目标: warehouse_inspection (两个系统共用)${NC}"
    echo ""
    if command -v pg_isready &>/dev/null; then
        if pg_isready -h localhost -p "$PG_PORT"; then
            ok "PostgreSQL (warehouse_inspection): 连接正常"
        else
            error "PostgreSQL: 连接失败"
        fi
    else
        error "pg_isready 未找到"
    fi

    if command -v redis-cli &>/dev/null; then
        if redis-cli ping 2>/dev/null | grep -q PONG; then
            ok "Redis: 连接正常"
        else
            warn "Redis: 连接失败"
        fi
    else
        warn "redis-cli 未找到"
    fi
}

# ═══════════════════════════════════════════
#  16. 数据库管理
# ═══════════════════════════════════════════
db_start_pg() {
    info "启动 PostgreSQL..."
    if sudo service postgresql start 2>/dev/null; then
        ok "PostgreSQL 已启动"
    else
        sudo pg_ctlcluster $(pg_lsclusters -h 2>/dev/null | head -1 | awk '{print $1, $2}') start 2>/dev/null && ok "PostgreSQL 已启动" || error "启动失败"
    fi
}

db_stop_pg() {
    if ! confirm "确定要停止 PostgreSQL 吗？"; then
        warn "已取消"; return
    fi
    info "停止 PostgreSQL..."
    if sudo service postgresql stop 2>/dev/null; then
        ok "PostgreSQL 已停止"
    else
        sudo pg_ctlcluster $(pg_lsclusters -h 2>/dev/null | head -1 | awk '{print $1, $2}') stop 2>/dev/null && ok "PostgreSQL 已停止" || error "停止失败"
    fi
}

db_restart_pg() {
    info "重启 PostgreSQL..."
    if sudo service postgresql restart 2>/dev/null; then
        ok "PostgreSQL 已重启"
    else
        sudo pg_ctlcluster $(pg_lsclusters -h 2>/dev/null | head -1 | awk '{print $1, $2}') restart 2>/dev/null && ok "PostgreSQL 已重启" || error "重启失败"
    fi
}

db_start_redis() {
    info "启动 Redis..."
    if sudo service redis-server start 2>/dev/null; then
        ok "Redis 已启动"
    else
        sudo redis-server --daemonize yes 2>/dev/null && ok "Redis 已启动" || error "启动失败"
    fi
}

db_stop_redis() {
    if ! confirm "确定要停止 Redis 吗？"; then
        warn "已取消"; return
    fi
    info "停止 Redis..."
    if sudo service redis-server stop 2>/dev/null; then
        ok "Redis 已停止"
    else
        redis-cli shutdown 2>/dev/null && ok "Redis 已停止" || error "停止失败"
    fi
}

db_restart_redis() {
    info "重启 Redis..."
    sudo service redis-server restart 2>/dev/null && ok "Redis 已重启" || \
        (redis-cli shutdown 2>/dev/null; sudo redis-server --daemonize yes 2>/dev/null && ok "Redis 已重启" || error "重启失败")
}

db_shell() {
    echo -e "${BOLD}数据库 Shell${NC}"
    echo ""
    if ! pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        error "PostgreSQL 未运行，请先启动"; press_enter; return
    fi
    echo "输入数据库名称 (默认: warehouse_inspection):"
    read -r dbname
    dbname="${dbname:-warehouse_inspection}"
    echo ""
    echo -e "${CYAN}已连接到: $dbname${NC}"
    echo -e "${CYAN}可用命令:${NC}"
    echo "  \\dt          - 列出所有表"
    echo "  \\d 表名      - 查看表结构"
    echo "  SELECT ...   - 查询数据"
    echo "  \\q           - 退出"
    echo ""
    sudo -u postgres psql -d "$dbname"
}

db_list_tables() {
    echo -e "${BOLD}数据库表列表${NC}"
    echo ""
    if ! pg_isready -h localhost -p "$PG_PORT" &>/dev/null; then
        error "PostgreSQL 未运行，请先启动"; return
    fi
    local dbname="${1:-warehouse_inspection}"
    echo -e "${CYAN}--- ${dbname} (两个系统共用) ---${NC}"
    echo -e "  无人机数据系统 ($DRONE_PORT) + 仓库巡检系统 ($WAREHOUSE_PORT)"
    echo ""
    sudo -u postgres psql -d "$dbname" -c "\dt" 2>/dev/null || warn "无法连接数据库"
    echo ""
    info "提示: 使用「打开数据库Shell」功能可执行 SQL 查询"
}

# ═══════════════════════════════════════════
#  17. 系统维护
# ═══════════════════════════════════════════
clean_venvs() {
    echo -e "${BOLD}清理虚拟环境${NC}"
    echo ""
    if ! confirm "将删除所有 venv 目录，需要重新安装依赖。继续？"; then
        warn "已取消"; return
    fi
    find "$SCRIPT_DIR" -maxdepth 4 -name "venv" -type d | while read -r venv; do
        info "删除: $venv"
        rm -rf "$venv"
    done
    ok "虚拟环境清理完成"
}

clean_app/logs() {
    echo -e "${BOLD}清理日志文件${NC}"
    echo ""
    local log_dir="$SCRIPT_DIR/app/logs"
    if [ -d "$log_dir" ]; then
        local count
        count=$(find "$log_dir" -name "*.log" | wc -l)
        info "找到 $count 个日志文件"
        if confirm "确认删除？"; then
            rm -f "$log_dir/"*.log
            ok "日志清理完成"
        else
            warn "已取消"
        fi
    else
        warn "app/logs 目录不存在"
    fi
}

reset_database() {
    echo -e "${BOLD}重置数据库${NC}"
    echo ""
    warn "此操作将删除两个系统的所有数据！"
    if ! confirm "确定要重置数据库吗？此操作不可恢复！"; then
        warn "已取消"; return
    fi
    if ! confirm "再次确认：真的要删除所有数据吗？"; then
        warn "已取消"; return
    fi
    info "正在重置共享数据库..."
    sudo -u postgres psql -c "DROP DATABASE warehouse_inspection;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE warehouse_inspection OWNER postgres;" 2>/dev/null || true
    ok "数据库已重置，重启服务后会自动重新建表"
}

update_code() {
    echo ""
    echo -e "${BOLD}更新系统代码${NC}"
    echo ""

    if ! command -v git &>/dev/null; then
        error "git 未安装"; return 1
    fi
    if ! git rev-parse --is-inside-work-tree &>/dev/null; then
        warn "当前目录不是 git 仓库，跳过"; return 1
    fi

    local branch
    branch=$(git branch --show-current)
    echo -e "  仓库: ${CYAN}$(git remote get-url origin 2>/dev/null)${NC}"
    echo -e "  分支: ${CYAN}$branch${NC}"

    local has_changes=false
    if ! git diff --quiet || ! git diff --cached --quiet; then
        has_changes=true
        warn "检测到本地有未提交的更改"
        echo ""
        echo -e "  ${YELLOW}本地修改:${NC}"
        git status --short
        echo ""
        if confirm "是否暂存本地更改后继续更新? (stash)" "Y"; then
            info "暂存本地更改..."
            git stash push -m "启动.sh 自动暂存 - $(date '+%Y-%m-%d %H:%M')" 2>/dev/null
            ok "本地更改已暂存 (git stash)"
        else
            info "跳过更新"; return 0
        fi
    fi

    echo ""
    info "获取远程更新..."
    if ! git fetch origin "$branch" 2>&1; then
        error "无法连接远程仓库，请检查网络"
        [ "$has_changes" = "true" ] && { info "恢复本地更改..."; git stash pop 2>/dev/null; }
        return 1
    fi

    local local_commit remote_commit
    local_commit=$(git rev-parse HEAD)
    remote_commit=$(git rev-parse "origin/$branch" 2>/dev/null)

    if [ "$local_commit" = "$remote_commit" ]; then
        ok "已是最新版本"
        [ "$has_changes" = "true" ] && { info "恢复本地更改..."; git stash pop 2>/dev/null; }
        return 0
    fi

    echo ""
    echo -e "  ${CYAN}远程新增提交:${NC}"
    git log --oneline "HEAD..origin/$branch" 2>/dev/null | head -20
    echo ""

    if ! confirm "确认更新到最新版本?" "Y"; then
        info "已取消更新"
        [ "$has_changes" = "true" ] && { info "恢复本地更改..."; git stash pop 2>/dev/null; }
        return 0
    fi

    info "正在合并更新..."
    if git merge "origin/$branch" 2>&1; then
        ok "代码更新成功"
        echo ""
        echo -e "  ${GREEN}已更新到: $(git log --oneline -1)${NC}"
        echo ""
        if confirm "是否重启服务使更新生效?" "Y"; then
            stop_all
            sleep 2
            start_all
        fi
    else
        error "合并冲突! 请手动解决: git status"
        info "冲突文件请手动编辑后执行: git add . && git commit"
        return 1
    fi
}

check_ports() {
    echo -e "${BOLD}端口占用检查${NC}"
    echo ""
    local ports=($DRONE_PORT $WAREHOUSE_PORT $GATEWAY_PORT $PG_PORT $REDIS_PORT)
    for port in "${ports[@]}"; do
        if check_port "$port"; then
            local pid
            pid=$(get_port_pid "$port")
            warn "端口 $port: 已占用 (PID: ${pid:-未知})"
        else
            ok "端口 $port: 空闲"
        fi
    done
}

# ═══════════════════════════════════════════
#  18. 系统信息
# ═══════════════════════════════════════════
show_system_info() {
    echo -e "${BOLD}系统信息${NC}"
    echo ""

    echo -e "${CYAN}--- 系统 ---${NC}"
    echo "  主机名: $(hostname)"
    echo "  内核: $(uname -r)"
    echo "  架构: $(uname -m)"
    echo ""

    echo -e "${CYAN}--- Python ---${NC}"
    command -v python3 &>/dev/null && echo "  版本: $(python3 --version 2>&1)" || echo "  未安装"
    echo "  路径: $(which python3 2>/dev/null || echo 'N/A')"
    echo ""

    echo -e "${CYAN}--- 数据库 ---${NC}"
    if command -v psql &>/dev/null; then
        echo "  PostgreSQL: $(psql --version 2>&1)"
    else
        echo "  PostgreSQL: 未安装"
    fi
    pg_isready -h localhost -p "$PG_PORT" &>/dev/null && echo "  状态: 运行中" || echo "  状态: 已停止"
    echo ""

    echo -e "${CYAN}--- Docker ---${NC}"
    if command -v docker &>/dev/null; then
        echo "  版本: $(docker --version 2>&1)"
        if docker ps &>/dev/null 2>&1; then
            echo "  守护进程: 运行中"
            echo "  容器数量: $(docker ps -q 2>/dev/null | wc -l)"
        else
            echo "  守护进程: 已停止"
        fi
        if docker compose version &>/dev/null 2>&1; then
            echo "  Compose: $(docker compose version 2>&1 | head -1)"
        elif command -v docker-compose &>/dev/null; then
            echo "  Compose: $(docker-compose --version 2>&1)"
        fi
    else
        echo "  未安装"
    fi
    echo ""

    echo -e "${CYAN}--- 磁盘使用 ---${NC}"
    df -h "$SCRIPT_DIR" 2>/dev/null | tail -1 | awk '{printf "  总空间: %s  已用: %s  可用: %s (%s)\n", $2, $3, $4, $5}'
    echo ""

    echo -e "${CYAN}--- 服务端口 ---${NC}"
    for port in $DRONE_PORT $WAREHOUSE_PORT $GATEWAY_PORT $PG_PORT $REDIS_PORT; do
        if check_port "$port"; then
            echo "  端口 $port: 使用中"
        else
            echo "  端口 $port: 空闲"
        fi
    done
}

# ═══════════════════════════════════════════
#  19. 服务管理子菜单
# ═══════════════════════════════════════════
start_single_service() {
    echo -e "${BOLD}启动单个服务${NC}"
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "无人机数据系统($DRONE_PORT)" \
        "仓库巡检系统($WAREHOUSE_PORT)" \
        "API网关($GATEWAY_PORT)" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "无人机数据系统($DRONE_PORT)")
            start_backend_bg "无人机数据系统" "drone/drone-db-prototype/backend" "app.main:app" "$DRONE_PORT" ;;
        "仓库巡检系统($WAREHOUSE_PORT)")
            start_backend_bg "仓库巡检系统" "station/warehouse-inspection-system/backend" "src.main:app" "$WAREHOUSE_PORT" ;;
        "API网关($GATEWAY_PORT)")
            start_backend_bg "API网关" "app/api-gateway" "main:app" "$GATEWAY_PORT" ;;
        "返回") ;;
    esac
}

stop_single_service() {
    echo -e "${BOLD}停止单个服务${NC}"
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "无人机数据系统($DRONE_PORT)" \
        "仓库巡检系统($WAREHOUSE_PORT)" \
        "API网关($GATEWAY_PORT)" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "无人机数据系统($DRONE_PORT)")
            stop_service_by_port "无人机数据系统" "$DRONE_PORT"
            ok "无人机数据系统 已停止" ;;
        "仓库巡检系统($WAREHOUSE_PORT)")
            stop_service_by_port "仓库巡检系统" "$WAREHOUSE_PORT"
            ok "仓库巡检系统 已停止" ;;
        "API网关($GATEWAY_PORT)")
            stop_service_by_port "API网关" "$GATEWAY_PORT"
            ok "API网关 已停止" ;;
        "返回") ;;
    esac
}

# ═══════════════════════════════════════════
#  20. 子菜单
# ═══════════════════════════════════════════
deploy_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 环境部署${NC}"
        local opt
        opt=$(menu_select "请选择 [1-8]: " \
            "快速部署(全自动)" \
            "检测环境" \
            "安装系统依赖" \
            "初始化数据库" \
            "配置RFID串口权限" \
            "配置PiP镜像源" \
            "设置运行模式" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "快速部署(全自动)")   quick_deploy ;;
            "检测环境")           check_environment; press_enter ;;
            "安装系统依赖")       install_dependencies; press_enter ;;
            "初始化数据库")       init_database; press_enter ;;
            "配置RFID串口权限")   setup_rfid_permissions; press_enter ;;
            "配置PiP镜像源")      config_pip_mirror; press_enter ;;
            "设置运行模式")       select_mode; press_enter ;;
            "返回主菜单")         return ;;
        esac
    done
}

service_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 服务管理 (模式: $(get_mode_label))${NC}"
        local opt
        opt=$(menu_select "请选择 [1-9]: " \
            "启动所有服务" \
            "停止所有服务" \
            "重启所有服务" \
            "查看服务状态" \
            "查看日志" \
            "启动单个服务" \
            "停止单个服务" \
            "切换运行模式" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "启动所有服务")   start_all; press_enter ;;
            "停止所有服务")   stop_all; press_enter ;;
            "重启所有服务")   stop_all; sleep 2; start_all; press_enter ;;
            "查看服务状态")   check_all_status; press_enter ;;
            "查看日志")       view_app/logs; press_enter ;;
            "启动单个服务")   start_single_service; press_enter ;;
            "停止单个服务")   stop_single_service; press_enter ;;
            "切换运行模式")   select_mode; press_enter ;;
            "返回主菜单")     return ;;
        esac
    done
}

test_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 功能测试${NC}"
        local opt
        opt=$(menu_select "请选择 [1-6]: " \
            "无人机模拟器" \
            "RFID读卡器测试" \
            "QR码识别测试" \
            "API连通性测试" \
            "数据库连通性测试" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "无人机模拟器")        run_drone_simulator; press_enter ;;
            "RFID读卡器测试")      test_rfid; press_enter ;;
            "QR码识别测试")        test_qr; press_enter ;;
            "API连通性测试")       test_api_connectivity; press_enter ;;
            "数据库连通性测试")    test_database; press_enter ;;
            "返回主菜单")          return ;;
        esac
    done
}

maintenance_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 系统维护${NC}"
        local opt
        opt=$(menu_select "请选择 [1-6]: " \
            "清理虚拟环境" \
            "清理日志文件" \
            "重置数据库" \
            "更新系统代码" \
            "检查端口占用" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "清理虚拟环境")   clean_venvs; press_enter ;;
            "清理日志文件")   clean_app/logs; press_enter ;;
            "重置数据库")     reset_database; press_enter ;;
            "更新系统代码")   update_code; press_enter ;;
            "检查端口占用")   check_ports; press_enter ;;
            "返回主菜单")     return ;;
        esac
    done
}

db_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 数据库管理${NC}"
        echo ""
        if pg_isready -h localhost -p "$PG_PORT" &>/dev/null 2>&1; then
            ok "PostgreSQL: 运行中"
        else
            warn "PostgreSQL: 已停止"
        fi
        if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null 2>&1; then
            ok "Redis: 运行中"
        else
            warn "Redis: 已停止"
        fi
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-9]: " \
            "启动 PostgreSQL" \
            "停止 PostgreSQL" \
            "重启 PostgreSQL" \
            "启动 Redis" \
            "停止 Redis" \
            "重启 Redis" \
            "打开数据库Shell" \
            "查看数据库表" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "启动 PostgreSQL")    db_start_pg; press_enter ;;
            "停止 PostgreSQL")    db_stop_pg; press_enter ;;
            "重启 PostgreSQL")    db_restart_pg; press_enter ;;
            "启动 Redis")         db_start_redis; press_enter ;;
            "停止 Redis")         db_stop_redis; press_enter ;;
            "重启 Redis")         db_restart_redis; press_enter ;;
            "打开数据库Shell")    db_shell; press_enter ;;
            "查看数据库表")       db_list_tables; press_enter ;;
            "返回主菜单")         return ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  21. 主菜单
# ═══════════════════════════════════════════
show_banner() {
    local mode_label="$(get_mode_label)"
    echo ""
    echo -e "${CYAN}=============================================${NC}"
    echo -e "${CYAN}  域感智能 - 系统引导菜单${NC}"
    echo -e "${CYAN}  运行模式: [${mode_label}]${NC}"
    echo -e "${CYAN}=============================================${NC}"
}

main_menu() {
    while true; do
        show_banner
        echo ""
        echo "  1) 环境部署"
        echo "  2) 服务管理"
        echo "  3) 数据库管理"
        echo "  4) 功能测试"
        echo "  5) 系统维护"
        echo "  6) 系统信息"
        echo "  7) 退出"
        echo ""

        local opt
        opt=$(menu_select "请选择 [1-7]: " \
            "环境部署" \
            "服务管理" \
            "数据库管理" \
            "功能测试" \
            "系统维护" \
            "系统信息" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "环境部署")   deploy_menu ;;
            "服务管理")   service_menu ;;
            "数据库管理") db_menu ;;
            "功能测试")   test_menu ;;
            "系统维护")   maintenance_menu ;;
            "系统信息")   show_system_info; press_enter ;;
            "退出")       echo -e "${GREEN}再见!${NC}"; exit 0 ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  22. CLI 帮助
# ═══════════════════════════════════════════
show_help() {
    echo -e "${CYAN}域感智能 - 统一启动管理脚本${NC}"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "  (无参数)    一键启动所有服务"
    echo "  menu        交互式引导菜单"
    echo "  start       一键启动所有服务"
    echo "  status      查看服务状态"
    echo "  stop        停止所有服务"
    echo "  restart     重启所有服务"
    echo "  app/logs [n]    查看日志（最近 n 行，默认 50）"
    echo "  daemon      启动守护进程（自动重启 + 日志轮转）"
    echo "  rotate-app/logs 手动触发日志轮转"
    echo "  help        显示帮助"
    echo ""
    echo "环境变量:"
    echo "  MODE=local     全部本地运行"
    echo "  MODE=docker    全部 Docker 运行"
    echo "  MODE=hybrid    基础设施Docker+后端本地（默认）"
    echo "  VENV_DIR=~/venvs  虚拟环境存放位置（WSL加速）"
    echo "  PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple"
    echo "  MAX_LOG_SIZE=10485760  日志文件大小上限(字节,默认10MB)"
    echo "  MAX_LOG_FILES=5        保留历史日志文件数"
    echo ""
}

# ═══════════════════════════════════════════
#  23. 入口
# ═══════════════════════════════════════════
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT

case "${1:-}" in
    menu)
        main_menu
        ;;
    start|start-all)
        start_all
        ;;
    status)
        check_all_status
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    app/logs)
        if [ -d "$SCRIPT_DIR/app/logs" ]; then
            tail -"${2:-50}" "$SCRIPT_DIR/app/logs/"*.log 2>/dev/null || warn "无日志"
        else
            warn "app/logs 目录不存在"
        fi
        ;;
    daemon)
        start_daemon
        ;;
    rotate-app/logs)
        rotate_app/logs
        ;;
    help|--help|-h)
        show_help
        ;;
    "")
        start_all
        ;;
    *)
        error "未知命令: $1"
        show_help
        exit 1
        ;;
esac