#!/bin/bash
echo "=== ALTER TABLE automated_tasks ADD COLUMN target_shelves ==="
sudo -u postgres psql -d warehouse_inspection -c "ALTER TABLE automated_tasks ADD COLUMN IF NOT EXISTS target_shelves TEXT;" 2>&1
echo
echo "=== 验证字段 ==="
sudo -u postgres psql -d warehouse_inspection -c "\d automated_tasks" 2>&1 | grep -E "target_shelves|Column|----"
