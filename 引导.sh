#!/bin/bash
# ========================================
#      域感智能 - 引导菜单
# ========================================

# ── 颜色输出 ─────────────────────────────────
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE_FILE="$SCRIPT_DIR/.mode.conf"

# ── 运行模式管理 ──────────────────────────────
get_mode() {
    if [ -f "$MODE_FILE" ]; then
        source "$MODE_FILE"
    fi
    echo "${MODE:-hybrid}"
}

get_mode_label() {
    local mode="${1:-$(get_mode)}"
    case "$mode" in
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

# ── 工具函数 ──────────────────────────────────
confirm() {
    local msg="$1"
    echo -e "${YELLOW}${msg} [y/N]${NC}"
    read -r answer
    [[ "$answer" =~ ^[Yy]$ ]]
}

show_banner() {
    local mode_label="$(get_mode_label)"
    echo ""
    echo -e "${CYAN}=============================================${NC}"
    echo -e "${CYAN}  域感智能 - 系统引导菜单${NC}"
    echo -e "${CYAN}  运行模式: [${mode_label}]${NC}"
    echo -e "${CYAN}=============================================${NC}"
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
            break
        else
            error "无效选择"
            return 1
        fi
    done
}

# ── 环境部署子菜单 ────────────────────────────
deploy_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}>> 环境部署${NC}"
        local opt
        opt=$(menu_select "请选择 [1-7]: " \
            "快速部署(全自动)" \
            "检测环境" \
            "安装系统依赖" \
            "初始化数据库" \
            "配置PiP镜像源" \
            "设置运行模式" \
            "返回主菜单")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "快速部署(全自动)")   quick_deploy ;;
            "检测环境")   check_environment; press_enter ;;
            "安装系统依赖")   install_dependencies; press_enter ;;
            "初始化数据库") init_database; press_enter ;;
            "配置PiP镜像源")  config_pip_mirror; press_enter ;;
            "设置运行模式") select_mode; press_enter ;;
            "返回主菜单")    return ;;
        esac
    done
}

check_environment() {
    echo -e "${BOLD}环境检测${NC}"
    echo ""

    # Python
    if command -v python3 &>/dev/null; then
        ok "Python3: $(python3 --version 2>&1)"
    else
        error "Python3 未安装"
    fi

    # PostgreSQL
    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p 5432 &>/dev/null; then
        ok "PostgreSQL: 运行中"
    else
        warn "PostgreSQL: 未运行"
    fi

    # Redis
    if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
        ok "Redis: 运行中"
    else
        warn "Redis: 未运行"
    fi

    # Docker
    if command -v docker &>/dev/null && docker ps &>/dev/null; then
        ok "Docker: 可用"
    else
        warn "Docker: 不可用"
    fi

    # libzbar0
    if dpkg -l libzbar0 2>/dev/null | grep -q ^ii; then
        ok "libzbar0: 已安装"
    else
        warn "libzbar0: 未安装 (QR功能需要)"
    fi

    # 端口
    for port in 8000 8001 8080 5432 6379; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
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
    if ! pg_isready -h localhost -p 5432 &>/dev/null; then
        error "PostgreSQL 未运行，请先启动数据库服务"; return
    fi

    info "创建数据库和用户..."
    sudo -u postgres psql -c "CREATE USER warehouse_admin WITH PASSWORD 'warehouse123' CREATEDB;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE warehouse_inspection OWNER warehouse_admin;" 2>/dev/null || warn "数据库已存在"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE warehouse_inspection TO warehouse_admin;" 2>/dev/null || true
    ok "数据库初始化完成"
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
        "阿里云源")  export PIP_MIRROR="https://mirrors.aliyun.com/pypi/simple/"; ok "已设置为阿里云源" ;;
        "官方PyPI")    unset PIP_MIRROR; ok "已设置为官方源" ;;
        "返回")    ;;
    esac
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
        "Docker模式") set_mode "docker" ;;
        "本地模式")   set_mode "local" ;;
        "混合模式(推荐)")   set_mode "hybrid" ;;
        "返回")       ;;
    esac
}

quick_deploy() {
    echo -e "${BOLD}快速部署（全自动）${NC}"
    echo ""
    if ! confirm "将检测环境、安装依赖、初始化数据库。继续？"; then
        warn "已取消"; return
    fi

    check_environment
    echo ""
    install_dependencies
    echo ""
    init_database
    echo ""
    ok "快速部署完成"
}

