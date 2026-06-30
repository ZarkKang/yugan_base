from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_active_user
from ..models.user import User
from ..models.image_data import ImageData
from ..schemas.image_data import ImageDataCreate, ImageDataUpdate, ImageDataResponse

router = APIRouter(prefix="/api/images", tags=["图片数据"])


@router.post("/", response_model=ImageDataResponse)
async def upload_image(
    file: UploadFile = File(...),
    drone_id: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    altitude: Optional[float] = None,
    description: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    import os
    import uuid
    from ..core.config import settings
    
    upload_dir = os.path.join(settings.UPLOAD_DIR, "images")
    os.makedirs(upload_dir, exist_ok=True)
    
    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(upload_dir, unique_filename)
    
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
        file_size = len(content)
    
    image_data = ImageData(
        file_name=file.filename or unique_filename,
        file_path=file_path,
        file_size=file_size,
        drone_id=drone_id,
        latitude=latitude,
        longitude=longitude,
        altitude=altitude,
        description=description
    )
    db.add(image_data)
    db.commit()
    db.refresh(image_data)
    return image_data


@router.get("/", response_model=List[ImageDataResponse])
def list_images(
    skip: int = 0,
    limit: int = 100,
    drone_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    query = db.query(ImageData)
    if drone_id:
        query = query.filter(ImageData.drone_id == drone_id)
    return query.order_by(ImageData.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{image_id}", response_model=ImageDataResponse)
def get_image(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    image = db.query(ImageData).filter(ImageData.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    return image


@router.delete("/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    image = db.query(ImageData).filter(ImageData.id == image_id).first()
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    
    import os
    if os.path.exists(image.file_path):
        os.remove(image.file_path)
    
    db.delete(image)
    db.commit()
    return {"message": "图片已删除"}
