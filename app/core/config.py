from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


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
    ml_models_dir: Path = Field(default=BASE_DIR / "app" / "ml" / "models", alias="ML_MODELS_DIR")
    ml_priority_high_threshold: float = Field(default=0.60, alias="ML_PRIORITY_HIGH_THRESHOLD")
    ml_priority_low_threshold: float = Field(default=0.40, alias="ML_PRIORITY_LOW_THRESHOLD")
    reports_bucket: str = Field(default="reports", alias="REPORTS_BUCKET")
    auth_rate_limit_per_minute: int = Field(default=5, alias="AUTH_RATE_LIMIT_PER_MINUTE")
    cors_origins_raw: str = Field(
        default="http://localhost:3000",
        alias="CORS_ORIGINS",
    )
    cors_origin_regex: str | None = Field(default=None, alias="CORS_ORIGIN_REGEX")

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

    @field_validator("ml_priority_high_threshold", "ml_priority_low_threshold")
    @classmethod
    def validate_probability_threshold(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("Los thresholds de prioridad ML deben estar entre 0 y 1.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
