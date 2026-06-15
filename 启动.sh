#!/bin/bash
# ========================================
#      域感智能 - Linux 快速启动/管理
# ========================================

# ── 颜色输出 ─────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${CYAN}[信息]${NC} $*"; }
ok()    { echo -e "${GREEN}[完成]${NC} $*"; }
warn()  { echo -e "${YELLOW}[警告]${NC} $*"; }
error() { echo -e "${RED}[错误]${NC} $*"; }
debug() { echo -e "${BLUE}[调试]${NC} $*"; }

# ── 项目根目录 ──────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 默认配置 ─────────────────────────────────
DRONE_PORT=${DRONE_PORT:-8000}
WAREHOUSE_PORT=${WAREHOUSE_PORT:-8001}
GATEWAY_PORT=${GATEWAY_PORT:-8080}
PIP_MIRROR=${PIP_MIRROR:-""}
VENV_DIR=${VENV_DIR:-""}
MODE=${MODE:-"hybrid"}  # hybrid=基础设施docker+后端本地, local=全部本地, docker=全部docker

# ── 日志轮转配置 ───────────────────────────────
MAX_LOG_SIZE=${MAX_LOG_SIZE:-10485760}  # 10MB
MAX_LOG_FILES=${MAX_LOG_FILES:-5}       # 保留5个历史日志

PIP_EXTRA=""
if [ -n "$PIP_MIRROR" ]; then
    PIP_EXTRA="-i $PIP_MIRROR --trusted-host $(echo "$PIP_MIRROR" | sed -E 's|https?://||' | sed 's|/.*||')"
fi

# ── 工具函数 ──────────────────────────────────
abs_path() {
    local rel="$1"
    local full="$SCRIPT_DIR/$rel"
    [ -d "$full" ] && echo "$full" || echo ""
}

get_venv() {
    local dir="$1"
    local abs="$(abs_path "$dir")"
    [ -n "$abs" ] && [ -d "$abs/venv" ] && echo "$abs/venv" && return
    if [ -n "$VENV_DIR" ]; then
        local name="$(basename "$abs")"
        [ -d "$VENV_DIR/$name" ] && echo "$VENV_DIR/$name"
    fi
}

require_cmd() {
    command -v "$1" &>/dev/null || { error "未找到命令: $1"; return 1; }
}

check_port() {
    local port=$1
    ss -tlnp 2>/dev/null | grep -q ":${port} "
}

check_docker_port() {
    docker ps --format '{{.Ports}}' 2>/dev/null | grep -qE "0\.0\.0\.0:${1}->|:${1}->"
}

# ─ 检查服务是否可用 ──────────────────────────
check_service_ready() {
    local name="$1" port="$2" max_wait="${3:-10}"
    info "等待 ${name} 就绪 (最多 ${max_wait}s)..."
    local i=0
    while [ $i -lt $max_wait ]; do
        if ! check_port "$port"; then
            ok "${name} 已就绪 (端口 $port)"
            return 0
        fi
        sleep 1
        i=$((i+1))
    done
    error "${name} 未在 ${max_wait}s 内就绪 (端口 $port)"
    return 1
}

