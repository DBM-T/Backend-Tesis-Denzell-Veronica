"""Variables de entorno y configuracion central."""
from functools import lru_cache

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = Field(validation_alias=AliasChoices("SUPABASE_URL"))
    supabase_publishable_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY")
    )
    supabase_secret_key: str = Field(
        validation_alias=AliasChoices("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_KEY")
    )
    supabase_jwks_url: str | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_JWKS_URL")
    )
    supabase_jwt_secret: str | None = Field(
        default=None, validation_alias=AliasChoices("SUPABASE_JWT_SECRET")
    )

    # PostgreSQL directo (asyncpg)
    database_url: str

    # Machine Learning
    ml_models_dir: str = "./ml_models"
    xgboost_model_path: str = "./ml_models/xgboost_demanda.joblib"
    xgboost_lead_time_model_path: str = "./ml_models/xgboost_lead_time.joblib"
    lead_time_raw_dataset_path: str = "./data/raw/dataset_lead_time.csv"
    lead_time_dataset_path: str = "./data/processed/dataset_lead_time_supabase.csv"
    lightgbm_model_path: str = "./ml_models/lightgbm_prioridad.joblib"

    # App
    app_env: str = "development"
    app_cors_origins: str = "http://localhost:3000"
    app_jwt_secret: str = "dev-local-auth-secret-change-me"
    app_jwt_exp_minutes: int = 60 * 12

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",")]

    @property
    def supabase_anon_key(self) -> str:
        return self.supabase_publishable_key

    @property
    def supabase_service_key(self) -> str:
        return self.supabase_secret_key

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
