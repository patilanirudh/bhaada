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

    def validate_for_production(self) -> None:
        """Fail fast at startup if production is configured unsafely."""
        if not self.is_production:
            return
        problems = []
        if len(self.jwt_secret) < 32 or "change-me" in self.jwt_secret:
            problems.append("JWT_SECRET must be a random string of 32+ characters")
        if not self.fernet_key:
            problems.append("FERNET_KEY must be set")
        if len(self.cron_secret) < 16 or self.cron_secret.startswith(("dev-", "change-me")):
            problems.append("CRON_SECRET must be a random string of 16+ characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true (HTTPS)")
        if not self.frontend_url.startswith("https://"):
            problems.append("FRONTEND_URL must use https://")
        if self.database_url.startswith("sqlite"):
            problems.append("DATABASE_URL must point to PostgreSQL, not SQLite")
        if self.storage_backend != "supabase":
            problems.append("STORAGE_BACKEND must be 'supabase' (local disk is wiped on free hosts)")
        if self.email_backend != "smtp":
            problems.append("EMAIL_BACKEND must be 'smtp'")
        if problems:
            raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(problems))

    @property
    def cors_origins(self) -> list[str]:
        origins = [self.frontend_url.rstrip("/")]
        origins += [o.strip().rstrip("/") for o in self.extra_cors_origins.split(",") if o.strip()]
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
