"""Configuration via Pydantic settings (reads from environment / .env)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 9004
    redis_url: str = "redis://academy_redis:6379/0"
    log_level: str = "INFO"

    # Globus Auth
    globus_client_id: str = ""
    globus_client_secret: str = ""
    globus_default_transfer_endpoint: str = ""
    globus_default_compute_endpoint: str = ""
    globus_default_search_index: str = ""

    model_config = {"env_prefix": "ACADEMY_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
