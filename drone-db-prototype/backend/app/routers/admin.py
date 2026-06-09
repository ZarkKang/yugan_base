from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..core.database import get_db
from ..core.permissions import require_permission, Permission
from ..models.user import User
from ..core.security import get_current_active_user
from ..services.qr_service import QRCodeService
from ..services.backup_service import BackupService
from ..services.tracing_service import tracing_service
import logging

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.post("/qr/process")
async def process_qr_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.IMAGE_WRITE)),
    db: Session = Depends(get_db)
):
    """处理图片中的二维码"""
    try:
        image_data = await file.read()
        
        # 处理图像
        result = QRCodeService.process_image_for_database(image_data)
        
        # 保存裁切后的二维码图像
        if result['has_qr']:
            for cropped in result['cropped_images']:
                # 这里可以保存到数据库或文件系统
                pass
        
        return {
            'success': True,
            'data': result
        }
        
    except Exception as e:
        logger.error(f"QR processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/qr/detect")
async def detect_qr_from_url(
    image_url: str,
    current_user: User = Depends(require_permission(Permission.IMAGE_READ)),
    db: Session = Depends(get_db)
):
    """从URL检测二维码（需实现下载逻辑）"""
    return {'message': 'URL detection coming soon'}


@router.post("/backup/create")
async def create_backup(
    include_data: bool = True,
    current_user: User = Depends(require_permission(Permission.SYSTEM_BACKUP)),
    db: Session = Depends(get_db)
):
    """创建备份"""
    try:
        backup_service = BackupService()
        result = backup_service.create_backup(db, include_data=include_data)
        
        if result['status'] != 'success':
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Backup failed')
            )
        
        return result
        
    except Exception as e:
        logger.error(f"Backup creation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/backup/list")
async def list_backups(
    current_user: User = Depends(require_permission(Permission.SYSTEM_BACKUP)),
    db: Session = Depends(get_db)
):
    """列出所有备份"""
    try:
        backup_service = BackupService()
        backups = backup_service.list_backups()
        
        return {
            'success': True,
            'data': backups
        }
        
    except Exception as e:
        logger.error(f"List backups failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/backup/restore")
async def restore_backup(
    backup_name: str,
    current_user: User = Depends(require_permission(Permission.SYSTEM_RESTORE)),
    db: Session = Depends(get_db)
):
    """从备份恢复"""
    try:
        backup_service = BackupService()
        result = backup_service.restore_backup(backup_name, db)
        
        if result['status'] != 'success':
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get('error', 'Restore failed')
            )
        
        return result
        
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/tracing/list")
async def list_traces(
    limit: int = 100,
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
    db: Session = Depends(get_db)
):
    """列出追踪记录"""
    try:
        traces = tracing_service.query_traces()
        return {
            'success': True,
            'data': traces[:limit]
        }
    except Exception as e:
        logger.error(f"List traces failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/tracing/{trace_id}")
async def get_trace_details(
    trace_id: str,
    current_user: User = Depends(require_permission(Permission.SYSTEM_CONFIG)),
    db: Session = Depends(get_db)
):
    """获取追踪详情"""
    try:
        traces = tracing_service.get_trace_details(trace_id)
        return {
            'success': True,
            'data': traces
        }
    except Exception as e:
        logger.error(f"Get trace details failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
