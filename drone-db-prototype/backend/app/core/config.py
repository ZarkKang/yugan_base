from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database — 与仓库巡检系统共用 PostgreSQL
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433  # 自建 PostgreSQL 端口
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "warehouse_inspection"
    DATABASE_URL: str = ""  # 留空则自动生成

    # Security — 统一认证配置（与仓库巡检系统共享）
    SECRET_KEY: str = "yugan-unified-secret-key-2026-shared-across-systems"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时（默认）
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7           # 7天（记住登录状态）

    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_VIDEO_SIZE: int = 500000000  # 500MB
    MAX_IMAGE_SIZE: int = 50000000    # 50MB

    def model_post_init(self, _context):
        """自动生成 PostgreSQL 连接 URL"""
        if not self.DATABASE_URL:
            object.__setattr__(self, "DATABASE_URL",
                f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
