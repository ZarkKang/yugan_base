import shutil
import os
from datetime import datetime, timedelta
from typing import Optional, List
from pathlib import Path
import json
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..core.database import engine, Base
import logging

logger = logging.getLogger(__name__)


class BackupService:
    """数据备份与恢复服务"""
    
    def __init__(self, backup_dir: str = "./backups"):
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)
    
    def create_backup(self, db: Session, include_data: bool = True) -> dict:
        """创建完整备份"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.backup_dir / f"backup_{timestamp}"
        backup_path.mkdir(exist_ok=True)
        
        result = {
            'timestamp': timestamp,
            'path': str(backup_path),
            'status': 'in_progress'
        }
        
        try:
            # 备份数据库结构
            self._backup_database_schema(backup_path)
            
            # 备份数据（可选）
            if include_data:
                self._backup_database_data(db, backup_path)
            
            # 备份文件
            self._backup_files(backup_path)
            
            # 创建备份元数据
            metadata = {
                'version': '1.0',
                'created_at': datetime.now().isoformat(),
                'include_data': include_data,
                'tables': self._get_table_list()
            }
            
            with open(backup_path / 'metadata.json', 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            result['status'] = 'success'
            logger.info(f"Backup created successfully: {backup_path}")
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            logger.error(f"Backup failed: {e}")
        
        return result
    
    def _backup_database_schema(self, backup_path: Path):
        """备份数据库结构"""
        schema_path = backup_path / 'schema.sql'
        
        # 使用SQLAlchemy导出DDL
        with engine.connect() as conn:
            # 这是一个简化实现，生产环境建议使用pg_dump
            pass
    
    def _backup_database_data(self, db: Session, backup_path: Path):
        """备份数据"""
        data_path = backup_path / 'data'
        data_path.mkdir(exist_ok=True)
        
        for table in Base.metadata.sorted_tables:
            try:
                result = db.execute(text(f"SELECT * FROM {table.name}"))
                rows = result.fetchall()
                
                if rows:
                    table_data = []
                    for row in rows:
                        table_data.append(dict(row._mapping))
                    
                    with open(data_path / f"{table.name}.json", 'w', encoding='utf-8') as f:
                        json.dump(table_data, f, ensure_ascii=False, indent=2, default=str)
            except Exception as e:
                logger.warning(f"Could not backup table {table.name}: {e}")
    
    def _backup_files(self, backup_path: Path):
        """备份上传的文件"""
        files_dir = Path("./uploads")
        if files_dir.exists():
            shutil.copytree(files_dir, backup_path / 'files', dirs_exist_ok=True)
    
    def _get_table_list(self) -> List[str]:
        return [table.name for table in Base.metadata.sorted_tables]
    
    def list_backups(self) -> List[dict]:
        """列出所有备份"""
        backups = []
        
        for backup_dir in sorted(self.backup_dir.iterdir(), reverse=True):
            if backup_dir.is_dir():
                metadata_path = backup_dir / 'metadata.json'
                
                if metadata_path.exists():
                    try:
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                        
                        backups.append({
                            'name': backup_dir.name,
                            'path': str(backup_dir),
                            'metadata': metadata
                        })
                    except Exception:
                        pass
        
        return backups
    
    def restore_backup(self, backup_name: str, db: Session) -> dict:
        """从备份恢复"""
        backup_path = self.backup_dir / backup_name
        
        if not backup_path.exists():
            return {'status': 'failed', 'error': 'Backup not found'}
        
        result = {
            'backup': backup_name,
            'status': 'in_progress'
        }
        
        try:
            metadata_path = backup_path / 'metadata.json'
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # 恢复数据
            data_path = backup_path / 'data'
            if data_path.exists() and metadata.get('include_data'):
                self._restore_data(data_path, db)
            
            # 恢复文件
            files_backup = backup_path / 'files'
            if files_backup.exists():
                target_files = Path("./uploads")
                shutil.copytree(files_backup, target_files, dirs_exist_ok=True)
            
            result['status'] = 'success'
            logger.info(f"Restore completed successfully")
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            logger.error(f"Restore failed: {e}")
        
        return result
    
    def _restore_data(self, data_path: Path, db: Session):
        """恢复数据"""
        for table in Base.metadata.sorted_tables:
            file_path = data_path / f"{table.name}.json"
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        table_data = json.load(f)
                    
                    # 清空表
                    db.execute(text(f"TRUNCATE TABLE {table.name} CASCADE"))
                    
                    # 重新插入
                    for row in table_data:
                        db.execute(table.insert().values(row))
                    
                    db.commit()
                except Exception as e:
                    logger.warning(f"Could not restore table {table.name}: {e}")
                    db.rollback()
    
    def delete_old_backups(self, keep_days: int = 30):
        """删除旧备份"""
        cutoff = datetime.now() - timedelta(days=keep_days)
        
        for backup_dir in self.backup_dir.iterdir():
            if backup_dir.is_dir():
                try:
                    # 从目录名解析时间
                    if backup_dir.name.startswith('backup_'):
                        try:
                            timestamp_str = backup_dir.name.replace('backup_', '')
                            backup_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                            if backup_time < cutoff:
                                shutil.rmtree(backup_dir)
                        except ValueError:
                            continue
                except Exception as e:
                    logger.warning(f"Could not delete {backup_dir}: {e}")
