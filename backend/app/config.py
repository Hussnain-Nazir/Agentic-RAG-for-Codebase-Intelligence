from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-side configuration loaded from environment variables."""

    database_url: str = "postgresql+asyncpg://prism:prism@postgres:5432/prism"
    jwt_secret: str | None = None

    github_app_id: str | None = None
    github_app_private_key_path: str = "/run/secrets/github_app_key.pem"
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_webhook_secret: str | None = None

    model_a_name: str | None = None
    model_a_base_url: str | None = None
    model_a_api_key: str | None = None
    model_a_timeout: int = 60

    model_b_name: str | None = None
    model_b_base_url: str | None = None
    model_b_api_key: str | None = None
    model_b_timeout: int = 60

    embedding_model_name: str = "BAAI/bge-small-en-v1.5"

    web_search_provider: str | None = None
    web_search_api_key: str | None = None

    max_zip_size_mb: int = 200
    max_file_size_mb: float = 1.5
    max_concurrent_index_jobs: int = 2

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
