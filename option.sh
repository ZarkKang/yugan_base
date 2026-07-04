#!/bin/bash
# ========================================
#   域感智能 - 配置中心脚本 (option.sh)
#   用途: 修改运行模式、CORS、RFID、守护进程等配置
#   用法:
#     ./option.sh              交互式引导菜单
#     ./option.sh show         查看当前配置
#     ./option.sh set-mode dev 设置运行模式
#     ./option.sh add-lan-ip   自动添加局域网IP到CORS
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

# ═══════════════════════════════════════════
#  .env 读写工具
# ═══════════════════════════════════════════
env_get() {
    local key="$1"
    [ -f "$ENV_FILE" ] && grep "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-
}

env_set() {
    local key="$1" val="$2"
    [ ! -f "$ENV_FILE" ] && touch "$ENV_FILE"
    if grep -q "^${key}=" "$ENV_FILE"; then
        # 兼容 sed 特殊字符：用 | 作为分隔符，对 val 中的 | 转义
        local safe_val
        safe_val=$(printf '%s' "$val" | sed 's/[&|]/\\&/g')
        sed -i "s|^${key}=.*|${key}=${safe_val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

env_get_mode() {
    local mode
    mode=$(env_get "APP_MODE")
    echo "${mode:-dev}"
}

# ═══════════════════════════════════════════
#  docker-compose.override.yml 生成
#  根据 APP_MODE 生成对应的覆盖配置
# ═══════════════════════════════════════════
generate_override() {
    local mode
    mode=$(env_get_mode)

    local debug_val="false"
    local restart_policy="no"
    local health_interval="30s"
    local docs_flag="false"

    if [ "$mode" = "dev" ]; then
        debug_val="true"
        restart_policy="no"
        health_interval="30s"
        docs_flag="true"
    elif [ "$mode" = "prod" ]; then
        debug_val="false"
        restart_policy="always"
        health_interval="10s"
        docs_flag="false"
    fi

    # 同步 DEBUG 到 .env（供 config.py 读取）
    env_set "DEBUG" "$debug_val"

    cat > "$OVERRIDE_FILE" <<EOF
# 自动生成 by option.sh - 模式: $mode
# 请勿手动编辑，运行 ./option.sh 重新生成
# 生成时间: $(date '+%Y-%m-%d %H:%M:%S')

services:
  drone-db:
    environment:
      - DEBUG=$debug_val
    restart: $restart_policy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: $health_interval
      timeout: 5s
      retries: 3
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000

  warehouse:
    environment:
      - DEBUG=$debug_val
    restart: $restart_policy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: $health_interval
      timeout: 5s
      retries: 3
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000

  api-gateway:
    environment:
      - DEBUG=$debug_val
    restart: $restart_policy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: $health_interval
      timeout: 5s
      retries: 3
    command: uvicorn main:app --host 0.0.0.0 --port 8080

  postgres:
    restart: $restart_policy
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: $health_interval
      timeout: 5s
      retries: 5

  redis:
    restart: $restart_policy
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: $health_interval
      timeout: 3s
      retries: 3

  frontend:
    restart: $restart_policy
EOF

    ok "docker-compose.override.yml 已生成 (模式: $mode)"
    info "  DEBUG=$debug_val, restart=$restart_policy, healthcheck=$health_interval"
}

# ═══════════════════════════════════════════
#  1. 查看当前配置
# ═══════════════════════════════════════════
show_config() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 当前配置 ━━━${NC}"
    echo ""

    if [ ! -f "$ENV_FILE" ]; then
        error ".env 不存在，请运行 ./setup.sh init"
        return
    fi

    local mode
    mode=$(env_get_mode)

    echo -e "${CYAN}── 运行模式 ──${NC}"
    case "$mode" in
        dev)  echo "  APP_MODE: ${GREEN}dev${NC} (开发模式 - DEBUG日志/Swagger开放/CORS宽松)" ;;
        prod) echo "  APP_MODE: ${GREEN}prod${NC} (生产模式 - INFO日志/Swagger关闭/CORS严格/restart=always)" ;;
        *)    echo "  APP_MODE: ${YELLOW}$mode${NC} (未知)" ;;
    esac
    echo ""

    echo -e "${CYAN}── 安全 ──${NC}"
    local jwt
    jwt=$(env_get "JWT_SECRET_KEY")
    if [ -n "$jwt" ] && [ "$jwt" != "your-secret-key-here" ]; then
        echo "  JWT_SECRET_KEY: ${GREEN}已配置${NC} (${jwt:0:8}...)"
    else
        echo "  JWT_SECRET_KEY: ${RED}未配置${NC}"
    fi
    echo ""

    echo -e "${CYAN}── CORS 白名单 ──${NC}"
    local cors
    cors=$(env_get "CORS_ORIGINS")
    if [ -n "$cors" ]; then
        echo "  CORS_ORIGINS: $cors"
    else
        echo "  CORS_ORIGINS: ${RED}未配置${NC}"
    fi
    echo ""

    echo -e "${CYAN}── RFID 硬件 ──${NC}"
    echo "  RFID_DEVICE: $(env_get 'RFID_DEVICE' || echo '未配置')"
    echo "  RFID_BAUD_RATE: $(env_get 'RFID_BAUD_RATE' || echo '未配置')"
    echo ""

    echo -e "${CYAN}── 守护进程 ──${NC}"
    local daemon
    daemon=$(env_get "DAEMON_ENABLED")
    if [ "$daemon" = "true" ]; then
        echo "  DAEMON_ENABLED: ${GREEN}true${NC} (启动脚本外的自动重启监控)"
    else
        echo "  DAEMON_ENABLED: ${YELLOW}false${NC} (依赖 Docker restart 策略)"
    fi
    echo ""

    echo -e "${CYAN}── Swagger 文档 ──${NC}"
    if [ "$mode" = "dev" ]; then
        echo "  /docs: ${GREEN}开放${NC} (http://localhost:8001/docs)"
    else
        echo "  /docs: ${YELLOW}关闭${NC}"
    fi
    echo ""

    echo -e "${CYAN}── override 文件 ──${NC}"
    if [ -f "$OVERRIDE_FILE" ]; then
        ok "docker-compose.override.yml: 存在"
    else
        warn "docker-compose.override.yml: 不存在（运行 ./option.sh apply 生成）"
    fi
}

