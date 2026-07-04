#!/bin/bash
# ========================================
#   域感智能 - 日志查看脚本 (logs.sh)
#   用途: 查看 Docker 容器日志和应用日志
#   用法:
#     ./logs.sh                    交互式引导菜单
#     ./logs.sh all                查看所有服务日志
#     ./logs.sh warehouse          查看 warehouse 日志
#     ./logs.sh warehouse -f       跟踪 warehouse 日志
#     ./logs.sh warehouse --tail 100  查看最后100行
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
        error "Docker Compose 不可用"
        return 1
    fi
}

# ═══════════════════════════════════════════
#  服务列表
# ═══════════════════════════════════════════
SERVICES=("postgres" "redis" "drone-db" "warehouse" "api-gateway" "frontend")

# ═══════════════════════════════════════════
#  1. 查看容器日志
# ═══════════════════════════════════════════
view_container_logs() {
    local service="$1"
    local follow="${2:-false}"
    local tail_lines="${3:-100}"

    if [ -z "$service" ]; then
        echo ""
        echo -e "${BOLD}${CYAN}━━━ 查看容器日志 ━━━${NC}"
        echo ""
        local opt
        opt=$(menu_select "请选择服务 [1-7]: " \
            "warehouse (仓库巡检)" \
            "drone-db (无人机数据)" \
            "api-gateway (网关)" \
            "postgres (数据库)" \
            "redis (缓存)" \
            "frontend (前端)" \
            "全部服务")
        [ $? -ne 0 ] && return

        case "$opt" in
            "warehouse (仓库巡检)")   service="warehouse" ;;
            "drone-db (无人机数据)")   service="drone-db" ;;
            "api-gateway (网关)")      service="api-gateway" ;;
            "postgres (数据库)")       service="postgres" ;;
            "redis (缓存)")            service="redis" ;;
            "frontend (前端)")         service="frontend" ;;
            "全部服务")                service="all" ;;
        esac
    fi

    echo ""
    if [ "$service" = "all" ]; then
        info "查看所有服务日志（最后 $tail_lines 行）..."
        dc logs --tail="$tail_lines" 2>&1 | less -R
    else
        if [ "$follow" = "true" ]; then
            info "跟踪 $service 日志（Ctrl+C 退出）..."
            dc logs -f --tail="$tail_lines" "$service"
        else
            info "查看 $service 日志（最后 $tail_lines 行）..."
            dc logs --tail="$tail_lines" "$service" 2>&1 | less -R
        fi
    fi
}

