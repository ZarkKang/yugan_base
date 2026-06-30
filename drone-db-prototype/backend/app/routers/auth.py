"""
认证路由 - 无人机数据系统
统一认证配置 - 与仓库巡检系统共享 SECRET_KEY
"""
from fastapi import APIRouter, Depends, HTTPException, status, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Optional
from ..core.database import get_db
from ..core.security import verify_password, create_access_token, get_password_hash
from ..core.config import settings
from ..models.user import User
from ..schemas.user import UserCreate, UserResponse, Token
from ..init_data import ensure_admin

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """注册新用户"""
    # 检查用户是否存在
    db_user = db.query(User).filter(
        (User.username == user.username) | (User.email == user.email)
    ).first()
    if db_user:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")
    
    # 创建用户
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    remember_me: bool = Form(False),
    db: Session = Depends(get_db)
):
    """
    用户登录
    
    返回 JWT access_token。
    支持 remember_me 参数：True 时 token 有效期为 7 天。
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")
    
    access_token = create_access_token(
        data={"sub": user.username},
        remember_me=remember_me
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/ensure-admin")
def ensure_admin_user(db: Session = Depends(get_db)):
    """确保 admin 用户存在且密码正确 — 统一登录兜底
    
    默认账号密码：admin / admin
    """
    try:
        admin = ensure_admin(db)
        # 确保密码是 admin（统一认证）
        if not verify_password("admin", admin.hashed_password):
            admin.hashed_password = get_password_hash("admin")
        db.commit()
        return {"success": True, "message": "admin 用户已就绪（密码：admin）", "username": admin.username}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
