#!/bin/bash
# ========================================
#   域感智能 - 主启停脚本 (start.sh)
#   用途: 启动/停止/重启/状态查看 Docker Compose 服务
#   用法:
#     ./start.sh                交互式引导菜单
#     ./start.sh start          启动所有服务
#     ./start.sh start warehouse 单服务启动
#     ./start.sh stop           停止所有服务
#     ./start.sh restart        重启所有服务
#     ./start.sh status         查看服务状态
#     ./start.sh update         更新代码并重建
# ========================================

set -o pipefail

# ═══════════════════════════════════════════
#  颜色与日志函数
# ═══════════════════════════════════════════
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
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
OVERRIDE_FILE="$SCRIPT_DIR/docker-compose.override.yml"
COMPOSE_WRAPPER="$SCRIPT_DIR/docker-compose-wrapper.sh"
DAEMON_PID_FILE="$SCRIPT_DIR/.daemon.pid"

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
        error "Docker Compose 不可用"
        return 1
    fi
}

# ═══════════════════════════════════════════
#  .env 读取工具
# ═══════════════════════════════════════════
env_get() {
    local key="$1"
    [ -f "$ENV_FILE" ] && grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-
}

# ═══════════════════════════════════════════
#  前置检查
# ═══════════════════════════════════════════
preflight_check() {
    local errors=0

    # Docker
    if ! command -v docker &>/dev/null; then
        error "Docker 未安装"
        echo -e "  ${YELLOW}请运行: ./setup.sh fix${NC}"
        errors=$((errors + 1))
    elif ! docker ps &>/dev/null 2>&1; then
        error "Docker 守护进程未运行"
        echo -e "  ${YELLOW}请运行: sudo systemctl start docker${NC}"
        errors=$((errors + 1))
    fi

    # Docker Compose
    if ! dc version &>/dev/null 2>&1; then
        error "Docker Compose 不可用"
        echo -e "  ${YELLOW}请运行: ./setup.sh fix${NC}"
        errors=$((errors + 1))
    fi

    # .env 文件
    if [ ! -f "$ENV_FILE" ]; then
        error ".env 配置文件不存在"
        echo -e "  ${YELLOW}请运行: ./setup.sh init${NC}"
        errors=$((errors + 1))
    else
        # JWT_SECRET_KEY
        if [ -z "$(env_get 'JWT_SECRET_KEY')" ]; then
            error "JWT_SECRET_KEY 未配置"
            echo -e "  ${YELLOW}请运行: ./setup.sh init${NC}"
            errors=$((errors + 1))
        fi
    fi

    # docker-compose.yml
    if [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        error "docker-compose.yml 不存在"
        errors=$((errors + 1))
    fi

    # docker-compose.override.yml（可选但推荐）
    if [ ! -f "$OVERRIDE_FILE" ]; then
        warn "docker-compose.override.yml 不存在"
        echo -e "  ${YELLOW}建议运行: ./option.sh apply${NC}"
    fi

    return $errors
}

# ═══════════════════════════════════════════
#  RFID 串口权限扫描
# ═══════════════════════════════════════════
scan_rfid_permissions() {
    local rfid_device
    rfid_device=$(env_get "RFID_DEVICE")
    [ -z "$rfid_device" ] && rfid_device="/dev/ttyUSB0"

    local serial_devices=()
    for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
        [ -e "$dev" ] && serial_devices+=("$dev")
    done

    if [ ${#serial_devices[@]} -eq 0 ]; then
        echo "rfid_status=unavailable"
        return
    fi

    local has_permission=true
    local device_list=""
    for dev in "${serial_devices[@]}"; do
        if [ -r "$dev" ] && [ -w "$dev" ]; then
            device_list="$device_list$dev:ok,"
        else
            device_list="$device_list$dev:no_permission,"
            has_permission=false
        fi
    done

    if $has_permission; then
        echo "rfid_status=ready"
    else
        echo "rfid_status=no_permission"
    fi
    echo "rfid_devices=$device_list"
    echo "rfid_configured=$rfid_device"
}

# ═══════════════════════════════════════════
#  1. 启动服务
# ═══════════════════════════════════════════
start_services() {
    local service="${1:-}"

    echo ""
    echo -e "${BOLD}${CYAN}━━━ 启动服务 ━━━${NC}"
    echo ""

    # 前置检查
    if ! preflight_check; then
        error "前置检查失败，请先解决上述问题"
        echo ""
        echo -e "${YELLOW}提示:${NC}"
        echo "  - 环境初始化: ./setup.sh"
        echo "  - 配置修改:   ./option.sh"
        return 1
    fi

    # 确保 override 文件存在
    if [ ! -f "$OVERRIDE_FILE" ]; then
        warn "docker-compose.override.yml 不存在，自动生成..."
        "$SCRIPT_DIR/option.sh" apply >/dev/null 2>&1 || true
    fi

    # RFID 串口权限扫描（仅提示，不阻塞）
    echo -e "${CYAN}── RFID 串口扫描 ──${NC}"
    local rfid_info
    rfid_info=$(scan_rfid_permissions)
    local rfid_status
    rfid_status=$(echo "$rfid_info" | grep "^rfid_status=" | cut -d= -f2)
    case "$rfid_status" in
        ready)
            ok "RFID 串口: 可用"
            ;;
        no_permission)
            warn "RFID 串口: 权限不足"
            echo "  $rfid_info" | tr ',' '\n' | grep "no_permission" | while read -r line; do
                [ -n "$line" ] && echo "    - ${line}"
            done
            echo -e "  ${YELLOW}请在前端 RFID 界面点击权限申请按钮，或运行: ./option.sh → RFID设备配置${NC}"
            ;;
        unavailable)
            warn "RFID 串口: 未检测到设备（RFID 功能不可用，其他服务正常）"
            ;;
    esac
    echo ""

    # 启动
    if [ -n "$service" ]; then
        info "启动服务: $service"
        dc up -d "$service"
    else
        info "启动所有服务..."
        dc up -d
    fi

    local rc=$?
    if [ $rc -ne 0 ]; then
        error "启动失败"
        echo -e "  ${YELLOW}查看日志: ./logs.sh${NC}"
        return $rc
    fi

    # 等待健康检查
    echo ""
    info "等待服务健康检查（最多 60 秒）..."
    local healthy=0
    for i in $(seq 1 12); do
        sleep 5
        local total running
        total=$(dc ps --services 2>/dev/null | wc -l)
        running=$(dc ps 2>/dev/null | grep -c "healthy" || echo 0)
        echo "  [$i/12] healthy: $running/$total"
        if [ "$running" -ge "$total" ]; then
            healthy=1
            break
        fi
    done

    echo ""
    if [ "$healthy" = "1" ]; then
        ok "服务已启动并健康"
    else
        warn "部分服务可能未就绪，请检查状态: ./start.sh status"
    fi

    # 启动后状态报告
    echo ""
    show_status_report

    # 守护进程
    local daemon
    daemon=$(env_get "DAEMON_ENABLED")
    if [ "$daemon" = "true" ]; then
        start_daemon
    fi
}

