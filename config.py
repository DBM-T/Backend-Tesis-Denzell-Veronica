"""
config.py — Variables de entorno y configuración central
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url:         str
    supabase_anon_key:    str
    supabase_service_key: str
    supabase_jwt_secret:  str

    # PostgreSQL directo (asyncpg)
    database_url: str

    # RNS
    rns_model_path:           str   = "./rns_module/weights/sasnn_v1.pt"
    rns_encoder_name:         str   = "paraphrase-multilingual-MiniLM-L12-v2"
    rns_similarity_threshold: float = 0.85
    rns_top_k:                int   = 5

    # App
    app_env:          str = "development"
    app_cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.app_cors_origins.split(",")]

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
