# 引导菜单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 `引导.sh` 终端交互式菜单脚本，覆盖部署、管理、测试、维护四大功能模块。

**Architecture:** 独立 Bash 脚本，两级 `select` 菜单结构，通过 `source 启动.sh` 复用现有函数，运行模式通过 `.mode.conf` 持久化。

**Tech Stack:** Bash, select, 复用启动.sh 函数

---

### Task 1: 创建基础框架与主菜单

**Files:**
- Create: `引导.sh`
- Create: `.mode.conf`

- [ ] **Step 1: 创建基础框架、颜色变量、工具函数和主菜单**

创建 `引导.sh`，包含：
- 颜色变量（复用启动.sh 格式）
- 模式配置读写函数（`.mode.conf`）
- 主菜单 `select` 循环
- `source 启动.sh` 复用基础函数

```bash
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
        docker) echo "纯Docker模式" ;;
        local)  echo "纯本地模式" ;;
        hybrid) echo "混合模式" ;;
        *)      echo "未知模式" ;;
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
    echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║        域感智能 - 系统引导菜单           ║${NC}"
    echo -e "${CYAN}║        运行模式: [${mode_label}]         ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
    echo ""
}

press_enter() {
    echo -e "${YELLOW}按回车键继续...${NC}"
    read -r
}

# ── 主菜单 ────────────────────────────────────
main_menu() {
    while true; do
        show_banner
        echo "  1) 🚀 环境部署"
        echo "  2) ⚙️ 服务管理"
        echo "  3) 🧪 功能测试"
        echo "  4) 🔧 系统维护"
        echo "  5) ℹ️  系统信息"
        echo "  6) ❌ 退出"
        echo ""

        select choice in "环境部署" "服务管理" "功能测试" "系统维护" "系统信息" "退出"; do
            case "$choice" in
                "环境部署") deploy_menu; break ;;
                "服务管理") service_menu; break ;;
                "功能测试") test_menu; break ;;
                "系统维护") maintenance_menu; break ;;
                "系统信息") show_system_info; press_enter; break ;;
                "退出")
                    echo -e "${GREEN}再见!${NC}"
                    exit 0 ;;
                *) error "无效选择"; break ;;
            esac
        done
    done
}

# ── 子菜单占位 ────────────────────────────────
deploy_menu()    { warn "环境部署 - 待实现"; press_enter; }
service_menu()   { warn "服务管理 - 待实现"; press_enter; }
test_menu()      { warn "功能测试 - 待实现"; press_enter; }
maintenance_menu() { warn "系统维护 - 待实现"; press_enter; }
show_system_info() { warn "系统信息 - 待实现"; press_enter; }

# ── 入口 ──────────────────────────────────────
trap 'echo -e "\n${GREEN}已取消${NC}"; exit 0' INT
main_menu
```

- [ ] **Step 2: 创建 .mode.conf 默认配置**

```
MODE=hybrid
```

- [ ] **Step 3: 测试主菜单可运行**

在 WSL 中执行: `bash 引导.sh`
预期: 显示主菜单，选择 6 退出

- [ ] **Step 4: 提交**

```bash
git add 引导.sh .mode.conf
git commit -m "feat: 添加引导菜单基础框架和主菜单"
```

---

### Task 2: 实现环境部署子菜单

**Files:**
- Modify: `引导.sh` (替换 deploy_menu 函数)

- [ ] **Step 1: 替换 deploy_menu 函数**

```bash
deploy_menu() {
    while true; do
        echo -e "${BOLD}🚀 环境部署${NC}"
        echo ""
        echo "  1) 快速部署（全自动）"
        echo "  2) 仅检测环境"
        echo "  3) 安装系统依赖"
        echo "  4) 初始化数据库"
        echo "  5) 配置 PiP 镜像源"
        echo "  6) ⚙️ 设置运行模式"
        echo "  7) ← 返回主菜单"
        echo ""

        select choice in "快速部署" "检测环境" "安装依赖" "初始化数据库" "配置镜像源" "设置运行模式" "返回"; do
            case "$choice" in
                "快速部署")   quick_deploy; break ;;
                "检测环境")   check_environment; press_enter; break ;;
                "安装依赖")   install_dependencies; press_enter; break ;;
                "初始化数据库") init_database; press_enter; break ;;
                "配置镜像源")  config_pip_mirror; press_enter; break ;;
                "设置运行模式") select_mode; press_enter; break ;;
                "返回")        return ;;
                *)            error "无效选择"; break ;;
            esac
        done
    done
}
```

- [ ] **Step 2: 添加各子函数**

