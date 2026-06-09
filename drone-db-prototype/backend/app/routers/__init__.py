from .auth import router as auth_router
from .users import router as users_router
from .skus import router as skus_router
from .drones import router as drones_router
from .videos import router as videos_router
from .images import router as images_router
from .rfid import router as rfid_router
from .admin import router as admin_router

__all__ = [
    "auth_router",
    "users_router",
    "skus_router",
    "drones_router",
    "videos_router",
    "images_router",
    "rfid_router",
    "admin_router",
]