# ═══════════════════════════════════════════
#  2. 切换运行模式
# ═══════════════════════════════════════════
set_mode() {
    local target="${1:-}"
    local current
    current=$(env_get_mode)

    if [ -z "$target" ]; then
        echo ""
        echo -e "${BOLD}${CYAN}━━━ 切换运行模式 ━━━${NC}"
        echo ""
        echo "  当前模式: $current"
        echo ""
        echo "  dev  - 开发模式（DEBUG日志、Swagger开放、CORS宽松、restart=no）"
        echo "  prod - 生产模式（INFO日志、Swagger关闭、CORS严格、restart=always）"
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-3]: " \
            "开发模式(dev)" \
            "生产模式(prod)" \
            "返回")
        [ $? -ne 0 ] && return
        case "$opt" in
            "开发模式(dev)")  target="dev" ;;
            "生产模式(prod)") target="prod" ;;
            "返回")           return ;;
        esac
    fi

    if [ "$target" = "$current" ]; then
        info "当前已是 $target 模式，无需切换"
        return
    fi

    echo ""
    info "切换模式: $current → $target"
    echo ""

    # 显示模式差异
    echo -e "${CYAN}模式差异:${NC}"
    if [ "$target" = "dev" ]; then
        echo "  日志级别: INFO → DEBUG"
        echo "  Swagger: 关闭 → 开放"
        echo "  CORS: 严格 → 宽松（保留当前白名单）"
        echo "  Docker restart: always → no"
        echo "  健康检查间隔: 10s → 30s"
    else
        echo "  日志级别: DEBUG → INFO"
        echo "  Swagger: 开放 → 关闭"
        echo "  CORS: 宽松 → 严格（保留当前白名单）"
        echo "  Docker restart: no → always"
        echo "  健康检查间隔: 30s → 10s"
    fi
    echo ""

    if ! confirm "确认切换到 $target 模式？"; then
        info "已取消"; return
    fi

    env_set "APP_MODE" "$target"
    generate_override

    echo ""
    if confirm "模式已保存。是否立即重启服务使配置生效？" "Y"; then
        info "重启服务..."
        "$SCRIPT_DIR/start.sh" restart
    else
        warn "配置已保存但未生效，请手动运行: ./start.sh restart"
    fi
}