```bash
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
    echo "  1) 清华源 (推荐)"
    echo "  2) 阿里云源"
    echo "  3) 官方 PyPI"
    echo "  4) 返回"
    echo ""
    select choice in "清华源" "阿里云" "官方" "返回"; do
        case "$choice" in
            "清华源")  export PIP_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"; ok "已设置为清华源"; break ;;
            "阿里云")  export PIP_MIRROR="https://mirrors.aliyun.com/pypi/simple/"; ok "已设置为阿里云源"; break ;;
            "官方")    unset PIP_MIRROR; ok "已设置为官方源"; break ;;
            "返回")    break ;;
            *)        error "无效选择"; break ;;
        esac
    done
}

select_mode() {
    echo -e "${BOLD}设置运行模式${NC}"
    echo ""
    echo "当前模式: $(get_mode_label)"
    echo ""
    echo "  1) 🐳 纯 Docker 模式"
    echo "     - 所有服务通过 docker-compose 运行"
    echo "  2) 💻 纯本地模式"
    echo "     - PostgreSQL/Redis/后端全部本地运行"
    echo "  3) 🔀 混合模式（推荐）"
    echo "     - 基础设施Docker，后端本地运行"
    echo "  4) 返回"
    echo ""
    select choice in "Docker模式" "本地模式" "混合模式" "返回"; do
        case "$choice" in
            "Docker模式") set_mode "docker"; break ;;
            "本地模式")   set_mode "local"; break ;;
            "混合模式")   set_mode "hybrid"; break ;;
            "返回")       break ;;
            *)            error "无效选择"; break ;;
        esac
    done
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
```

- [ ] **Step 3: 测试环境部署菜单**

在 WSL 中执行: `bash 引导.sh` → 选择 1
预期: 各子菜单正常显示和执行

- [ ] **Step 4: 提交**

```bash
git add 引导.sh
git commit -m "feat: 实现环境部署子菜单"
```

---

### Task 3: 实现服务管理子菜单

**Files:**
- Modify: `引导.sh` (替换 service_menu 函数)

- [ ] **Step 1: 替换 service_menu 函数并添加实现**

```bash
service_menu() {
    while true; do
        echo -e "${BOLD}⚙️ 服务管理${NC}"
        echo "  当前模式: $(get_mode_label)"
        echo ""
        echo "  1) 🚀 启动所有服务"
        echo "  2) 停止所有服务"
        echo "  3) 重启所有服务"
        echo "  4) 查看服务状态"
        echo "  5) 查看日志"
        echo "  6) 启动单个服务"
        echo "  7) 停止单个服务"
        echo "  8) 🔄 切换运行模式"
        echo "  9) ← 返回主菜单"
        echo ""

        select choice in "启动所有" "停止所有" "重启所有" "查看状态" "查看日志" "启动单个" "停止单个" "切换模式" "返回"; do
            case "$choice" in
                "启动所有")   bash "$SCRIPT_DIR/启动.sh" start; press_enter; break ;;
                "停止所有")   bash "$SCRIPT_DIR/启动.sh" stop; press_enter; break ;;
                "重启所有")   bash "$SCRIPT_DIR/启动.sh" restart; press_enter; break ;;
                "查看状态")   bash "$SCRIPT_DIR/启动.sh" status; press_enter; break ;;
                "查看日志")   view_logs; break ;;
                "启动单个")   start_single_service; press_enter; break ;;
                "停止单个")   stop_single_service; press_enter; break ;;
                "切换模式")   select_mode; press_enter; break ;;
                "返回")       return ;;
                *)            error "无效选择"; break ;;
            esac
        done
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
    echo ""
    select choice in "无人机数据系统 (8000)" "仓库巡检系统 (8001)" "API网关 (8080)" "返回"; do
        case "$choice" in
            "无人机数据系统 (8000)")
                MODE=$(get_mode) bash "$SCRIPT_DIR/启动.sh" start-drone 2>/dev/null || \
                    bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start"
                break ;;
            "仓库巡检系统 (8001)")
                bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start-warehouse" 2>/dev/null || \
                    bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start"
                break ;;
            "API网关 (8080)")
                bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start-gateway" 2>/dev/null || \
                    bash -c "cd '$SCRIPT_DIR' && MODE=$(get_mode) ./启动.sh start"
                break ;;
            "返回") return ;;
            *) error "无效选择"; break ;;
        esac
    done
}

stop_single_service() {
    local mode="$(get_mode)"
    echo -e "${BOLD}停止单个服务${NC}"
    echo ""
    select choice in "无人机数据系统 (8000)" "仓库巡检系统 (8001)" "API网关 (8080)" "返回"; do
        case "$choice" in
            "无人机数据系统 (8000)")
                pkill -f "uvicorn.*port=8000" 2>/dev/null && ok "已停止" || warn "未运行"
                break ;;
            "仓库巡检系统 (8001)")
                pkill -f "uvicorn.*port=8001" 2>/dev/null && ok "已停止" || warn "未运行"
                break ;;
            "API网关 (8080)")
                pkill -f "uvicorn.*port=8080" 2>/dev/null && ok "已停止" || warn "未运行"
                break ;;
            "返回") return ;;
            *) error "无效选择"; break ;;
        esac
    done
}
```

- [ ] **Step 2: 提交**

```bash
git add 引导.sh
git commit -m "feat: 实现服务管理子菜单"
```

---

### Task 4: 实现功能测试子菜单

**Files:**
- Modify: `引导.sh` (替换 test_menu 函数)

