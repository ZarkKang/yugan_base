from fastapi import Depends, HTTPException, status
from typing import List, Set
from enum import Enum
from ..models.user import User
from .security import get_current_active_user


class Permission(str, Enum):
    """权限枚举"""
    # 用户管理
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_DELETE = "user:delete"
    
    # 无人机管理
    DRONE_READ = "drone:read"
    DRONE_WRITE = "drone:write"
    DRONE_DELETE = "drone:delete"
    
    # SKU管理
    SKU_READ = "sku:read"
    SKU_WRITE = "sku:write"
    SKU_DELETE = "sku:delete"
    
    # 数据管理
    VIDEO_READ = "video:read"
    VIDEO_WRITE = "video:write"
    IMAGE_READ = "image:read"
    IMAGE_WRITE = "image:write"
    RFID_READ = "rfid:read"
    RFID_WRITE = "rfid:write"
    
    # 巡检管理
    INSPECTION_READ = "inspection:read"
    INSPECTION_WRITE = "inspection:write"
    
    # 系统管理
    SYSTEM_BACKUP = "system:backup"
    SYSTEM_RESTORE = "system:restore"
    SYSTEM_CONFIG = "system:config"


# 角色常量
ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

# 角色权限映射
ROLE_PERMISSIONS = {
    ROLE_ADMIN: [
        Permission.USER_READ,
        Permission.USER_WRITE,
        Permission.USER_DELETE,
        Permission.DRONE_READ,
        Permission.DRONE_WRITE,
        Permission.DRONE_DELETE,
        Permission.SKU_READ,
        Permission.SKU_WRITE,
        Permission.SKU_DELETE,
        Permission.VIDEO_READ,
        Permission.VIDEO_WRITE,
        Permission.IMAGE_READ,
        Permission.IMAGE_WRITE,
        Permission.RFID_READ,
        Permission.RFID_WRITE,
        Permission.INSPECTION_READ,
        Permission.INSPECTION_WRITE,
        Permission.SYSTEM_BACKUP,
        Permission.SYSTEM_RESTORE,
        Permission.SYSTEM_CONFIG,
    ],
    ROLE_OPERATOR: [
        Permission.USER_READ,
        Permission.DRONE_READ,
        Permission.DRONE_WRITE,
        Permission.SKU_READ,
        Permission.SKU_WRITE,
        Permission.VIDEO_READ,
        Permission.VIDEO_WRITE,
        Permission.IMAGE_READ,
        Permission.IMAGE_WRITE,
        Permission.RFID_READ,
        Permission.RFID_WRITE,
        Permission.INSPECTION_READ,
        Permission.INSPECTION_WRITE,
    ],
    ROLE_VIEWER: [
        Permission.DRONE_READ,
        Permission.SKU_READ,
        Permission.VIDEO_READ,
        Permission.IMAGE_READ,
        Permission.RFID_READ,
        Permission.INSPECTION_READ,
    ],
}


def get_user_permissions(user: User) -> Set[Permission]:
    """获取用户的所有权限"""
    return set(ROLE_PERMISSIONS.get(user.role, []))


def has_permission(user: User, permission: Permission) -> bool:
    """检查用户是否有特定权限"""
    user_permissions = get_user_permissions(user)
    return permission in user_permissions


def require_permission(permission: Permission):
    """权限依赖器"""
    def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return current_user
    return dependency


def require_any_permission(*permissions: Permission):
    """需要任意一个权限"""
    def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        user_perms = get_user_permissions(current_user)
        if not any(p in user_perms for p in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(p for p in permissions)}"
            )
        return current_user
    return dependency


def require_all_permissions(*permissions: Permission):
    """需要所有权限"""
    def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        user_perms = get_user_permissions(current_user)
        if not all(p in user_perms for p in permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires all: {', '.join(p for p in permissions)}"
            )
        return current_user
    return dependency


def require_role(*roles: str):
    """需要特定角色"""
    def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: one of {', '.join(roles)}"
            )
        return current_user
    return dependency


# 便捷依赖
require_admin = require_role(ROLE_ADMIN)
require_operator_or_above = require_role(ROLE_ADMIN, ROLE_OPERATOR)
