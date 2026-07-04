"""
API路由 - 货架管理

货架数据由无人机端 shelves.yaml 推送同步（POST /api/v1/gateway/shelves/sync）。
基站端保留手动管理和编辑能力，但货架号(shelf_code)来源于无人机端。
删除采用软删除（标记archived），保留历史数据关联。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from ..db.database import get_db
from ..models.models import Shelf, User
from ..schemas.schemas import (
    ShelfCreate,
    ShelfUpdate,
    ShelfResponse,
    APIResponse
)
from .auth import get_current_user

router = APIRouter(prefix="/shelves", tags=["货架管理"])


@router.post("/", response_model=APIResponse)
def create_shelf(
    shelf: ShelfCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """手动注册新货架（仅当无人机端未提供时使用）"""
    # 仅检查活跃货架，已归档的shelf_code可重新使用
    existing = db.query(Shelf).filter(
        Shelf.shelf_code == shelf.shelf_code,
        Shelf.archived_at.is_(None)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="货架编号已存在（活跃状态）")
    new_shelf = Shelf(**shelf.model_dump())
    db.add(new_shelf)
    db.commit()
    db.refresh(new_shelf)
    return APIResponse(success=True, message="创建成功", data={"id": new_shelf.id})


@router.get("/", response_model=List[ShelfResponse])
def list_shelves(
    zone: Optional[str] = None,
    status: Optional[str] = None,
    include_archived: bool = Query(False, description="是否包含已归档货架"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取货架列表（默认不含已归档）"""
    query = db.query(Shelf)
    if zone:
        query = query.filter(Shelf.zone == zone)
    if status:
        query = query.filter(Shelf.status == status)
    elif not include_archived:
        query = query.filter(Shelf.archived_at.is_(None))
    return query.order_by(Shelf.created_at.desc()).all()


@router.get("/{shelf_id}", response_model=ShelfResponse)
def get_shelf(
    shelf_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取货架详情"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    return shelf


@router.patch("/{shelf_id}", response_model=APIResponse)
def update_shelf(
    shelf_id: int,
    update: ShelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """更新货架信息（仅基站端字段：zone/qr_code/status等）"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(shelf, key, value)
    db.commit()
    return APIResponse(success=True, message="更新成功")


@router.delete("/{shelf_id}", response_model=APIResponse)
def delete_shelf(
    shelf_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """软删除货架（标记为archived，保留历史数据关联）"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    if shelf.archived_at is not None:
        raise HTTPException(status_code=400, detail="货架已归档")
    shelf.status = "archived"
    shelf.archived_at = datetime.utcnow()
    db.commit()
    return APIResponse(success=True, message="货架已归档（软删除），历史数据保留")