- [ ] **Step 1: 替换 test_menu 函数并添加实现**

```bash
test_menu() {
    while true; do
        echo -e "${BOLD}🧪 功能测试${NC}"
        echo ""
        echo "  1) 运行无人机模拟器"
        echo "  2) 测试 RFID 读卡器"
        echo "  3) 测试 QR 码识别"
        echo "  4) API 连通性测试"
        echo "  5) 数据库连通性测试"
        echo "  6) ← 返回主菜单"
        echo ""

        select choice in "无人机模拟" "RFID测试" "QR测试" "API测试" "数据库测试" "返回"; do
            case "$choice" in
                "无人机模拟")  run_drone_simulator; press_enter; break ;;
                "RFID测试")    test_rfid; press_enter; break ;;
                "QR测试")      test_qr; press_enter; break ;;
                "API测试")     test_api_connectivity; press_enter; break ;;
                "数据库测试")  test_database; press_enter; break ;;
                "返回")        return ;;
                *)             error "无效选择"; break ;;
            esac
        done
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
    if command -v python3 &>/dev/null; then
        info "尝试连接 RFID 读卡器..."
        python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/warehouse-inspection-system/backend/src')
try:
    from hardware.rfid_reader import RFIDReader
    reader = RFIDReader()
    if reader.connect():
        print('RFID 连接成功')
        tag = reader.read_tag()
        if tag:
            print(f'读取到标签: {tag}')
        else:
            print('未读取到标签')
        reader.disconnect()
    else:
        print('RFID 连接失败')
except Exception as e:
    print(f'错误: {e}')
"
    else
        error "Python3 未安装"
    fi
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
    local endpoints=(
        "http://localhost:8000/health:无人机数据系统"
        "http://localhost:8001/health:仓库巡检系统"
        "http://localhost:8080/health:API网关"
        "http://localhost:8001/api/v1/dashboard/overview:看板API"
    )

    for entry in "${endpoints[@]}"; do
        local url="${entry%%:*}"
        local name="${entry##*:}"
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
        if [ "$http_code" = "200" ]; then
            ok "$name ($url) → $http_code"
        elif [ -z "$http_code" ]; then
            error "$name ($url) → 无法连接"
        else
            warn "$name ($url) → $http_code"
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
```

- [ ] **Step 2: 提交**

```bash
git add 引导.sh
git commit -m "feat: 实现功能测试子菜单"
```

---

### Task 5: 实现系统维护子菜单与系统信息

**Files:**
- Modify: `引导.sh` (替换 maintenance_menu 和 show_system_info 函数)

- [ ] **Step 1: 替换 maintenance_menu 函数并添加实现**

```bash
maintenance_menu() {
    while true; do
        echo -e "${BOLD}🔧 系统维护${NC}"
        echo ""
        echo "  1) 清理虚拟环境"
        echo "  2) 清理日志文件"
        echo "  3) 重置数据库"
        echo "  4) 更新系统代码"
        echo "  5) 检查端口占用"
        echo "  6) ← 返回主菜单"
        echo ""

        select choice in "清理虚拟环境" "清理日志" "重置数据库" "更新代码" "检查端口" "返回"; do
            case "$choice" in
                "清理虚拟环境") clean_venvs; press_enter; break ;;
                "清理日志")     clean_logs; press_enter; break ;;
                "重置数据库")   reset_database; press_enter; break ;;
                "更新代码")     update_code; press_enter; break ;;
                "检查端口")     check_ports; press_enter; break ;;
                "返回")         return ;;
                *)              error "无效选择"; break ;;
            esac
        done
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
    echo -e "${BOLD}⚠️  重置数据库${NC}"
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
```

- [ ] **Step 2: 替换 show_system_info 函数**

```bash
show_system_info() {
    echo -e "${BOLD}ℹ️  系统信息${NC}"
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
```

- [ ] **Step 3: 提交**

```bash
git add 引导.sh
git commit -m "feat: 实现系统维护和系统信息子菜单"
```

---

### Task 6: 最终测试与文档

**Files:**
- Modify: `引导.sh` (最终确认)
- Modify: `docs/开发进度_2026-06-11.md` (记录新功能)

- [ ] **Step 1: 完整流程测试**

在 WSL 中执行:
```bash
bash 引导.sh
```
测试所有子菜单：
- 环境部署 → 检测环境、设置模式
- 服务管理 → 启动所有、查看状态
- 功能测试 → API测试、数据库测试
- 系统维护 → 检查端口
- 系统信息
- 退出

- [ ] **Step 2: 更新开发进度文档**

在 `docs/开发进度_2026-06-11.md` 中添加：
```markdown
### 7. 引导菜单
- 创建 `引导.sh` 终端交互式菜单
- 四大功能模块: 环境部署/服务管理/功能测试/系统维护
- 支持三种运行模式: Docker/本地/混合
- 模式配置持久化到 `.mode.conf`
```

- [ ] **Step 3: 最终提交**

```bash
git add 引导.sh docs/开发进度_2026-06-11.md
git commit -m "feat: 引导菜单完成，记录开发进度"
```
