from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.rfid_data import RFIDData
from ..schemas.rfid_data import RFIDDataCreate, RFIDDataUpdate, RFIDDataResponse

router = APIRouter(prefix="/api/rfid", tags=["RFID数据"])


@router.post("/", response_model=RFIDDataResponse)
def create_rfid_data(
    rfid: RFIDDataCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    # 检查RFID标签是否已存在
    existing = db.query(RFIDData).filter(RFIDData.rfid_tag == rfid.rfid_tag).first()
    if existing:
        raise HTTPException(status_code=400, detail="RFID标签已存在")
    
    db_rfid = RFIDData(**rfid.model_dump())
    db.add(db_rfid)
    db.commit()
    db.refresh(db_rfid)
    return db_rfid


@router.post("/batch", response_model=List[RFIDDataResponse])
def create_rfid_batch(
    rfid_list: List[RFIDDataCreate],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    created = []
    for rfid in rfid_list:
        existing = db.query(RFIDData).filter(RFIDData.rfid_tag == rfid.rfid_tag).first()
        if not existing:
            db_rfid = RFIDData(**rfid.model_dump())
            db.add(db_rfid)
            created.append(db_rfid)
    
    db.commit()
    for item in created:
        db.refresh(item)
    return created


@router.get("/", response_model=List[RFIDDataResponse])
def list_rfid_data(
    skip: int = 0,
    limit: int = 100,
    drone_id: Optional[int] = None,
    is_valid: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(RFIDData)
    if drone_id:
        query = query.filter(RFIDData.drone_id == drone_id)
    if is_valid is not None:
        query = query.filter(RFIDData.is_valid == is_valid)
    return query.order_by(RFIDData.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{rfid_id}", response_model=RFIDDataResponse)
def get_rfid_data(rfid_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    rfid = db.query(RFIDData).filter(RFIDData.id == rfid_id).first()
    if not rfid:
        raise HTTPException(status_code=404, detail="RFID数据不存在")
    return rfid


@router.put("/{rfid_id}", response_model=RFIDDataResponse)
def update_rfid_data(
    rfid_id: int,
    rfid_update: RFIDDataUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    rfid = db.query(RFIDData).filter(RFIDData.id == rfid_id).first()
    if not rfid:
        raise HTTPException(status_code=404, detail="RFID数据不存在")
    
    update_data = rfid_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(rfid, key, value)
    
    db.commit()
    db.refresh(rfid)
    return rfid


@router.delete("/{rfid_id}")
def delete_rfid_data(rfid_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    rfid = db.query(RFIDData).filter(RFIDData.id == rfid_id).first()
    if not rfid:
        raise HTTPException(status_code=404, detail="RFID数据不存在")
    db.delete(rfid)
    db.commit()
    return {"message": "RFID数据已删除"}
