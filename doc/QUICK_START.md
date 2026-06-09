
# 域感智能 - 本地快速启动指南

## 快速启动（不使用 Docker）

### 1. 启动仓库巡检系统（已有 venv）
```powershell
cd warehouse-inspection-system/backend
.\venv\Scripts\Activate.ps1
uvicorn src.main:app --host 0.0.0.0 --port 8001 --reload
```

### 2. 启动无人机数据系统（新终端）
```powershell
cd drone-db-prototype/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 启动 API 网关（新终端）
```powershell
cd api-gateway
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

---

## 简化配置（使用 SQLite）

为了避免 Docker 复杂性，我建议：

### 修改 drone-db-prototype/backend/app/core/config.py：
```python
DATABASE_URL: str = "sqlite:///./yugan.db"
```

这样就不需要 PostgreSQL 和 Redis 了！
