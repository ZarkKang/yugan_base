"""
API路由 - 认证
=================
用户登录、token管理、权限验证
"""
from fastapi import APIRouter, Depends, HTTPException, status, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from ..db.database import get_db
from ..models.models import User
from ..core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    decode_access_token,
    ACCESS_TOKEN_EXPIRE_DAYS,
)
from ..schemas.schemas import (
    LoginRequest,
    LoginResponse,
    UserResponse,
    TokenData,
    APIResponse,
)

router = APIRouter(prefix="/auth", tags=["认证"])
security_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    """获取当前登录用户"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭证",
        )
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
        )
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已禁用",
        )
    return user


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    用户登录

    返回 JWT access_token 和用户信息。
    支持 remember_me 参数：True 时 token 有效期为 7 天。
    """
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已禁用",
        )

    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        remember_me=request.remember_me
    )
    user_data = UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
    )

    return LoginResponse(
        success=True,
        message="登录成功",
        access_token=access_token,
        token_type="bearer",
        user=user_data,
    )


@router.get("/me", response_model=APIResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return APIResponse(
        success=True,
        message="操作成功",
        data=UserResponse(
            id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            full_name=current_user.full_name,
            role=current_user.role,
            is_active=current_user.is_active,
        ),
    )


@router.post("/register", response_model=APIResponse)
def register(
    username: str = Form(...),
    password: str = Form(...),
    email: Optional[str] = Form(None),
    full_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """注册新用户"""
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )
    # 创建新用户
    hashed = get_password_hash(password)
    new_user = User(
        username=username,
        email=email,
        hashed_password=hashed,
        full_name=full_name,
        role="user",
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return APIResponse(success=True, message="注册成功", data={"id": new_user.id})


@router.post("/ensure-admin", response_model=APIResponse)
def ensure_admin_user(db: Session = Depends(get_db)):
    """确保 admin 用户存在且密码正确 — 统一登录兜底
    
    默认账号密码：admin / admin
    """
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if admin is None:
            admin = User(
                username="admin",
                email="admin@yugan.local",
                hashed_password=get_password_hash("admin"),
                full_name="系统管理员",
                role="admin",
                is_active=True,
            )
            db.add(admin)
        else:
            try:
                if not verify_password("admin", admin.hashed_password):
                    admin.hashed_password = get_password_hash("admin")
            except Exception:
                admin.hashed_password = get_password_hash("admin")
            if not admin.is_active:
                admin.is_active = True
        db.commit()
        return APIResponse(success=True, message="admin 用户已就绪（密码：admin）")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
