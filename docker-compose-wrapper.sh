#!/bin/bash
# Docker Compose Wrapper Script
# 将docker compose v2插件包装为可独立使用的命令

COMPOSE_PLUGIN="/tmp/docker-compose/usr/libexec/docker/cli-plugins/docker-compose"

# 如果插件不存在，自动下载并解压
if [ ! -f "$COMPOSE_PLUGIN" ]; then
    echo "[docker-compose-wrapper] 插件不存在，正在下载..."
    mkdir -p /tmp/docker-compose
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
fi

# 执行compose命令
exec "$COMPOSE_PLUGIN" "$@"