# ═══════════════════════════════════════════
#  2. 停止服务
# ═══════════════════════════════════════════
stop_services() {
    local service="${1:-}"

    echo ""
    echo -e "${BOLD}${CYAN}━━━ 停止服务 ━━━${NC}"
    echo ""

    # 停止守护进程
    stop_daemon

    if [ -n "$service" ]; then
        info "停止服务: $service"
        dc stop "$service"
    else
        info "停止所有服务..."
        dc stop
    fi

    local rc=$?
    if [ $rc -eq 0 ]; then
        ok "服务已停止"
    else
        error "停止失败"
    fi
}

# ═══════════════════════════════════════════
#  3. 重启服务
# ═══════════════════════════════════════════
restart_services() {
    local service="${1:-}"

    echo ""
    echo -e "${BOLD}${CYAN}━━━ 重启服务 ━━━${NC}"
    echo ""

    if [ -n "$service" ]; then
        info "重启服务: $service"
        dc restart "$service"
        ok "$service 已重启"
    else
        info "全量重启..."
        stop_services
        sleep 2
        start_services
    fi
}

# ═══════════════════════════════════════════
#  4. 查看状态
# ═══════════════════════════════════════════
show_status() {
    echo ""
    show_status_report
}

show_status_report() {
    local mode
    mode=$(env_get "APP_MODE")
    mode="${mode:-dev}"

    echo -e "${BOLD}${CYAN}━━━ 服务状态 ━━━${NC}"
    echo ""
    echo -e "运行模式: ${GREEN}$mode${NC}"
    echo -e "局域网IP: $(hostname -I 2>/dev/null | awk '{print $1}')"
    echo ""

    # 容器状态
    echo -e "${CYAN}── 容器状态 ──${NC}"
    if dc ps &>/dev/null 2>&1; then
        dc ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || dc ps
    else
        warn "Docker Compose 不可用"
    fi

    echo ""

    # 访问地址
    echo -e "${CYAN}── 访问地址 ──${NC}"
    local lan_ip
    lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "  前端:        http://localhost:3000/"
    [ -n "$lan_ip" ] && echo "  前端(LAN):   http://$lan_ip:3000/"
    echo "  API网关:     http://localhost:8080"
    echo "  warehouse:   http://localhost:8001/docs"
    echo "  drone-db:    http://localhost:8000/docs"
    echo ""

    # RFID 状态
    echo -e "${CYAN}── RFID 串口 ──${NC}"
    local rfid_info
    rfid_info=$(scan_rfid_permissions)
    echo "$rfid_info" | while IFS= read -r line; do
        echo "  $line"
    done
    echo ""

    # 守护进程
    echo -e "${CYAN}── 守护进程 ──${NC}"
    if [ -f "$DAEMON_PID_FILE" ] && kill -0 "$(cat "$DAEMON_PID_FILE" 2>/dev/null)" 2>/dev/null; then
        ok "守护进程: 运行中 (PID: $(cat "$DAEMON_PID_FILE"))"
    else
        info "守护进程: 未启动"
    fi
}

