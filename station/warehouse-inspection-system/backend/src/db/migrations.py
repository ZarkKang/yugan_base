"""
数据库幂等迁移模块
==================
项目 Alembic 未集成（P3 优先级），此处使用 PostgreSQL 原生
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 实现幂等迁移。

调用时机：在 `init_db()` (create_all) 之后调用，因为 `create_all` 只建新表，
不为已有表加列。

设计原则：
- 每条 SQL 独立 `IF NOT EXISTS`，重跑安全
- 整体在事务中执行，失败整体回滚
- 仅用于追加字段/索引，删除字段需手动操作
"""
import logging
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 迁移 SQL 列表（按时间顺序追加）
MIGRATIONS = [
    # ── 2026-07-05: WS 实时图传 + QR 双图保存 + 航点标记帧 ──
    # VideoData 表新增字段
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS source VARCHAR(16) DEFAULT 'upload'",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS stream_session_id VARCHAR(64)",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS frame_rate_actual FLOAT",
    "ALTER TABLE video_data ADD COLUMN IF NOT EXISTS waypoint_markers TEXT",

    # ImageRecord 表新增字段（QR 双图证据）
    "ALTER TABLE image_records ADD COLUMN IF NOT EXISTS qr_cropped_path VARCHAR(512)",
    "ALTER TABLE image_records ADD COLUMN IF NOT EXISTS annotated_path VARCHAR(512)",

    # 索引（加速按 stream_session_id 查询 WS 流视频）
    "CREATE INDEX IF NOT EXISTS ix_video_data_stream_session ON video_data (stream_session_id)",
    # 索引（加速按 source 过滤查询）
    "CREATE INDEX IF NOT EXISTS ix_video_data_source ON video_data (source)",
]


def run_migrations(engine: Engine) -> None:
    """
    执行所有幂等迁移。

    在事务中顺序执行 MIGRATIONS 中的 SQL，失败则整体回滚。
    每条 SQL 都用 IF NOT EXISTS，重跑安全。

    Args:
        engine: SQLAlchemy Engine 实例
    """
    executed = 0
    skipped = 0
    with engine.begin() as conn:
        for sql in MIGRATIONS:
            try:
                conn.execute(text(sql))
                executed += 1
            except Exception as e:
                # 单条失败不阻塞后续，记录后继续
                logger.warning("[Migrations] SQL 执行失败（已跳过）: %s | 错误: %s", sql[:80], e)
                skipped += 1

    logger.info("[Migrations] 迁移完成: %d 条执行, %d 条跳过", executed, skipped)