# ═══════════════════════════════════════════
#  3. CORS 白名单管理
# ═══════════════════════════════════════════
manage_cors() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ CORS 白名单管理 ━━━${NC}"
    echo ""

    local current
    current=$(env_get "CORS_ORIGINS")
    echo "  当前白名单: $current"
    echo ""

    local opt
    opt=$(menu_select "请选择 [1-5]: " \
        "自动添加局域网IP" \
        "手动添加来源" \
        "删除来源" \
        "重置为默认" \
        "返回")
    [ $? -ne 0 ] && return

    case "$opt" in
        "自动添加局域网IP")
            local lan_ip
            lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
            if [ -z "$lan_ip" ]; then
                error "无法检测局域网 IP"; return
            fi
            local new_origin="http://$lan_ip:3000"
            info "检测到局域网 IP: $lan_ip"
            info "将添加: $new_origin"

            # 解析当前 JSON 数组并添加
            python3 - <<PYEOF
import json, sys
try:
    origins = json.loads('''$current''')
    if not isinstance(origins, list):
        origins = []
except Exception:
    origins = []
new = "$new_origin"
if new not in origins:
    origins.append(new)
print(json.dumps(origins, ensure_ascii=False))
PYEOF
            local new_cors
            new_cors=$(python3 -c "
import json
try:
    origins = json.loads('''$current''')
    if not isinstance(origins, list):
        origins = []
except Exception:
    origins = []
new = '$new_origin'
if new not in origins:
    origins.append(new)
print(json.dumps(origins, ensure_ascii=False))
" 2>/dev/null)

            if [ -n "$new_cors" ]; then
                env_set "CORS_ORIGINS" "$new_cors"
                ok "CORS 已更新: $new_cors"
                echo ""
                if confirm "是否重启服务使配置生效？" "Y"; then
                    "$SCRIPT_DIR/start.sh" restart
                fi
            else
                error "解析失败"
            fi
            ;;

        "手动添加来源")
            echo ""
            echo -e "输入要添加的来源（如 http://192.168.1.100:3000）:"
            read -r new_origin
            [ -z "$new_origin" ] && { info "已取消"; return; }

            local new_cors
            new_cors=$(python3 -c "
import json
try:
    origins = json.loads('''$current''')
    if not isinstance(origins, list):
        origins = []
except Exception:
    origins = []
if '$new_origin' not in origins:
    origins.append('$new_origin')
print(json.dumps(origins, ensure_ascii=False))
" 2>/dev/null)

            if [ -n "$new_cors" ]; then
                env_set "CORS_ORIGINS" "$new_cors"
                ok "CORS 已更新: $new_cors"
                echo ""
                if confirm "是否重启服务使配置生效？" "Y"; then
                    "$SCRIPT_DIR/start.sh" restart
                fi
            fi
            ;;

        "删除来源")
            echo ""
            python3 -c "
import json
try:
    origins = json.loads('''$current''')
except Exception:
    origins = []
for i, o in enumerate(origins, 1):
    print(f'  {i}. {o}')
" 2>/dev/null
            echo ""
            echo "输入要删除的序号:"
            read -r idx
            local new_cors
            new_cors=$(python3 -c "
import json
try:
    origins = json.loads('''$current''')
except Exception:
    origins = []
idx = $idx - 1
if 0 <= idx < len(origins):
    origins.pop(idx)
print(json.dumps(origins, ensure_ascii=False))
" 2>/dev/null)
            if [ -n "$new_cors" ]; then
                env_set "CORS_ORIGINS" "$new_cors"
                ok "CORS 已更新: $new_cors"
                echo ""
                if confirm "是否重启服务使配置生效？" "Y"; then
                    "$SCRIPT_DIR/start.sh" restart
                fi
            fi
            ;;

        "重置为默认")
            local lan_ip
            lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
            local default_cors="[\"http://localhost:3000\",\"http://127.0.0.1:3000\""
            [ -n "$lan_ip" ] && default_cors="$default_cors,\"http://$lan_ip:3000\""
            default_cors="$default_cors]"
            env_set "CORS_ORIGINS" "$default_cors"
            ok "CORS 已重置: $default_cors"
            echo ""
            if confirm "是否重启服务使配置生效？" "Y"; then
                "$SCRIPT_DIR/start.sh" restart
            fi
            ;;

        "返回") ;;
    esac
}