# ═══════════════════════════════════════════
#  5. 更新代码并重建
# ═══════════════════════════════════════════
update_code() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 更新代码 ━━━${NC}"
    echo ""

    if [ ! -d "$SCRIPT_DIR/.git" ]; then
        warn "非 git 仓库，跳过代码更新"
        return
    fi

    # 获取更新
    info "拉取远程更新..."
    cd "$SCRIPT_DIR"
    git fetch origin 2>&1 | tail -5

    # 对比差异
    local local_commit remote_commit
    local_commit=$(git rev-parse HEAD)
    remote_commit=$(git rev-parse origin/HEAD 2>/dev/null || git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

    if [ "$local_commit" = "$remote_commit" ]; then
        ok "已是最新版本"
        return
    fi

    # 显示差异
    echo ""
    echo -e "${CYAN}── 待更新内容 ──${NC}"
    git log --oneline "$local_commit".."$remote_commit" 2>/dev/null | head -20
    echo ""

    # 文件变更
    local changed_files
    changed_files=$(git diff --stat "$local_commit" "$remote_commit" 2>/dev/null | tail -5)
    [ -n "$changed_files" ] && echo "$changed_files"
    echo ""

    # 二次确认
    if ! confirm "确认拉取更新？"; then
        info "已取消"; return
    fi

    # 拉取
    info "拉取更新..."
    git pull origin 2>&1 | tail -10
    if [ $? -ne 0 ]; then
        error "拉取失败，可能有本地未提交的修改"
        return
    fi

    # 重建
    echo ""
    if confirm "代码已更新。是否立即重建 Docker 镜像并重启服务？" "Y"; then
        info "重建镜像..."
        dc build --parallel 2>&1 | tail -20
        if [ $? -eq 0 ]; then
            ok "镜像重建完成"
            echo ""
            restart_services
        else
            error "镜像重建失败"
        fi
    else
        warn "需手动重建: ./setup.sh build && ./start.sh restart"
    fi
}

# ═══════════════════════════════════════════
#  6. 守护进程
# ═══════════════════════════════════════════
start_daemon() {
    if [ -f "$DAEMON_PID_FILE" ] && kill -0 "$(cat "$DAEMON_PID_FILE" 2>/dev/null)" 2>/dev/null; then
        warn "守护进程已在运行 (PID: $(cat "$DAEMON_PID_FILE"))"
        return
    fi

    local interval
    interval=$(env_get "DAEMON_CHECK_INTERVAL")
    interval="${interval:-30}"

    info "启动守护进程（检查间隔: ${interval}s）..."

    # 后台守护循环
    (
        while true; do
            sleep "$interval"
            # 检查容器健康状态
            unhealthy=$(dc ps 2>/dev/null | grep -c "unhealthy" || echo 0)
            if [ "$unhealthy" -gt 0 ]; then
                echo "[$(date '+%H:%M:%S')] 检测到 $unhealthy 个不健康容器，尝试重启..." >> "$SCRIPT_DIR/logs/daemon.log"
                dc restart 2>>"$SCRIPT_DIR/logs/daemon.log"
            fi
        done
    ) &

    local pid=$!
    echo "$pid" > "$DAEMON_PID_FILE"
    ok "守护进程已启动 (PID: $pid)"
}

stop_daemon() {
    if [ -f "$DAEMON_PID_FILE" ]; then
        local pid
        pid=$(cat "$DAEMON_PID_FILE" 2>/dev/null)
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            ok "守护进程已停止 (PID: $pid)"
        fi
        rm -f "$DAEMON_PID_FILE"
    fi
}

