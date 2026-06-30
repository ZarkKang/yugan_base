
# 域感智能 - Makefile

.PHONY: help install build run clean stop logs drone warehouse gateway desktop docker

# 帮助信息
help:
	@echo "域感智能 - 可用命令:"
	@echo ""
	@echo "  install      - 安装所有依赖"
	@echo "  drone        - 启动无人机数据系统 (端口 8000)"
	@echo "  warehouse    - 启动仓库巡检系统 (端口 8001)"
	@echo "  gateway      - 启动 API 网关 (端口 8080)"
	@echo "  desktop      - 启动桌面应用"
	@echo "  docker       - 使用 Docker 启动所有服务"
	@echo "  stop         - 停止 Docker 服务"
	@echo "  logs         - 查看 Docker 日志"
	@echo "  clean        - 清理缓存文件"
	@echo ""

# 安装所有依赖
install:
	@echo "正在安装 Python 依赖..."
	cd drone/drone-db-prototype/backend && pip install -r requirements.txt
	cd station/warehouse-inspection-system/backend && pip install -r requirements.txt
	cd app/api-gateway && pip install -r requirements.txt
	@echo "正在安装 Node.js 依赖..."
	cd app/desktop-app && npm install
	@echo "依赖安装完成！"

# 启动无人机数据系统
drone:
	cd drone/drone-db-prototype/backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 启动仓库巡检系统
warehouse:
	cd station/warehouse-inspection-system/backend && \
	if [ -d "venv" ]; then source venv/bin/activate; fi && \
	uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload

# 启动 API 网关
gateway:
	cd app/api-gateway && uvicorn main:app --host 0.0.0.0 --port 8080 --reload

# 启动桌面应用
desktop:
	cd app/desktop-app && npm run dev

# Docker 相关
docker:
	docker-compose up -d

stop:
	docker-compose down

logs:
	docker-compose logs -f

# 清理缓存
clean:
	@echo "正在清理缓存文件..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	rm -f drone/drone-db-prototype/backend/yugan.db
	rm -rf drone/drone-db-prototype/backend/uploads/*
	@echo "清理完成！"
