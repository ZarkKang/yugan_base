#!/bin/bash
# ============================================================
# 模拟无人机 - 一键启动脚本 (Linux)
# ============================================================
# 功能:
#   1. 自动创建/激活 Python 虚拟环境
#   2. 安装依赖 (requests, Pillow, qrcode)
#   3. 启动模拟无人机测试程序
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

# ── 颜色 ──────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════╗"
echo "║     模拟无人机 - 虚拟环境自动启动             ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ── 1. 检查 Python3 ───────────────────────────
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ 未找到 python3，请先安装 Python 3.10+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓${NC} Python 版本: ${PYTHON_VERSION}"

# ── 2. 创建虚拟环境 ────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${CYAN}→${NC} 创建虚拟环境: ${VENV_DIR}"
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} 虚拟环境已创建"
else
    echo -e "${GREEN}✓${NC} 虚拟环境已存在"
fi

# ── 3. 激活虚拟环境并安装依赖 ──────────────────
echo -e "${CYAN}→${NC} 安装依赖..."

"$PIP_BIN" install --quiet --upgrade pip 2>/dev/null || true

DEPS=("requests" "Pillow" "qrcode[pil]")
for dep in "${DEPS[@]}"; do
    echo -e "  ${CYAN}→${NC} 安装 ${dep}..."
    "$PIP_BIN" install --quiet "$dep" 2>/dev/null && {
        echo -e "  ${GREEN}✓${NC} ${dep}"
    } || {
        echo -e "  ${YELLOW}⚠${NC} ${dep} 安装失败，尝试继续..."
    }
done

echo -e "\n${GREEN}${BOLD}依赖安装完成!${NC}\n"

# ── 4. 运行模拟程序 ────────────────────────────
echo -e "${CYAN}${BOLD}启动模拟无人机测试程序...${NC}"
echo -e "${YELLOW}提示: 使用 --help 查看所有选项${NC}"
echo -e "${YELLOW}提示: 使用 --auto 一键执行完整测试流程${NC}"
echo ""

# 传递所有参数给模拟程序
"$PYTHON_BIN" "$SCRIPT_DIR/simulate_drone.py" "$@"

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "\n${GREEN}${BOLD}测试完成!${NC}"
else
    echo -e "\n${RED}${BOLD}测试异常退出 (exit code: ${EXIT_CODE})${NC}"
fi
exit $EXIT_CODE