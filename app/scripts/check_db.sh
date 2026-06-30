#!/bin/bash
echo "=== 1. 8001 服务是否在跑(对照) ==="
pgrep -af 'uvicorn.*8001' || echo '8001 也未启动'
echo
echo "=== 2. postgres 超级用户连接 ==="
sudo -u postgres psql -c 'SELECT 1 AS ok;' 2>&1 | head -3
echo
echo "=== 3. 查看 warehouse_admin 用户 ==="
sudo -u postgres psql -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname='warehouse_admin';" 2>&1
echo
echo "=== 4. 查看 warehouse_inspection 数据库 ==="
sudo -u postgres psql -c "SELECT datname FROM pg_database WHERE datname='warehouse_inspection';" 2>&1
echo
echo "=== 5. users 表是否存在 ==="
sudo -u postgres psql -d warehouse_inspection -c "\dt users" 2>&1 | head -10
