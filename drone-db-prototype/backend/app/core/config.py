from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database (使用 SQLite 简化开发)
    DATABASE_URL: str = "sqlite:///./yugan.db"
    
    # Security
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_VIDEO_SIZE: int = 500000000  # 500MB
    MAX_IMAGE_SIZE: int = 50000000    # 50MB
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