# ═══════════════════════════════════════════
#  2. 查看应用日志文件
# ═══════════════════════════════════════════
view_app_logs() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 应用日志文件 ━━━${NC}"
    echo ""

    local log_files=()
    if [ -f "$SCRIPT_DIR/logs/devlog.md" ]; then
        log_files+=("devlog.md (开发日志)")
    fi

    # 收集 logs/review 下的报告
    if [ -d "$SCRIPT_DIR/logs/review" ]; then
        while IFS= read -r -d '' f; do
            local basename
            basename=$(basename "$f")
            log_files+=("review/$basename")
        done < <(find "$SCRIPT_DIR/logs/review" -maxdepth 1 -type f -name "*.md" -print0 2>/dev/null)
    fi

    # 收集 logs 下的其他日志
    if [ -d "$SCRIPT_DIR/logs" ]; then
        while IFS= read -r -d '' f; do
            local basename
            basename=$(basename "$f")
            [ "$basename" = "devlog.md" ] && continue
            log_files+=("$basename")
        done < <(find "$SCRIPT_DIR/logs" -maxdepth 1 -type f -name "*.log" -o -name "*.txt" -print0 2>/dev/null)
    fi

    if [ ${#log_files[@]} -eq 0 ]; then
        warn "未找到应用日志文件"
        return
    fi

    log_files+=("返回")

    local opt
    opt=$(menu_select "请选择 [1-${#log_files[@]}]: " "${log_files[@]}")
    [ $? -ne 0 ] && return

    [ "$opt" = "返回" ] && return

    local target_file
    case "$opt" in
        devlog.md*) target_file="$SCRIPT_DIR/logs/devlog.md" ;;
        review/*)   target_file="$SCRIPT_DIR/logs/review/${opt#review/}" ;;
        *)          target_file="$SCRIPT_DIR/logs/$opt" ;;
    esac

    if [ -f "$target_file" ]; then
        info "查看: $target_file"
        less -R "$target_file"
    else
        error "文件不存在: $target_file"
    fi
}

# ═══════════════════════════════════════════
#  3. 实时监控（多窗口）
# ═══════════════════════════════════════════
live_monitor() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 实时监控 ━━━${NC}"
    echo ""
    info "将同时跟踪所有后端服务日志（Ctrl+C 退出）"
    echo ""
    warn "按 Ctrl+C 退出"
    read -r -p "按回车开始..."

    dc logs -f --tail=20 warehouse drone-db api-gateway
}

# ═══════════════════════════════════════════
#  4. 查看错误日志
# ═══════════════════════════════════════════
view_errors() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 错误日志 ━━━${NC}"
    echo ""

    local opt
    opt=$(menu_select "请选择 [1-4]: " \
        "warehouse 最近错误" \
        "drone-db 最近错误" \
        "api-gateway 最近错误" \
        "返回")
    [ $? -ne 0 ] && return

    [ "$opt" = "返回" ] && return

    local service=""
    case "$opt" in
        warehouse*)    service="warehouse" ;;
        drone-db*)     service="drone-db" ;;
        api-gateway*)  service="api-gateway" ;;
    esac

    info "过滤 $service 中的 ERROR/WARNING（最近 500 行）..."
    dc logs --tail=500 "$service" 2>&1 | grep -iE "error|warning|exception|traceback|failed" | less -R
}

# ═══════════════════════════════════════════
#  5. 导出日志
# ═══════════════════════════════════════════
export_logs() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 导出日志 ━━━${NC}"
    echo ""

    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local export_dir="$SCRIPT_DIR/logs/export"
    mkdir -p "$export_dir"

    local export_file="$export_dir/logs_$timestamp.tar.gz"

    info "导出到: $export_file"
    warn "包含所有容器日志（最近 1000 行）+ 应用日志文件"

    # 导出容器日志
    for svc in "${SERVICES[@]}"; do
        dc logs --tail=1000 "$svc" > "$export_dir/${svc}.log" 2>/dev/null
    done

    # 打包
    tar -czf "$export_file" \
        -C "$export_dir" \
        postgres.log redis.log drone-db.log warehouse.log api-gateway.log frontend.log \
        2>/dev/null

    # 清理临时文件
    rm -f "$export_dir"/{postgres,redis,drone-db,warehouse,api-gateway,frontend}.log

    # 加入应用日志
    if [ -d "$SCRIPT_DIR/logs" ]; then
        tar -czf "$export_file" -C "$SCRIPT_DIR" logs/ 2>/dev/null
    fi

    ok "日志已导出: $export_file"
    local size
    size=$(du -h "$export_file" | cut -f1)
    info "文件大小: $size"
}

# ═══════════════════════════════════════════
#  主菜单
# ═══════════════════════════════════════════
main_menu() {
    while true; do
        echo ""
        echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
        echo -e "${BOLD}${CYAN}║   域感智能 - 日志查看                ║${NC}"
        echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-7]: " \
            "查看容器日志" \
            "实时跟踪日志" \
            "查看应用日志文件" \
            "查看错误日志" \
            "实时监控(多服务)" \
            "导出日志" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "查看容器日志")       view_container_logs; press_enter ;;
            "实时跟踪日志")       view_container_logs "" true 100 ;;
            "查看应用日志文件")   view_app_logs; press_enter ;;
            "查看错误日志")       view_errors; press_enter ;;
            "实时监控(多服务)")   live_monitor ;;
            "导出日志")           export_logs; press_enter ;;
            "退出")               echo -e "${GREEN}再见!${NC}"; exit 0 ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT

# 解析 CLI 参数
# 用法: ./logs.sh [service] [-f] [--tail N]
if [ $# -gt 0 ] && [ "$1" != "menu" ] && [ "$1" != "help" ] && [ "$1" != "--help" ] && [ "$1" != "-h" ]; then
    service="$1"
    shift
    follow="false"
    tail_lines=100

    while [ $# -gt 0 ]; do
        case "$1" in
            -f|--follow) follow="true"; shift ;;
            --tail)      tail_lines="$2"; shift 2 ;;
            *)           shift ;;
        esac
    done

    view_container_logs "$service" "$follow" "$tail_lines"
    exit $?
fi

case "${1:-menu}" in
    menu)   main_menu ;;
    help|--help|-h)
        echo "用法: $0 [service] [-f] [--tail N] | menu"
        echo ""
        echo "  service  服务名 (warehouse/drone-db/api-gateway/postgres/redis/frontend/all)"
        echo "  -f       跟踪日志"
        echo "  --tail N 最后 N 行（默认 100）"
        echo "  menu     交互式菜单（默认）"
        ;;
    *)
        error "未知命令: $1"
        exit 1
        ;;
esac