# ═══════════════════════════════════════════
#  4. RFID 设备配置
# ═══════════════════════════════════════════
manage_rfid() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ RFID 设备配置 ━━━${NC}"
    echo ""

    echo -e "${CYAN}当前配置:${NC}"
    echo "  RFID_DEVICE: $(env_get 'RFID_DEVICE' || echo '未配置')"
    echo "  RFID_BAUD_RATE: $(env_get 'RFID_BAUD_RATE' || echo '未配置')"
    echo ""

    echo -e "${CYAN}可用串口设备:${NC}"
    local devices=()
    local idx=1
    for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
        if [ -e "$dev" ]; then
            local perm="不可读写"
            if [ -r "$dev" ] && [ -w "$dev" ]; then
                perm="${GREEN}可读写${NC}"
            else
                perm="${RED}不可读写${NC}"
            fi
            echo "  $idx. $dev ($perm)"
            devices+=("$dev")
            idx=$((idx + 1))
        fi
    done

    if [ ${#devices[@]} -eq 0 ]; then
        warn "未检测到任何串口设备"
        echo ""
        info "RFID 串口权限申请说明:"
        echo "  1. 临时权限: sudo chmod 666 /dev/ttyUSB0"
        echo "  2. 永久权限: sudo usermod -aG dialout \$USER（需重新登录）"
        echo ""
        echo "  前端 RFID 界面也提供串口扫描和权限申请按钮"
        return
    fi

    echo ""
    local opt
    opt=$(menu_select "请选择 [1-3]: " \
        "选择串口设备" \
        "申请串口权限(sudo)" \
        "返回")
    [ $? -ne 0 ] && return

    case "$opt" in
        "选择串口设备")
            echo ""
            echo "输入序号选择设备:"
            read -r sel
            local sel_idx=$((sel - 1))
            if [ $sel_idx -ge 0 ] && [ $sel_idx -lt ${#devices[@]} ]; then
                local selected="${devices[$sel_idx]}"
                env_set "RFID_DEVICE" "$selected"
                ok "RFID_DEVICE 已设置为: $selected"
                echo ""
                warn "需重启 warehouse 容器使配置生效: ./start.sh restart warehouse"
            else
                error "无效选择"
            fi
            ;;

        "申请串口权限(sudo)")
            echo ""
            info "将申请所有串口设备的读写权限"
            if sudo -n true 2>/dev/null; then
                for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
                    [ -e "$dev" ] && sudo chmod 666 "$dev" 2>/dev/null && ok "$dev 权限已修复"
                done
                sudo usermod -aG dialout "$USER" 2>/dev/null && ok "已加入 dialout 组（重新登录后生效）"
                ok "权限申请完成"
            else
                warn "需要 sudo 密码，请在下方输入:"
                for dev in /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*; do
                    [ -e "$dev" ] && sudo chmod 666 "$dev" 2>/dev/null && ok "$dev 权限已修复"
                done
                sudo usermod -aG dialout "$USER" 2>/dev/null && ok "已加入 dialout 组（重新登录后生效）"
            fi
            ;;

        "返回") ;;
    esac
}

# ═══════════════════════════════════════════
#  5. 守护进程开关
# ═══════════════════════════════════════════
manage_daemon() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 守护进程配置 ━━━${NC}"
    echo ""

    local current
    current=$(env_get "DAEMON_ENABLED")
    echo "  当前状态: $current"
    echo ""
    echo "  守护进程会在 start.sh 启动时额外启动一个监控循环，"
    echo "  定期检查容器健康状态，不健康时自动重启。"
    echo "  Docker 自带 restart 策略已能处理崩溃重启，"
    echo "  守护进程主要用于健康检查异常（服务运行但响应异常）的场景。"
    echo ""

    local opt
    opt=$(menu_select "请选择 [1-3]: " \
        "开启守护进程" \
        "关闭守护进程(默认)" \
        "返回")
    [ $? -ne 0 ] && return

    case "$opt" in
        "开启守护进程")
            env_set "DAEMON_ENABLED" "true"
            ok "守护进程已开启"
            warn "需重启 start.sh 生效: ./start.sh restart"
            ;;
        "关闭守护进程(默认)")
            env_set "DAEMON_ENABLED" "false"
            ok "守护进程已关闭（依赖 Docker restart 策略）"
            warn "需重启 start.sh 生效: ./start.sh restart"
            ;;
        "返回") ;;
    esac
}