# ── 日志轮转 ──────────────────────────────────
rotate_logs() {
    local log_dir="$SCRIPT_DIR/logs"
    [ ! -d "$log_dir" ] && return 0

    for log_file in "$log_dir"/*.log; do
        [ ! -f "$log_file" ] && continue
        local size
        size=$(stat -c%s "$log_file" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            local base="$(basename "$log_file" .log)"
            local date_stamp="$(date +%Y%m%d_%H%M%S)"
            # 归档当前日志
            cp "$log_file" "$log_dir/${base}_${date_stamp}.log"
            : > "$log_file"  # 清空当前日志
            info "日志已轮转: ${base}.log (${size} bytes → ${base}_${date_stamp}.log)"

            # 清理旧归档（保留最近 MAX_LOG_FILES 个）
            local count=0
            for old in $(ls -t "$log_dir/${base}_"*.log 2>/dev/null); do
                count=$((count+1))
                [ $count -gt "$MAX_LOG_FILES" ] && rm -f "$old"
            done
        fi
    done
}

# ── 自动重启守护 ──────────────────────────────
auto_restart_monitor() {
    local name="$1" port="$2" module="$3" dir="$4" req_file="${5:-requirements.txt}"
    local pid_file="$SCRIPT_DIR/logs/${name}.pid"
    local log_file="$SCRIPT_DIR/logs/${name}.log"

    # 检查PID文件
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            warn "${name} 进程已崩溃 (PID: $pid)，尝试重启..."
            rm -f "$pid_file"
            start_backend_bg "$name" "$dir" "$module" "$port" "$req_file" && \
                ok "${name} 自动重启成功" || \
                error "${name} 自动重启失败"
        fi
    fi

    # 检查端口是否存活
    if ! check_port "$port"; then
        warn "${name} 端口 $port 无响应，尝试重启..."
        start_backend_bg "$name" "$dir" "$module" "$port" "$req_file" && \
            ok "${name} 自动重启成功" || \
            error "${name} 自动重启失败"
    fi
}

# ── 守护进程入口 ──────────────────────────────
start_daemon() {
    info "启动自动重启守护进程 (PID: $$)"
    local count=0
    while true; do
        sleep 15
        count=$((count+1))
        # 每15秒检查一次 (仓库巡检系统先启动以确保表结构)
        auto_restart_monitor "仓库巡检系统" "$WAREHOUSE_PORT" "src.main:app" "warehouse-inspection-system/backend"
        auto_restart_monitor "无人机数据系统" "$DRONE_PORT" "app.main:app" "drone-db-prototype/backend"
        auto_restart_monitor "API网关" "$GATEWAY_PORT" "main:app" "api-gateway"
        # 每5分钟轮转一次日志
        if [ $((count % 20)) -eq 0 ]; then
            rotate_logs
        fi
    done
}

# ── 基础设施启动 (PostgreSQL + Redis) ─────────
start_infra() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    步骤 1/4: 启动基础设施${NC}"
    echo -e "${CYAN}========================================${NC}"

    # 检查本地是否已有 PostgreSQL
    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p 5432 &>/dev/null; then
        ok "本地 PostgreSQL 已运行"
    elif check_docker_port 5432; then
        ok "Docker PostgreSQL 已运行"
    else
        info "启动 Docker PostgreSQL + Redis..."
        if ! docker compose up -d postgres redis 2>&1; then
            error "Docker 启动失败，尝试使用本地服务..."
            if command -v pg_isready &>/dev/null; then
                sudo service postgresql start 2>/dev/null || true
                sleep 2
                if pg_isready -h localhost -p 5432 &>/dev/null; then
                    ok "本地 PostgreSQL 已启动"
                else
                    error "PostgreSQL 无法启动，请手动安装: sudo apt install postgresql"
                    return 1
                fi
            else
                error "PostgreSQL 未安装"
                return 1
            fi
        else
            check_service_ready "PostgreSQL" 5432 15 || return 1
            check_service_ready "Redis" 6379 10 || warn "Redis 未就绪 (可选)"
        fi
    fi
}

# ── 设置虚拟环境 ─────────────────────────────
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

    [ ! -d "$venv_dir" ] && { info "创建虚拟环境 ($dir)..."; python3 -m venv "$venv_dir"; }

    if [ -f "$abs_dir/$req_file" ]; then
        info "安装依赖 ($dir/$req_file)..."
        "$venv_dir/bin/pip" install $PIP_EXTRA -r "$abs_dir/$req_file" || return 1
        ok "依赖安装完成"
    fi
    return 0
}

# ── 启动后端服务 ──────────────────────────────
start_backend_bg() {
    local name="$1" dir="$2" module="$3" port="$4" req_file="${5:-requirements.txt}"
    local log_file="$SCRIPT_DIR/logs/${name}.log"
    local abs_dir="$(abs_path "$dir")"
    local venv_dir
    if [ -n "$VENV_DIR" ]; then
        venv_dir="$VENV_DIR/$(basename "$abs_dir")"
    else
        venv_dir="$abs_dir/venv"
    fi

    mkdir -p "$SCRIPT_DIR/logs"

    # 检查 Docker 是否占用
    if check_docker_port "$port"; then
        warn "端口 $port 已被 Docker 占用，跳过 ${name}"
        return 1
    fi

    # 停止旧进程
    if ! check_port "$port"; then
        local pid="$(lsof -ti :$port 2>/dev/null | head -1)"
        [ -n "$pid" ] && { warn "停止旧进程 (PID: $pid)"; kill -9 "$pid" 2>/dev/null; sleep 1; }
    fi

    setup_venv "$dir" "$req_file" || return 1

    info "启动 ${name} (端口 $port)..."
    cd "$abs_dir" && nohup "$venv_dir/bin/uvicorn" "$module" --host 0.0.0.0 --port "$port" > "$log_file" 2>&1 &
    cd "$SCRIPT_DIR"
    local pid=$!
    echo "$pid" > "$SCRIPT_DIR/logs/${name}.pid"
    debug "PID: $pid"

    sleep 4
    if kill -0 "$pid" 2>/dev/null && check_port "$port"; then
        ok "${name} 启动成功 (PID: $pid, 端口: $port)"
    else
        error "${name} 启动失败"
        error "=== 日志 (最后 20 行) ==="
        [ -f "$log_file" ] && tail -20 "$log_file"
        error "==========================="
        return 1
    fi
}

# ── 状态检查 ──────────────────────────────────
check_all_status() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}         服务状态总览${NC}"
    echo -e "${CYAN}========================================${NC}"

    local all_ok=true

    # PostgreSQL
    if command -v pg_isready &>/dev/null && pg_isready -h localhost -p 5432 &>/dev/null; then
        echo -e "  PostgreSQL      ${GREEN}[运行中]${NC}  端口 5432"
    elif check_docker_port 5432; then
        echo -e "  PostgreSQL      ${GREEN}[Docker]${NC}   端口 5432"
    else
        echo -e "  PostgreSQL      ${RED}[已停止]${NC}"
        all_ok=false
    fi

    # Redis
    if command -v redis-cli &>/dev/null && redis-cli -h localhost ping 2>/dev/null | grep -q PONG; then
        echo -e "  Redis           ${GREEN}[运行中]${NC}  端口 6379"
    elif check_docker_port 6379; then
        echo -e "  Redis           ${GREEN}[Docker]${NC}   端口 6379"
    else
        echo -e "  Redis           ${YELLOW}[未运行]${NC}  (可选)"
    fi

    # 后端服务
    for svc in "无人机数据系统:${DRONE_PORT}" "仓库巡检系统:${WAREHOUSE_PORT}" "API网关:${GATEWAY_PORT}"; do
        local name="${svc%%:*}" port="${svc##*:}"
        if check_port "$port"; then
            echo -e "  ${name}    ${GREEN}[运行中]${NC}  端口 $port"
        elif check_docker_port "$port"; then
            echo -e "  ${name}    ${GREEN}[Docker]${NC}   端口 $port"
        else
            echo -e "  ${name}    ${RED}[已停止]${NC}"
            all_ok=false
        fi
    done

    # 图传模块
    if ping -c 1 -W 1 192.168.1.200 &>/dev/null; then
        echo -e "  图传模块(200)   ${GREEN}[在线]${NC}"
    else
        echo -e "  图传模块(200)   ${RED}[离线]${NC}"
    fi

    echo ""
    $all_ok && ok "所有核心服务运行正常" || warn "部分服务未运行"
    return 0
}

# ── RFID 串口设备检测 ────────────────────────

# 检查并修复串口设备权限
check_rfid_permissions() {
    local device="$1"
    local auto_fix="${2:-false}"  # 是否自动修复权限

    # 1. 检查设备读写权限
    if [ -n "$device" ] && [ -e "$device" ]; then
        if [ -r "$device" ] && [ -w "$device" ]; then
            ok "设备权限正常: $device (可读写)"
        else
            warn "设备权限不足: $device"
            # 尝试自动修复权限（静默模式）
            if sudo -n true 2>/dev/null; then
                if sudo chmod 666 "$device" 2>/dev/null; then
                    ok "权限已自动修复: $device"
                else
                    warn "自动修复失败，请手动执行: sudo chmod 666 $device"
                fi
            elif [ "$auto_fix" = "true" ]; then
                # 非交互模式下仅警告
                warn "无 sudo 权限，请手动执行: sudo chmod 666 $device"
            fi
        fi
    fi

    # 2. 检查用户是否在 dialout 组 (Linux 专属)
    if [ "$(uname -s)" = "Linux" ]; then
        if groups "$USER" 2>/dev/null | grep -q dialout; then
            ok "用户已在 dialout 组"
        else
            warn "用户不在 dialout 组 (串口设备可能无法访问)"
            # 自动将用户加入 dialout 组
            if sudo -n true 2>/dev/null; then
                if sudo usermod -aG dialout "$USER" 2>/dev/null; then
                    ok "已将用户 $USER 加入 dialout 组"
                    info "注意: 组变更将在新终端会话中生效，当前会话可能需要重新登录"
                else
                    warn "加入 dialout 组失败，请手动执行: sudo usermod -aG dialout \$USER"
                fi
            elif [ "$auto_fix" = "true" ]; then
                warn "无 sudo 权限，请手动执行: sudo usermod -aG dialout \$USER"
            fi
        fi
    fi

    # 3. 检查 Docker 用户组权限 (如果使用 Docker 模式)
    if command -v docker &>/dev/null; then
        if groups "$USER" 2>/dev/null | grep -q docker; then
            ok "用户已在 docker 组"
        else
            warn "用户不在 docker 组"
            if sudo -n true 2>/dev/null; then
                if sudo usermod -aG docker "$USER" 2>/dev/null; then
                    ok "已将用户 $USER 加入 docker 组"
                    info "注意: 组变更将在新终端会话中生效"
                fi
            fi
        fi
    fi
}

detect_rfid_device() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    检测 RFID 串口设备${NC}"
    echo -e "${CYAN}========================================${NC}"

    local detected=""

    # 1. 检查环境变量中已配置的路径
    if [ -n "${RFID_DEVICE:-}" ]; then
        if [ -e "$RFID_DEVICE" ]; then
            ok "RFID 设备已配置且存在: $RFID_DEVICE"
            return 0
        else
            warn "RFID_DEVICE 指向的路径不存在: $RFID_DEVICE"
        fi
    fi

    # 2. 自动探测常见串口
    local candidates=()
    for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
        [ -e "$dev" ] && candidates+=("$dev")
    done

    if [ ${#candidates[@]} -eq 0 ]; then
        warn "未检测到任何串口设备"
        echo ""
        echo -e "  ${YELLOW}请手动配置 .env 文件中的 RFID_DEVICE 变量:${NC}"
        echo "    Linux:  RFID_DEVICE=/dev/ttyUSB0"
        if is_wsl; then
            echo "    WSL:    RFID_DEVICE=/dev/ttyS6  (COM7 映射)"
        fi
        echo "    不启用: RFID_DEVICE= (留空)"
        return 0
    fi

    echo ""
    echo "  检测到以下串口设备:"
    for dev in "${candidates[@]}"; do
        echo "    $dev"
    done
    echo ""

    # 自动选择第一个 /dev/ttyUSB 或 /dev/ttyACM
    for dev in "${candidates[@]}"; do
        if [[ "$dev" =~ /dev/ttyUSB|/dev/ttyACM ]]; then
            detected="$dev"
            break
        fi
    done
    # 没有 USB/ACM 就用第一个
    [ -z "$detected" ] && detected="${candidates[0]}"

    if [ -n "$detected" ]; then
        ok "自动选择 RFID 设备: $detected"
        export RFID_DEVICE="$detected"
        # 同步写入 .env 文件
        local env_file="$SCRIPT_DIR/warehouse-inspection-system/.env"
        if [ -f "$env_file" ]; then
            if grep -q "^RFID_DEVICE=" "$env_file"; then
                sed -i "s|^RFID_DEVICE=.*|RFID_DEVICE=$detected|" "$env_file"
            else
                echo "RFID_DEVICE=$detected" >> "$env_file"
            fi
            ok "已写入 .env: RFID_DEVICE=$detected"
        fi
        # 检查并修复权限（启用自动修复模式）
        check_rfid_permissions "$detected" true
    fi
    return 0
}

# ── 停止服务 ──────────────────────────────────
stop_service() {
    local name="$1" port="$2"
    local pid_file="$SCRIPT_DIR/logs/${name}.pid"
    if [ -f "$pid_file" ]; then
        local pid="$(cat "$pid_file")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 0.3
        fi
        rm -f "$pid_file"
        ok "$name 已停止"
    else
        info "$name 无 PID 文件，跳过"
    fi
}

stop_all() {
    info "停止所有服务..."
    # Kill backend processes by port using pgrep (fast and reliable)
    pkill -f "uvicorn.*port=$DRONE_PORT" 2>/dev/null || true
    pkill -f "uvicorn.*port=$WAREHOUSE_PORT" 2>/dev/null || true
    pkill -f "uvicorn.*port=$GATEWAY_PORT" 2>/dev/null || true
    sleep 0.3
    # Also kill by PID files if they exist
    stop_service "无人机数据系统" "$DRONE_PORT"
    stop_service "仓库巡检系统" "$WAREHOUSE_PORT"
    stop_service "API网关" "$GATEWAY_PORT"
    # Kill electron if running
    pkill -f "electron" 2>/dev/null || true
    rm -f "$SCRIPT_DIR/logs/"*.pid 2>/dev/null
    ok "所有服务已停止"
}

# ── 主流程: 一键启动 ──────────────────────────
start_all() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║     域感智能 - 一键启动             ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════╝${NC}"

    start_infra || { error "基础设施启动失败"; return 1; }

    detect_rfid_device

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    步骤 2/4: 启动仓库巡检系统${NC}"
    echo -e "${CYAN}    (先启动以创建统一的数据库表结构)${NC}"
    echo -e "${CYAN}========================================${NC}"
    start_backend_bg "仓库巡检系统" "warehouse-inspection-system/backend" "src.main:app" "$WAREHOUSE_PORT" || true

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    步骤 3/4: 启动无人机数据系统${NC}"
    echo -e "${CYAN}    (共用PostgreSQL数据库)${NC}"
    echo -e "${CYAN}========================================${NC}"
    start_backend_bg "无人机数据系统" "drone-db-prototype/backend" "app.main:app" "$DRONE_PORT" || true

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    步骤 4/4: 启动 API 网关${NC}"
    echo -e "${CYAN}========================================${NC}"
    start_backend_bg "API网关" "api-gateway" "main:app" "$GATEWAY_PORT" || true

    echo ""
    check_all_status
    echo ""
    echo -e "${GREEN}访问地址:${NC}"
    echo -e "  无人机数据:  ${CYAN}http://localhost:$DRONE_PORT${NC}"
    echo -e "  仓库巡检:    ${CYAN}http://localhost:$WAREHOUSE_PORT${NC}"
    echo -e "  API 网关:    ${CYAN}http://localhost:$GATEWAY_PORT${NC}"
    echo -e "  前端页面:    ${CYAN}file://$SCRIPT_DIR/warehouse-inspection-system/frontend/index.html${NC}"
    echo ""
}

# ── 帮助 ──────────────────────────────────────
show_help() {
    echo -e "${CYAN}域感智能 - 系统管理脚本${NC}"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "  (无参数)    一键启动所有服务"
    echo "  start       同上"
    echo "  status      查看服务状态"
    echo "  stop        停止所有服务"
    echo "  logs [n]    查看日志（最近n行）"
    echo "  restart     重启所有服务"
    echo "  daemon      启动守护进程（自动重启+日志轮转）"
    echo "  rotate-logs 手动触发日志轮转"
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

# ── 入口 ──────────────────────────────────────
case "${1:-}" in
    start|start-all) start_all ;;
    status)          check_all_status ;;
    stop)            stop_all ;;
    logs)            tail -${2:-50} logs/*.log 2>/dev/null || warn "无日志" ;;
    restart)         stop_all; sleep 2; start_all ;;
    daemon)          start_daemon ;;
    rotate-logs)     rotate_logs ;;
    help|--help|-h)  show_help ;;
    "")              start_all ;;
    *)               error "未知命令: $1"; show_help; exit 1 ;;
esac
