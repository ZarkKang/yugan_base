"""
API路由 - 货架管理
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..db.database import get_db
from ..models.models import Shelf
from ..schemas.schemas import (
    ShelfCreate,
    ShelfUpdate,
    ShelfResponse,
    APIResponse
)

router = APIRouter(prefix="/shelves", tags=["货架管理"])


@router.post("/", response_model=APIResponse)
def create_shelf(shelf: ShelfCreate, db: Session = Depends(get_db)):
    """注册新货架"""
    existing = db.query(Shelf).filter(Shelf.shelf_code == shelf.shelf_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="货架编号已存在")
    new_shelf = Shelf(**shelf.model_dump())
    db.add(new_shelf)
    db.commit()
    db.refresh(new_shelf)
    return APIResponse(success=True, message="创建成功", data={"id": new_shelf.id})


@router.get("/", response_model=List[ShelfResponse])
def list_shelves(
    zone: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """获取货架列表"""
    query = db.query(Shelf)
    if zone:
        query = query.filter(Shelf.zone == zone)
    if status:
        query = query.filter(Shelf.status == status)
    return query.all()


@router.get("/{shelf_id}", response_model=ShelfResponse)
def get_shelf(shelf_id: int, db: Session = Depends(get_db)):
    """获取货架详情"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    return shelf


@router.patch("/{shelf_id}", response_model=APIResponse)
def update_shelf(
    shelf_id: int,
    update: ShelfUpdate,
    db: Session = Depends(get_db)
):
    """更新货架信息"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(shelf, key, value)
    db.commit()
    return APIResponse(success=True, message="更新成功")


@router.delete("/{shelf_id}", response_model=APIResponse)
def delete_shelf(shelf_id: int, db: Session = Depends(get_db)):
    """删除货架"""
    shelf = db.query(Shelf).filter(Shelf.id == shelf_id).first()
    if not shelf:
        raise HTTPException(status_code=404, detail="货架不存在")
    db.delete(shelf)
    db.commit()
    return APIResponse(success=True, message="删除成功")