# ── 服务管理子菜单 ────────────────────────────
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
            "启动所有服务")   bash "$SCRIPT_DIR/启动.sh" start; press_enter ;;
            "停止所有服务")   bash "$SCRIPT_DIR/启动.sh" stop; press_enter ;;
            "重启所有服务")   bash "$SCRIPT_DIR/启动.sh" restart; press_enter ;;
            "查看服务状态")   bash "$SCRIPT_DIR/启动.sh" status; press_enter ;;
            "查看日志")   view_logs ;;
            "启动单个服务")   start_single_service; press_enter ;;
            "停止单个服务")   stop_single_service; press_enter ;;
            "切换运行模式")   select_mode; press_enter ;;
            "返回主菜单")       return ;;
        esac
    done
}

view_logs() {
    echo -e "${BOLD}查看日志${NC}"
    echo ""
    echo "输入要查看的行数 (默认50):"
    read -r lines
    lines="${lines:-50}"
    if [ -d "$SCRIPT_DIR/logs" ]; then
        tail -"$lines" "$SCRIPT_DIR/logs/"*.log 2>/dev/null || warn "无日志文件"
    else
        warn "logs 目录不存在"
    fi
}

start_single_service() {
    echo -e "${BOLD}启动单个服务${NC}"
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "无人机数据系统(8000)" \
        "仓库巡检系统(8001)" \
        "API网关(8080)" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "无人机数据系统(8000)")
            MODE=$(get_mode) bash "$SCRIPT_DIR/启动.sh" start-drone 2>/dev/null || \
                bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start" ;;
        "仓库巡检系统(8001)")
            bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start-warehouse" 2>/dev/null || \
                bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start" ;;
        "API网关(8080)")
            bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start-gateway" 2>/dev/null || \
                bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start" ;;
        "返回") return ;;
    esac
}

stop_single_service() {
    echo -e "${BOLD}停止单个服务${NC}"
    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "无人机数据系统(8000)" \
        "仓库巡检系统(8001)" \
        "API网关(8080)" \
        "返回")
    [ $? -ne 0 ] && return
    case "$opt" in
        "无人机数据系统(8000)")
            pkill -f "uvicorn.*port=8000" 2>/dev/null && ok "已停止" || warn "未运行" ;;
        "仓库巡检系统(8001)")
            pkill -f "uvicorn.*port=8001" 2>/dev/null && ok "已停止" || warn "未运行" ;;
        "API网关(8080)")
            pkill -f "uvicorn.*port=8080" 2>/dev/null && ok "已停止" || warn "未运行" ;;
        "返回") return ;;
    esac
}

# ── 功能测试子菜单 ────────────────────────────
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
            "无人机模拟器")  run_drone_simulator; press_enter ;;
            "RFID读卡器测试")    test_rfid; press_enter ;;
            "QR码识别测试")      test_qr; press_enter ;;
            "API连通性测试")     test_api_connectivity; press_enter ;;
            "数据库连通性测试")  test_database; press_enter ;;
            "返回主菜单")        return ;;
        esac
    done
}

run_drone_simulator() {
    echo -e "${BOLD}运行无人机模拟器${NC}"
    echo ""
    local sim_dir="$SCRIPT_DIR/warehouse-inspection-system/tools"
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

    # 先诊断串口设备
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
sys.path.insert(0, '$SCRIPT_DIR/warehouse-inspection-system/backend/src')
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
    if [ -f "$SCRIPT_DIR/warehouse-inspection-system/backend/src/image/qr_worker.py" ]; then
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

    # Test each endpoint directly
    local targets=(
        "无人机数据系统|http://localhost:8000/health"
        "仓库巡检系统|http://localhost:8001/health"
        "API网关|http://localhost:8080/health"
        "看板API|http://localhost:8001/api/v1/dashboard/overview"
    )

    for entry in "${targets[@]}"; do
        local name="${entry%%|*}"
        local url="${entry#*|}"
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
    if command -v pg_isready &>/dev/null; then
        if pg_isready -h localhost -p 5432; then
            ok "PostgreSQL: 连接正常"
        else
            error "PostgreSQL: 连接失败"
        fi
    else
        error "pg_isready 未找到"
    fi

    if command -v redis-cli &>/dev/null; then
        local response
        response=$(redis-cli ping 2>/dev/null)
        if [ "$response" = "PONG" ]; then
            ok "Redis: 连接正常"
        else
            warn "Redis: 连接失败"
        fi
    else
        warn "redis-cli 未找到"
    fi
}