# ═══════════════════════════════════════════
#  6. JWT 密钥重置
# ═══════════════════════════════════════════
reset_jwt() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 重置 JWT 密钥 ━━━${NC}"
    echo ""
    warn "重置后所有已登录用户需重新登录"
    if ! confirm "确认重置 JWT_SECRET_KEY？"; then
        info "已取消"; return
    fi
    local new_key
    new_key=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)
    env_set "JWT_SECRET_KEY" "$new_key"
    ok "JWT_SECRET_KEY 已重置"
    echo ""
    if confirm "是否重启服务使配置生效？" "Y"; then
        "$SCRIPT_DIR/start.sh" restart
    fi
}

# ═══════════════════════════════════════════
#  7. 应用配置（生成 override）
# ═══════════════════════════════════════════
apply_config() {
    echo ""
    echo -e "${BOLD}${CYAN}━━━ 应用配置 ━━━${NC}"
    echo ""
    info "根据当前 .env 生成 docker-compose.override.yml"
    generate_override
    echo ""
    if confirm "是否重启服务使配置生效？" "Y"; then
        "$SCRIPT_DIR/start.sh" restart
    fi
}

# ═══════════════════════════════════════════
#  主菜单
# ═══════════════════════════════════════════
main_menu() {
    while true; do
        local mode
        mode=$(env_get_mode)
        echo ""
        echo -e "${BOLD}${CYAN}╔══════════════════════════════════════╗${NC}"
        echo -e "${BOLD}${CYAN}║   域感智能 - 配置中心                ║${NC}"
        echo -e "${BOLD}${CYAN}║   运行模式: [${mode}]                   ║${NC}"
        echo -e "${BOLD}${CYAN}╚══════════════════════════════════════╝${NC}"
        echo ""
        local opt
        opt=$(menu_select "请选择 [1-8]: " \
            "查看当前配置" \
            "切换运行模式(dev/prod)" \
            "CORS白名单管理" \
            "RFID设备配置" \
            "守护进程开关" \
            "重置JWT密钥" \
            "应用配置(生成override)" \
            "退出")
        [ $? -ne 0 ] && continue
        case "$opt" in
            "查看当前配置")               show_config; press_enter ;;
            "切换运行模式(dev/prod)")     set_mode; press_enter ;;
            "CORS白名单管理")             manage_cors; press_enter ;;
            "RFID设备配置")               manage_rfid; press_enter ;;
            "守护进程开关")               manage_daemon; press_enter ;;
            "重置JWT密钥")                reset_jwt; press_enter ;;
            "应用配置(生成override)")     apply_config; press_enter ;;
            "退出")                       echo -e "${GREEN}再见!${NC}"; exit 0 ;;
        esac
    done
}

# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT

# 确保 .env 存在
if [ ! -f "$ENV_FILE" ]; then
    warn ".env 不存在，请先运行: ./setup.sh init"
    exit 1
fi

case "${1:-menu}" in
    menu)               main_menu ;;
    show)               show_config ;;
    set-mode)
        if [ -z "$2" ]; then
            set_mode
        else
            set_mode "$2"
        fi
        ;;
    add-lan-ip)
        # 快捷命令：自动添加局域网 IP
        lan_ip=$(hostname -I 2>/dev/null | awk '{print $1}')
        if [ -z "$lan_ip" ]; then
            error "无法检测局域网 IP"; exit 1
        fi
        current=$(env_get "CORS_ORIGINS")
        new_cors=$(python3 -c "
import json
try:
    origins = json.loads('''$current''')
    if not isinstance(origins, list):
        origins = []
except Exception:
    origins = []
new = 'http://$lan_ip:3000'
if new not in origins:
    origins.append(new)
print(json.dumps(origins, ensure_ascii=False))
" 2>/dev/null)
        if [ -n "$new_cors" ]; then
            env_set "CORS_ORIGINS" "$new_cors"
            ok "CORS 已更新: $new_cors"
        fi
        ;;
    apply)              apply_config ;;
    help|--help|-h)
        echo "用法: $0 [show|set-mode|add-lan-ip|apply|menu]"
        echo ""
        echo "  show         查看当前配置"
        echo "  set-mode     切换运行模式 (dev/prod)"
        echo "  add-lan-ip   自动添加局域网IP到CORS白名单"
        echo "  apply        根据 .env 生成 docker-compose.override.yml"
        echo "  menu         交互式菜单（默认）"
        ;;
    *)
        error "未知命令: $1"
        exit 1
        ;;
esac
