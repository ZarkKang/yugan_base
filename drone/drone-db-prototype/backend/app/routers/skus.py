from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.sku import SKU
from ..schemas.sku import SKUCreate, SKUUpdate, SKUResponse

router = APIRouter(prefix="/api/skus", tags=["SKU管理"])


@router.post("/", response_model=SKUResponse)
def create_sku(sku: SKUCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    # 检查SKU编码是否已存在
    existing = db.query(SKU).filter(SKU.sku_code == sku.sku_code).first()
    if existing:
        raise HTTPException(status_code=400, detail="SKU编码已存在")
    
    db_sku = SKU(**sku.model_dump())
    db.add(db_sku)
    db.commit()
    db.refresh(db_sku)
    return db_sku


@router.get("/", response_model=List[SKUResponse])
def list_skus(
    skip: int = 0,
    limit: int = 100,
    category: Optional[str] = None,
    is_active: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(SKU)
    if category:
        query = query.filter(SKU.category == category)
    if is_active is not None:
        query = query.filter(SKU.is_active == is_active)
    return query.offset(skip).limit(limit).all()


@router.get("/{sku_id}", response_model=SKUResponse)
def get_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU不存在")
    return sku


@router.put("/{sku_id}", response_model=SKUResponse)
def update_sku(sku_id: int, sku_update: SKUUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU不存在")
    
    update_data = sku_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(sku, key, value)
    
    db.commit()
    db.refresh(sku)
    return sku


@router.delete("/{sku_id}")
def delete_sku(sku_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    sku = db.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU不存在")
    db.delete(sku)
    db.commit()
    return {"message": "SKU已删除"}