# ── 系统维护子菜单 ────────────────────────────
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
            "清理虚拟环境") clean_venvs; press_enter ;;
            "清理日志文件")     clean_logs; press_enter ;;
            "重置数据库")   reset_database; press_enter ;;
            "更新系统代码")     update_code; press_enter ;;
            "检查端口占用")     check_ports; press_enter ;;
            "返回主菜单")         return ;;
        esac
    done
}

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

clean_logs() {
    echo -e "${BOLD}清理日志文件${NC}"
    echo ""
    local log_dir="$SCRIPT_DIR/logs"
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
        warn "logs 目录不存在"
    fi
}

reset_database() {
    echo -e "${BOLD}重置数据库${NC}"
    echo ""
    warn "此操作将删除所有数据！"
    if ! confirm "确定要重置数据库吗？此操作不可恢复！"; then
        warn "已取消"; return
    fi
    if ! confirm "再次确认：真的要删除所有数据吗？"; then
        warn "已取消"; return
    fi

    info "正在重置数据库..."
    sudo -u postgres psql -c "DROP DATABASE warehouse_inspection;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE warehouse_inspection OWNER warehouse_admin;" 2>/dev/null || true
    ok "数据库已重置，重启服务后会自动重新建表"
}

update_code() {
    echo -e "${BOLD}更新系统代码${NC}"
    echo ""
    if command -v git &>/dev/null && git rev-parse --is-inside-work-tree &>/dev/null; then
        info "当前分支: $(git branch --show-current)"
        info "正在拉取更新..."
        git pull
        if [ $? -eq 0 ]; then
            ok "代码更新完成，建议重启服务"
        else
            warn "更新失败或已是最新"
        fi
    else
        warn "当前目录不是 git 仓库"
    fi
}

check_ports() {
    echo -e "${BOLD}端口占用检查${NC}"
    echo ""
    local ports=(8000 8001 8080 5432 6379)
    for port in "${ports[@]}"; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            local pid
            pid=$(ss -tlnp sport = :$port 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)
            warn "端口 $port: 已占用 (PID: ${pid:-未知})"
        else
            ok "端口 $port: 空闲"
        fi
    done
}

# ── 系统信息 ──────────────────────────────────
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
    pg_isready -h localhost -p 5432 &>/dev/null && echo "  状态: 运行中" || echo "  状态: 已停止"
    echo ""

    echo -e "${CYAN}--- Docker ---${NC}"
    if command -v docker &>/dev/null; then
        echo "  版本: $(docker --version 2>&1)"
        docker ps &>/dev/null && echo "  状态: 可用" || echo "  状态: 不可用"
    else
        echo "  未安装"
    fi
    echo ""

    echo -e "${CYAN}--- 磁盘使用 ---${NC}"
    df -h "$SCRIPT_DIR" 2>/dev/null | tail -1 | awk '{printf "  总空间: %s  已用: %s  可用: %s (%s)\n", $2, $3, $4, $5}'
    echo ""

    echo -e "${CYAN}--- 服务端口 ---${NC}"
    for port in 8000 8001 8080 5432 6379; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            echo "  端口 $port: 使用中"
        else
            echo "  端口 $port: 空闲"
        fi
    done
}

# ── 主菜单 ────────────────────────────────────
main_menu() {
    while true; do
        show_banner
        echo ""
        echo "  1) 环境部署"
        echo "  2) 服务管理"
        echo "  3) 功能测试"
        echo "  4) 系统维护"
        echo "  5) 系统信息"
        echo "  6) 退出"
        echo ""

        local opt
        opt=$(menu_select "请选择 [1-6]: " \
            "环境部署" \
            "服务管理" \
            "功能测试" \
            "系统维护" \
            "系统信息" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "环境部署") deploy_menu ;;
            "服务管理") service_menu ;;
            "功能测试") test_menu ;;
            "系统维护") maintenance_menu ;;
            "系统信息") show_system_info; press_enter ;;
            "退出")
                echo -e "${GREEN}再见!${NC}"
                exit 0 ;;
        esac
    done
}

# ── 入口 ──────────────────────────────────────
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT
main_menu
