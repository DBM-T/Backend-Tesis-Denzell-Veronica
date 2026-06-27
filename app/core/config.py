from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "CALEAND SAC Backend"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    port: int = Field(default=8000, alias="PORT")

    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_anon_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY")
    )
    supabase_service_role_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY")
    )
    supabase_jwt_secret: str | None = Field(default=None, alias="SUPABASE_JWT_SECRET")
    supabase_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_JWKS_URL"),
    )

    oc_limite_aprobacion_gerencia: Decimal = Field(
        default=Decimal("1500.00"),
        alias="OC_LIMITE_APROBACION_GERENCIA",
    )
    ml_models_dir: Path = Field(default=Path("app/ml/models"), alias="ML_MODELS_DIR")
    reports_bucket: str = Field(default="reports", alias="REPORTS_BUCKET")
    auth_rate_limit_per_minute: int = Field(default=5, alias="AUTH_RATE_LIMIT_PER_MINUTE")
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        alias="CORS_ORIGINS",
    )

    @field_validator("cors_origins_raw", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> str:
        if isinstance(value, list):
            return ",".join(value)
        if not value:
            return "*"
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
