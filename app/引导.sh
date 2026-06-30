#!/bin/bash
# ========================================
#  域感智能 - 引导菜单（兼容性包装器）
#  实际调用: ./启动.sh menu
# ========================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/启动.sh" menu