from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    environment: str = "development"  # development | production | test
    app_name: str = "Bhaada Rent Manager"
    database_url: str = "sqlite:///./rent.db"
    frontend_url: str = "http://localhost:5173"
    # Comma-separated extra allowed origins (optional)
    extra_cors_origins: str = ""

    # Security
    jwt_secret: str = "change-me-dev-only-secret-at-least-32-chars"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    # Fernet key (urlsafe base64, 32 bytes). Generate with:
    # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = ""
    cron_secret: str = "dev-cron-secret"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"  # lax when frontend proxies /api (recommended); none for cross-site

    # Storage
    storage_backend: str = "local"  # local | supabase
    local_upload_dir: str = "./uploads"
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_bucket: str = "rent-private"
    signed_url_seconds: int = 300

    # Email (system account, used for password reset & owner notifications fallback)
    email_backend: str = "smtp"  # smtp | console | memory
    system_gmail_address: str = ""
    system_gmail_app_password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465

    # Public registration rate limit
    registration_rate_limit: int = 10  # per IP per hour

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.frontend_url.rstrip("/")]
        origins += [o.strip().rstrip("/") for o in self.extra_cors_origins.split(",") if o.strip()]
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