# ═══════════════════════════════════════════
#  7. 数据库管理
# ═══════════════════════════════════════════
manage_database() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 数据库管理 ━━━${NC}"
    echo ""

    local opt
    opt=$(menu_select "请选择 [1-5]: " \
        "进入 psql shell" \
        "查看数据库列表" \
        "备份数据库" \
        "恢复数据库" \
        "返回")
    [ $? -ne 0 ] && return

    case "$opt" in
        "进入 psql shell")
            info "进入 PostgreSQL shell（输入 \\q 退出）..."
            docker exec -it yugan-postgres psql -U postgres -d warehouse_inspection
            ;;
        "查看数据库列表")
            echo ""
            docker exec yugan-postgres psql -U postgres -c "\l" 2>/dev/null
            ;;
        "备份数据库")
            local backup_dir="$SCRIPT_DIR/logs/db_backup"
            mkdir -p "$backup_dir"
            local backup_file="$backup_dir/warehouse_$(date '+%Y%m%d_%H%M%S').sql"
            info "备份到: $backup_file"
            docker exec yugan-postgres pg_dump -U postgres warehouse_inspection > "$backup_file" 2>/dev/null
            if [ $? -eq 0 ]; then
                local size
                size=$(du -h "$backup_file" | cut -f1)
                ok "备份完成: $backup_file ($size)"
            else
                error "备份失败"
            fi
            ;;
        "恢复数据库")
            echo ""
            warn "此操作将覆盖当前数据库数据"
            if ! confirm "确定要恢复吗？"; then
                info "已取消"; return
            fi
            echo "输入备份文件路径:"
            read -r backup_file
            [ ! -f "$backup_file" ] && { error "文件不存在"; return; }
            info "恢复中..."
            docker exec -i yugan-postgres psql -U postgres -d warehouse_inspection < "$backup_file" 2>/dev/null
            [ $? -eq 0 ] && ok "恢复完成" || error "恢复失败"
            ;;
        "返回") ;;
    esac
}

# ═══════════════════════════════════════════
#  8. 健康检查
# ═══════════════════════════════════════════
health_check() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 健康检查 ━━━${NC}"
    echo ""

    local endpoints=(
        "warehouse|http://localhost:8001/health"
        "drone-db|http://localhost:8000/health"
        "api-gateway|http://localhost:8080/health"
        "frontend|http://localhost:3000"
    )

    for ep in "${endpoints[@]}"; do
        local name url
        name="${ep%%|*}"
        url="${ep##*|}"
        printf "  %-15s " "$name"
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")
        case "$code" in
            200|301|302) echo -e "${GREEN}$code OK${NC}  $url" ;;
            000)         echo -e "${RED}无法连接${NC}  $url" ;;
            *)           echo -e "${YELLOW}$code${NC}  $url" ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  主菜单
# ═══════════════════════════════════════════
main_menu() {
    while true; do
        local mode
        mode=$(env_get "APP_MODE")
        mode="${mode:-dev}"

        local daemon_status="关闭"
        if [ -f "$DAEMON_PID_FILE" ] && kill -0 "$(cat "$DAEMON_PID_FILE" 2>/dev/null)" 2>/dev/null; then
            daemon_status="开启"
        fi

        echo ""
        echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
        echo -e "${BOLD}${CYAN}║   域感智能 - 启停管理                ║${NC}"
        echo -e "${BOLD}${CYAN}║   模式:[$mode] 守护:[$daemon_status]       ║${NC}"
        echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-9]: " \
            "启动服务" \
            "停止服务" \
            "重启服务" \
            "查看状态" \
            "健康检查" \
            "更新代码" \
            "数据库管理" \
            "配置中心(option.sh)" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "启动服务")                start_services; press_enter ;;
            "停止服务")                stop_services; press_enter ;;
            "重启服务")                restart_services; press_enter ;;
            "查看状态")                show_status; press_enter ;;
            "健康检查")                health_check; press_enter ;;
            "更新代码")                update_code; press_enter ;;
            "数据库管理")              manage_database; press_enter ;;
            "配置中心(option.sh)")
                cd "$SCRIPT_DIR"
                ./option.sh
                cd - >/dev/null
                ;;
            "退出")                    echo -e "${GREEN}再见!${NC}"; exit 0 ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT

case "${1:-menu}" in
    menu)   main_menu ;;
    start)  shift; start_services "$@" ;;
    stop)   shift; stop_services "$@" ;;
    restart) shift; restart_services "$@" ;;
    status) show_status ;;
    health) health_check ;;
    update) update_code ;;
    db)     manage_database ;;
    daemon-start) start_daemon ;;
    daemon-stop)  stop_daemon ;;
    help|--help|-h)
        echo "用法: $0 [start|stop|restart|status|health|update|db|menu] [service]"
        echo ""
        echo "  start [service]   启动服务（可选指定服务名）"
        echo "  stop [service]    停止服务"
        echo "  restart [service] 重启服务"
        echo "  status            查看服务状态"
        echo "  health            健康检查"
        echo "  update            更新代码并重建"
        echo "  db                数据库管理"
        echo "  daemon-start      启动守护进程"
        echo "  daemon-stop       停止守护进程"
        echo "  menu              交互式菜单（默认）"
        echo ""
        echo "服务名: postgres redis drone-db warehouse api-gateway frontend"
        ;;
    *)
        error "未知命令: $1"
        echo "运行: $0 help"
        exit 1
        ;;
esac
