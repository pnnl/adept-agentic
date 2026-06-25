"""Configuration via Pydantic settings (reads from environment / .env)."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = {{MCP_PORT}}
    redis_url: str = "redis://{{NAME}}_redis:6379/0"
    uploaded_files_dir: str = "/app/data/uploaded_files"
    data_dir: str = "/app/data/{{NAME}}"
    results_dir: str = "/app/data/{{NAME}}/results"
    device: str = "cpu"

    model_config = {"env_prefix": "{{NAME_UPPER}}_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
